"""WebSocket audio ingest.

Wire protocol:
  • binary frames  → raw PCM/audio bytes, appended to a per-session buffer.
  • text frames    → JSON control messages: {"action": "start"|"stop", ...}.

Outbound JSON events: ``stage_update``, ``final_segment``, ``risk_warning``,
``draft_ready``, ``error``. On ``stop`` we transcribe the buffer (Sarvam V3 +
diarization), run the grounded pipeline, and move the session to DRAFT for review.

This is a deliberately simple batch-at-stop skeleton; a production build would push
chunks to Sarvam's streaming endpoint and emit ``partial_transcript`` events live
(buffering/backpressure hooks are noted inline).
"""
from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings
from app.pipeline.orchestrator import run_pipeline
from app.schemas.session import ConsultationSession, ReviewState
from app.stt.sarvam import get_stt
from app.store import SessionStore
from app.templates.registry import get_registry


# Minimum captured-audio size; below this the recording is effectively silent.
_MIN_AUDIO_BYTES = 1024


async def consultation_ws(websocket: WebSocket, store: SessionStore, settings: Settings) -> None:
    await websocket.accept()
    session: ConsultationSession | None = None
    buffer = bytearray()

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if message.get("bytes") is not None:
                # Backpressure hook: cap/flush buffer here for true streaming.
                buffer.extend(message["bytes"])
                continue

            if message.get("text") is None:
                continue

            data = json.loads(message["text"])
            action = data.get("action")

            if action == "start":
                sid = data.get("session_id") or f"sess-{uuid.uuid4().hex[:12]}"
                template_id = data.get("template_id", "soap")
                session = ConsultationSession(
                    session_id=sid, template_id=template_id, state=ReviewState.LISTENING
                )
                store.create(session)
                buffer.clear()
                await websocket.send_json(
                    {"type": "stage_update", "stage": "listening", "session_id": sid}
                )

            elif action == "stop":
                if session is None:
                    await websocket.send_json({"type": "error", "message": "no active session"})
                    continue

                if len(buffer) < _MIN_AUDIO_BYTES:
                    session.transition(ReviewState.ESCALATION_REQUIRED)
                    await websocket.send_json(
                        {"type": "error", "stage": "processing", "session_id": session.session_id,
                         "state": session.state.value, "message": "no audible speech captured"}
                    )
                    continue

                session.transition(ReviewState.PROCESSING)
                await websocket.send_json(
                    {"type": "stage_update", "stage": "processing", "session_id": session.session_id}
                )

                try:
                    stt = get_stt(settings)
                    # Batch-diarized when available (accurate, speaker-labeled), with
                    # automatic real-time fallback so a note is never blocked. STT and the
                    # pipeline are blocking, so run them in a thread to keep the event loop
                    # responsive (ping/pong, concurrent consults).
                    raw = await asyncio.to_thread(
                        stt.transcribe_for_session, bytes(buffer), session_id=session.session_id
                    )
                    if not any((seg.text or "").strip() for seg in raw.segments):
                        raise RuntimeError("no speech detected in audio")
                    for seg in raw.segments:
                        await websocket.send_json(
                            {"type": "final_segment", "speaker": seg.speaker.value,
                             "text": seg.text, "span_id": seg.id, "confidence": seg.confidence}
                        )

                    await websocket.send_json(
                        {"type": "stage_update", "stage": "generating", "session_id": session.session_id}
                    )
                    template = get_registry().get(session.template_id)
                    result = await asyncio.to_thread(run_pipeline, raw, template, settings=settings)

                    session.raw_transcript = raw
                    session.clean_transcript = result.clean
                    session.extraction = result.extraction
                    session.note = result.note
                    session.risk = result.risk
                    session.template_version = template.version
                    store.set_result(session.session_id, result)
                    session.transition(ReviewState.DRAFT)

                    for marker in result.risk.markers:
                        await websocket.send_json(
                            {"type": "risk_warning", "severity": marker.severity.value,
                             "risk_type": marker.type.value, "message": marker.message,
                             "evidence_span_ids": marker.evidence_span_ids}
                        )

                    await websocket.send_json(
                        {"type": "draft_ready", "session_id": session.session_id,
                         "state": session.state.value, "risk_score": result.risk.score,
                         "note_markdown": result.note.to_markdown(),
                         "grounding": result.grounding.model_dump()}
                    )
                except Exception as exc:
                    # STT/LLM failure → escalate, never emit a silent blank record.
                    session.transition(ReviewState.ESCALATION_REQUIRED)
                    await websocket.send_json(
                        {"type": "error", "stage": "processing", "session_id": session.session_id,
                         "state": session.state.value, "message": f"processing failed: {exc}"}
                    )

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        return
