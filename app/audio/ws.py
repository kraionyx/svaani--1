"""WebSocket consultation ingest — real-time streaming + batch-diarized hybrid.

Wire protocol:
  • binary frames → raw 16 kHz mono PCM16 audio chunks (the browser recorder's output).
  • text frames   → JSON control: {"action": "start"|"stop"|"ping", ...}.

While the doctor records, audio is forwarded to Sarvam's **streaming** STT and live,
speaker-unlabeled segments are emitted as ``final_segment`` events (sub-second). On
``stop`` the buffered audio runs the **batch-diarized** pass to recover doctor/patient
labels, then the grounded pipeline runs and results stream back. Streaming has no
diarization, so this hybrid gives both live feedback and accurate final labels.

If streaming is unavailable (no key / disabled / connect fails) it degrades to
batch-at-stop. If batch diarization fails, the live streamed segments become the
(unlabeled) transcript — the note is never blocked.

Outbound events: ``stage_update``, ``partial_transcript``, ``final_segment``,
``risk_warning``, ``draft_ready``, ``error``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings
from app.llm.base import get_llm
from app.pipeline.complexity import assess_complexity
from app.pipeline.inference_mode import (
    decide_mode,
    mode_switch_notice,
    split_mode_choice,
)
from app.pipeline.narrate import stream_section_prose
from app.pipeline.orchestrator import run_pipeline
from app.pipeline.subjects import resolve_relationships
from app.schemas.intelligence import ConversationProfile
from app.schemas.review import InferenceMode
from app.schemas.session import ConsultationSession, ReviewState
from app.schemas.transcript import RawTranscript
from app.security.rbac import Principal
from app.stt import sarvam_stream
from app.stt.doctor_detect import assign_clinical_roles
from app.stt.sarvam import get_stt
from app.store import SessionStore
from app.templates.registry import get_registry

logger = logging.getLogger("svaani.audio")

# Minimum captured-audio size; below this the recording is effectively silent.
_MIN_AUDIO_BYTES = 1024


async def consultation_ws(
    websocket: WebSocket, store: SessionStore, settings: Settings, principal: Principal
) -> None:
    await websocket.accept()
    session: ConsultationSession | None = None
    import tempfile
    import struct
    import os

    audio_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    audio_path = audio_temp.name
    audio_size = 0
    audio_lock = asyncio.Lock()
    live_segments: list[tuple[str, str]] = []  # (segment_id, text) from streaming STT
    sock = None                                # open Sarvam streaming socket
    stream_cm = None                           # its async context manager
    reader_task: asyncio.Task | None = None

    async def _read_stream() -> None:
        """Pump streaming-STT responses to the browser as live segments."""
        try:
            async for resp in sock:
                text = sarvam_stream.transcript_of(resp)
                if not text:
                    continue
                seg_id = f"seg-{len(live_segments) + 1:04d}"
                live_segments.append((seg_id, text))
                await websocket.send_json({
                    "type": "final_segment", "speaker": "unknown",
                    "text": text, "span_id": seg_id, "confidence": 1.0,
                })
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — streaming errors must not kill the consult
            logger.warning("streaming reader stopped", exc_info=True)

    async def _close_stream() -> None:
        nonlocal sock, stream_cm, reader_task
        if sock is not None:
            try:
                await sock.flush()
                # Let the flush's trailing final(s) arrive before we cancel the reader.
                # Wait the full window if nothing has arrived yet; once segments appear,
                # stop ~0.3s after they stabilize. Bounded so stop never hangs. Trimmed for
                # responsiveness: poll faster (0.15s) and require fewer stable ticks so the
                # common case (everything already streamed) drains in ~0.3s instead of 0.6s,
                # and a silent tail caps at 1.6s instead of 3.0s.
                last, stable, elapsed = len(live_segments), 0, 0.0
                while elapsed < 1.6:
                    await asyncio.sleep(0.15); elapsed += 0.15
                    n = len(live_segments)
                    if n > last:
                        last, stable = n, 0
                    elif n > 0:
                        stable += 1
                        if stable >= 2:
                            break
            except Exception:  # noqa: BLE001
                pass
        if reader_task is not None:
            reader_task.cancel()
            try:
                await reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            reader_task = None
        if stream_cm is not None:
            try:
                await stream_cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            stream_cm = sock = None

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            # ── audio frame ──────────────────────────────────────────────────
            if message.get("bytes") is not None:
                chunk = message["bytes"]
                async with audio_lock:
                    audio_temp.write(chunk)
                    audio_size += len(chunk)
                if sock is not None:
                    try:
                        await sock.transcribe(audio=sarvam_stream.encode_chunk(chunk), sample_rate=16000)
                    except Exception:  # noqa: BLE001 — drop streaming, keep buffering for batch
                        logger.warning("streaming send failed; continuing buffer-only", exc_info=True)
                        await _close_stream()
                continue

            if message.get("text") is None:
                continue
            data = json.loads(message["text"])
            action = data.get("action")

            # ── start ────────────────────────────────────────────────────────
            if action == "start":
                sid = data.get("session_id") or f"sess-{uuid.uuid4().hex[:12]}"
                template_id = data.get("template_id", "soap")
                # Goal 3: per-consult mode choice (auto | realtime | batch).
                auto_mode, manual_mode = split_mode_choice(
                    data.get("mode"), legacy_auto=bool(data.get("auto", False))
                )
                session = ConsultationSession(
                    session_id=sid, template_id=template_id, state=ReviewState.LISTENING,
                    practitioner_id=principal.id,  # owner = authenticated caller (per-user isolation)
                    auto_mode=auto_mode, manual_mode=manual_mode,
                )
                store.create(session)
                # Count WS consults toward the doctor too (REST POST /sessions already does
                # this) so session totals in the admin console are consistent across both
                # capture paths instead of under-counting streaming consults.
                try:
                    from app.logging_service import get_logging_service
                    get_logging_service().update_doctor(
                        user_id=principal.id, increment_sessions=1, feature="session_create",
                        email=getattr(principal, "email", None),
                    )
                except Exception:  # noqa: BLE001 — analytics must never break a consult
                    pass
                async with audio_lock:
                    audio_temp.seek(0)
                    audio_temp.truncate(0)
                    audio_temp.write(b'\0' * 44)  # WAV header placeholder
                    audio_size = 0
                live_segments.clear()
                streaming = False
                if sarvam_stream.streaming_available(settings):
                    try:
                        stream_cm = sarvam_stream.open_stream(settings)
                        sock = await stream_cm.__aenter__()
                        reader_task = asyncio.create_task(_read_stream())
                        streaming = True
                    except Exception:  # noqa: BLE001 — fall back to batch-at-stop
                        logger.warning("streaming STT connect failed; batch-at-stop", exc_info=True)
                        stream_cm = sock = None
                await websocket.send_json({
                    "type": "stage_update", "stage": "listening",
                    "session_id": sid, "streaming": streaming,
                })

            # ── stop ─────────────────────────────────────────────────────────
            elif action == "stop":
                if session is None:
                    await websocket.send_json({"type": "error", "message": "no active session"})
                    continue
                await _close_stream()  # cancel reader first → no concurrent sends below

                if audio_size < _MIN_AUDIO_BYTES and not live_segments:
                    session.transition(ReviewState.ESCALATION_REQUIRED)
                    await websocket.send_json({
                        "type": "error", "stage": "processing", "session_id": session.session_id,
                        "state": session.state.value, "message": "no audible speech captured",
                    })
                    continue
                # Finalize the WAV header
                async with audio_lock:
                    audio_temp.seek(0)
                    header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + audio_size, b'WAVE', b'fmt ', 16, 1, 1, 16000, 32000, 2, 16, b'data', audio_size)
                    audio_temp.write(header)
                    audio_temp.flush()

                await _finalize(websocket, store, settings, session, audio_path, live_segments)

            # ── cancel ───────────────────────────────────────────────────────
            elif action == "cancel":
                # Abort the consult: tear down the live stream and discard the session
                # without running the pipeline — no draft, no clinical record persisted.
                await _close_stream()
                if session is not None:
                    try:
                        store.delete(session.session_id)
                    except Exception:  # noqa: BLE001 — best-effort cleanup
                        logger.info("cancel: could not delete session %s", session.session_id, exc_info=True)
                    session = None
                async with audio_lock:
                    audio_temp.seek(0)
                    audio_temp.truncate(0)
                    audio_temp.write(b'\0' * 44)
                    audio_size = 0
                live_segments.clear()
                await websocket.send_json({"type": "stage_update", "stage": "cancelled"})
                # The client closes right after; stop processing further frames.
                continue

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        return
    finally:
        await _close_stream()
        audio_temp.close()
        try:
            os.unlink(audio_path)
        except OSError:
            pass


async def _stream_note(websocket: WebSocket, note, llm, *, timeout_s: float) -> None:
    """Stream all non-empty sections' narrated prose CONCURRENTLY, token-by-token.

    Each section narrates in its own worker thread (the LLM stream is blocking); their
    chunks funnel through ONE merged queue so WS sends stay serialized (Starlette can't
    take concurrent sends). Latency is max(section) instead of sum(section). An overall
    ``timeout_s`` guards against a slow/hung section. Section text is accumulated back
    into the note so the persisted/exported note matches what was shown.
    """
    sections = [s for s in note.sections if not s.empty]
    if not sections:
        return
    loop = asyncio.get_running_loop()
    merged: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()
    texts: dict[str, str] = {s.section_id: "" for s in sections}

    def _worker(sec) -> None:
        try:
            for chunk in stream_section_prose(sec, llm):
                loop.call_soon_threadsafe(merged.put_nowait, (sec.section_id, chunk))
        except Exception:  # noqa: BLE001 — keep the deterministic text on failure
            logger.warning("section narration stream failed", exc_info=True)
        finally:
            loop.call_soon_threadsafe(merged.put_nowait, (sec.section_id, _SENTINEL))

    for sec in sections:  # fire all narrations at once
        loop.run_in_executor(None, _worker, sec)
        await websocket.send_json({
            "type": "note_chunk", "section_id": sec.section_id, "label": sec.label, "start": True,
        })

    remaining, done_ids, deadline = len(sections), set(), loop.time() + timeout_s
    while remaining > 0:
        try:
            sid, item = await asyncio.wait_for(merged.get(), timeout=max(0.1, deadline - loop.time()))
        except asyncio.TimeoutError:
            logger.warning("note streaming exceeded %ss; finishing with partial prose", timeout_s)
            break
        if item is _SENTINEL:
            remaining -= 1
            done_ids.add(sid)
            await websocket.send_json({"type": "note_chunk", "section_id": sid, "done": True})
        else:
            texts[sid] += item
            await websocket.send_json({"type": "note_chunk", "section_id": sid, "delta": item})

    for sec in sections:
        if texts[sec.section_id].strip():
            sec.content_text = texts[sec.section_id].strip()
        if sec.section_id not in done_ids:  # ensure the UI doesn't hang on a section
            await websocket.send_json({"type": "note_chunk", "section_id": sec.section_id, "done": True})


def _has_text(raw: RawTranscript) -> bool:
    return any((s.text or "").strip() for s in raw.segments)


async def _diarize(settings: Settings, session_id: str, audio: bytes | str) -> RawTranscript | None:
    """Run the bounded batch-diarized pass; return None if unavailable/slow/failed."""
    
    if isinstance(audio, str):
        size = os.path.getsize(audio)
        if size < _MIN_AUDIO_BYTES + 44:
            return None
        wav_input = audio
    else:
        if len(audio) < _MIN_AUDIO_BYTES:
            return None
        wav_input = sarvam_stream.pcm16_to_wav(audio, rate=16000)

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_stt(settings).transcribe_for_session, wav_input, session_id=session_id),
            timeout=settings.streaming_diarize_timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("diarization slow (>%ss); keeping live transcript", settings.streaming_diarize_timeout_s)
    except Exception:  # noqa: BLE001 — diarization failed; keep live transcript
        logger.warning("batch diarization failed; keeping live transcript", exc_info=True)
    return None


async def _emit_pass(
    websocket: WebSocket, store: SessionStore, settings: Settings,
    session: ConsultationSession, raw: RawTranscript, template, *, refine: bool,
) -> None:
    """Run the grounded pipeline on ``raw``, persist outputs, and emit to the client.

    ``refine=False`` (fast/only pass): deterministic note + token-streamed narration,
    emits ``analysis`` early then ``draft_ready``. ``refine=True``: single-call narration,
    emits ``refined`` (the client re-fetches the diarized transcript + sharpened outputs).
    """
    # Fast pass streams the prose; refine pass narrates in one call (already accurate).
    pipeline_settings = settings.model_copy(update={"narrative_notes": refine})
    result = await run_pipeline(raw, template, settings=pipeline_settings)

    session.raw_transcript = raw
    session.clean_transcript = result.clean
    session.extraction = result.extraction
    session.note = result.note
    session.risk = result.risk
    session.conversation_profile = result.profile
    session.template_version = template.version

    # Goals 3/4: stamp the authoritative real-time/batch label and surface the confidence
    # indicator. The Auto-escalation banner is emitted by _finalize (the moment it switches).
    if result.profile is not None:
        mode = decide_mode(result.profile, settings, auto=session.auto_mode, manual=session.manual_mode)
        session.inference_mode = mode.value
        await websocket.send_json({
            "type": "confidence_update", "session_id": session.session_id,
            "inference_mode": mode.value, **result.profile.summary(),
        })
    store.set_result(session.session_id, result)

    if refine:
        store.persist(session)
        await websocket.send_json({
            "type": "refined", "session_id": session.session_id,
            "risk_score": result.risk.score, "grounding": result.grounding.model_dump(),
        })
        return

    # Fast pass: populate Extraction/Risk/Grounding immediately, then stream the note.
    await websocket.send_json({
        "type": "analysis", "session_id": session.session_id,
        "extraction": result.extraction.model_dump(mode="json"),
        "risk": result.risk.model_dump(mode="json"),
        "grounding": result.grounding.model_dump(),
    })
    await websocket.send_json(
        {"type": "stage_update", "stage": "generating", "session_id": session.session_id}
    )
    if settings.narrative_notes:
        await _stream_note(websocket, result.note, get_llm(settings), timeout_s=settings.note_stream_timeout_s)
    if session.state is ReviewState.PROCESSING:
        session.transition(ReviewState.DRAFT)
    store.persist(session)
    for marker in result.risk.markers:
        await websocket.send_json({
            "type": "risk_warning", "severity": marker.severity.value,
            "risk_type": marker.type.value, "message": marker.message,
            "evidence_span_ids": marker.evidence_span_ids, "evidence_text": marker.evidence_text,
        })
    await websocket.send_json({
        "type": "draft_ready", "session_id": session.session_id, "state": session.state.value,
        "risk_score": result.risk.score, "note_markdown": result.note.to_markdown(),
        "grounding": result.grounding.model_dump(),
    })


def _diarized_profile(diar: RawTranscript, settings: Settings) -> ConversationProfile:
    """Resolve speaker roles + complexity on the DIARIZED transcript (rule-based, no LLM).

    Auto mode uses this to decide "is this consult complex?" — the live transcript can't be
    judged because streaming STT produces no speaker labels.
    """
    assign_clinical_roles(diar)
    profile = resolve_relationships(diar, None)
    assess_complexity(profile, diar, settings)
    return profile


async def _finalize(
    websocket: WebSocket,
    store: SessionStore,
    settings: Settings,
    session: ConsultationSession,
    audio_input: bytes | str,
    live_segments: list[tuple[str, str]],
) -> None:
    """On stop: run the flow for the doctor's per-consult mode (Goal 3).

    • real-time → live draft only (no diarization);
    • batch     → one accurate diarized pass (no live draft note);
    • hybrid    → live draft now, then ALWAYS diarize + refine (best balance);
    • auto      → live draft now, then diarize and replace it only if the consult is complex.
    """
    session.transition(ReviewState.PROCESSING)
    await websocket.send_json(
        {"type": "stage_update", "stage": "processing", "session_id": session.session_id}
    )
    try:
        template = get_registry().get(session.template_id)
        live_raw = sarvam_stream.raw_from_segments(session.session_id, live_segments)
        have_live = _has_text(live_raw)

        async def _single_diarized_pass() -> None:
            """One accurate pass: prefer the diarized transcript, fall back to live."""
            raw = await _diarize(settings, session.session_id, audio_input)
            if raw is None or not _has_text(raw):
                raw = live_raw
            if not _has_text(raw):
                raise RuntimeError("no speech detected in audio")
            assign_clinical_roles(raw)
            await _emit_pass(websocket, store, settings, session, raw, template, refine=False)

        if session.auto_mode:
            # Auto: instant draft, then diarize and REPLACE the draft only if it's complex.
            if not have_live:
                await _single_diarized_pass()
            else:
                await _emit_pass(websocket, store, settings, session, live_raw, template, refine=False)
                diar_raw = await _diarize(settings, session.session_id, audio_input)
                if diar_raw is not None and _has_text(diar_raw):
                    profile = _diarized_profile(diar_raw, settings)
                    if profile.is_complex:
                        await websocket.send_json({
                            **mode_switch_notice(profile, InferenceMode.AUTO_BATCH),
                            "session_id": session.session_id,
                        })
                        await _emit_pass(websocket, store, settings, session, diar_raw, template, refine=True)
        elif session.manual_mode == "hybrid":
            # Hybrid (best balance): instant draft for immediacy, then ALWAYS sharpen with the
            # diarized (speaker-labeled) pass — fast reply AND full accuracy on every consult.
            if have_live:
                await _emit_pass(websocket, store, settings, session, live_raw, template, refine=False)
                diar_raw = await _diarize(settings, session.session_id, audio_input)
                if diar_raw is not None and _has_text(diar_raw):
                    assign_clinical_roles(diar_raw)
                    await _emit_pass(websocket, store, settings, session, diar_raw, template, refine=True)
            else:
                await _single_diarized_pass()
        elif session.manual_mode == "batch":
            # Batch: live words already streamed for feedback; produce ONE accurate note now.
            await _single_diarized_pass()
        else:
            # Real-time: live draft only — no diarization (fastest; no speaker labels).
            if have_live:
                await _emit_pass(websocket, store, settings, session, live_raw, template, refine=False)
            else:
                await _single_diarized_pass()
    except Exception as exc:  # noqa: BLE001 — escalate, never emit a silent blank record
        session.transition(ReviewState.ESCALATION_REQUIRED)
        await websocket.send_json({
            "type": "error", "stage": "processing", "session_id": session.session_id,
            "state": session.state.value, "message": f"processing failed: {exc}",
        })
