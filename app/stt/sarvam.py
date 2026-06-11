"""Sarvam V3 speech-to-text (``saaras:v3``).

Two real paths (see ``docs/ARCHITECTURE.md`` §STT):
  • **Real-time** ``speech_to_text.transcribe`` — immediate English transcript, **no
    speaker labels** (≤30 s per request).
  • **Batch** ``speech_to_text_job`` with ``with_diarization`` — accurate,
    **doctor/patient speaker-labeled** + timestamped transcript for full consults.

``transcribe_for_session`` prefers the diarized batch path for accuracy and falls
back to real-time if batch errors (so a note is never blocked). ``get_stt`` returns
``MockSarvamSTT`` when no key is set, so the app and tests run with no credentials.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from typing import Any

from app.config import Settings, get_settings
from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment

logger = logging.getLogger(__name__)


def _approx_duration_s(audio: bytes, bytes_per_second: int = 32000) -> float:
    """Rough seconds for a 16 kHz mono 16-bit PCM WAV (~32000 bytes/s, ~44B header)."""
    return max(0.0, (len(audio) - 44) / bytes_per_second)


def _role_for(speaker_id: Any, role_map: dict[str, SpeakerRole]) -> SpeakerRole:
    """Map Sarvam diarization speaker ids → clinical roles by first-seen order.

    Diarization yields anonymous speakers (speaker_0, speaker_1, ...), not roles.
    We assign first-seen → DOCTOR, second → PATIENT, rest → OTHER. This is a
    reviewable heuristic; the doctor can correct attribution during sign-off.
    """
    key = str(speaker_id)
    if key not in role_map:
        order = len(role_map)
        role_map[key] = (
            SpeakerRole.DOCTOR if order == 0 else SpeakerRole.PATIENT if order == 1 else SpeakerRole.OTHER
        )
    return role_map[key]


class SarvamSTT:
    """Real Sarvam V3 client (official ``sarvamai`` SDK)."""

    def __init__(self, settings: Settings) -> None:
        from sarvamai import SarvamAI  # deferred

        self.settings = settings
        self.client = SarvamAI(api_subscription_key=settings.sarvam_api_key)

    @property
    def available(self) -> bool:
        return True

    # ── Real-time (immediate, unlabeled) ─────────────────────────────────────
    def transcribe(self, audio: bytes, *, session_id: str) -> RawTranscript:
        resp = self.client.speech_to_text.transcribe(
            file=("audio.wav", audio),
            model=self.settings.sarvam_stt_model,
            mode=self.settings.sarvam_mode,
            language_code=self.settings.sarvam_language_code,
            input_audio_codec="wav",
        )
        lang = getattr(resp, "language_code", None) or "en-IN"
        conf = float(getattr(resp, "language_probability", None) or 1.0)

        diarized = getattr(resp, "diarized_transcript", None)
        entries = getattr(diarized, "entries", None) if diarized else None
        if entries:
            return _segments_from_entries(session_id, entries, lang)

        # No diarization in real-time → a single UNKNOWN-speaker segment.
        return RawTranscript(
            session_id=session_id,
            segments=[TranscriptSegment(
                id="seg-0001", speaker=SpeakerRole.UNKNOWN,
                text=getattr(resp, "transcript", "") or "", language=lang, confidence=conf,
            )],
        )

    # ── Batch (accurate, diarized) ───────────────────────────────────────────
    def transcribe_diarized(self, audio: bytes, *, session_id: str) -> RawTranscript:
        tmpdir = tempfile.mkdtemp(prefix="sarvam_")
        in_path = os.path.join(tmpdir, f"{session_id}.wav")
        out_dir = os.path.join(tmpdir, "out")
        try:
            with open(in_path, "wb") as fh:
                fh.write(audio)

            job = self.client.speech_to_text_job.create_job(
                model=self.settings.sarvam_stt_model,
                mode=self.settings.sarvam_mode,
                with_diarization=True,
                with_timestamps=True,
                num_speakers=self.settings.sarvam_num_speakers,
                language_code=None if self.settings.sarvam_language_code == "unknown"
                else self.settings.sarvam_language_code,
            )
            job.upload_files([in_path])
            job.start()
            job.wait_until_complete(poll_interval=5, timeout=self.settings.sarvam_batch_timeout_s)
            if not job.is_successful():
                raise RuntimeError(f"Sarvam batch job not successful: {job.get_status().job_state}")

            # NOTE: get_file_results() returns only per-file status metadata — NOT the
            # transcript. The transcript lives in the job's output files, which must be
            # downloaded. download_outputs() writes one ``<input_filename>.json`` per file.
            job.download_outputs(out_dir)
            return _parse_batch_output_dir(session_id, out_dir)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # ── Dispatch + fallback ──────────────────────────────────────────────────
    def transcribe_for_session(self, audio: bytes, *, session_id: str, diarize: bool | None = None) -> RawTranscript:
        diarize = self.settings.sarvam_diarize if diarize is None else diarize
        # Real-time STT is capped at 30s; only use it as a fallback for short clips.
        short_enough = _approx_duration_s(audio) <= 28.0
        if diarize:
            try:
                result = self.transcribe_diarized(audio, session_id=session_id)
                chars = sum(len(s.text or "") for s in result.segments)
                logger.info("Sarvam batch diarized: segments=%d chars=%d", len(result.segments), chars)
                if chars > 0:
                    return result
                logger.warning("Sarvam batch returned an empty transcript.")
                if not short_enough:
                    # Real-time cannot help with >30s audio — return the (empty)
                    # batch result so the caller reports "no speech detected".
                    return result
            except Exception as exc:  # never block the note on a batch failure
                logger.warning("Sarvam batch diarization failed (%s).", exc)
                if not short_enough:
                    # Real-time would 400 on >30s; surface the real batch error.
                    raise
        rt = self.transcribe(audio, session_id=session_id)
        logger.info("Sarvam real-time: segments=%d chars=%d",
                    len(rt.segments), sum(len(s.text or "") for s in rt.segments))
        return rt


def _segments_from_entries(session_id: str, entries: list, lang: str) -> RawTranscript:
    role_map: dict[str, SpeakerRole] = {}
    segments: list[TranscriptSegment] = []
    for i, e in enumerate(entries):
        get = (lambda k, d=None: getattr(e, k, None) if not isinstance(e, dict) else e.get(k, d))
        segments.append(TranscriptSegment(
            id=f"seg-{i + 1:04d}",
            speaker=_role_for(get("speaker_id", i), role_map),
            text=get("transcript", "") or "",
            language=lang,
            start_ms=int(float(get("start_time_seconds", 0) or 0) * 1000),
            end_ms=int(float(get("end_time_seconds", 0) or 0) * 1000),
            confidence=1.0,
        ))
    return RawTranscript(session_id=session_id, segments=segments)


def _parse_batch_output_dir(session_id: str, out_dir: str) -> RawTranscript:
    """Parse Sarvam batch *output files* (downloaded JSON) → diarized segments.

    Each output file is the STT response for one input: it carries ``transcript``,
    ``language_code`` and (when diarization is on) ``diarized_transcript.entries``.
    """
    if not os.path.isdir(out_dir):
        return RawTranscript(session_id=session_id, segments=[])
    for fname in sorted(os.listdir(out_dir)):
        if not fname.lower().endswith(".json"):
            continue
        try:
            data = json.loads(open(os.path.join(out_dir, fname), encoding="utf-8").read())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        lang = data.get("language_code") or "en-IN"
        diar = data.get("diarized_transcript")
        entries = diar.get("entries") if isinstance(diar, dict) else None
        if entries:
            return _segments_from_entries(session_id, entries, lang)
        text = data.get("transcript")
        if text:
            return RawTranscript(session_id=session_id, segments=[TranscriptSegment(
                id="seg-0001", speaker=SpeakerRole.UNKNOWN, text=text, language=lang)])
    return RawTranscript(session_id=session_id, segments=[])


# ── Mock (no credentials) ────────────────────────────────────────────────────
#: The brief's ENT consultation, diarized — used for keyless demos and tests.
_CANNED: list[tuple[SpeakerRole, str, float]] = [
    (SpeakerRole.DOCTOR, "What brings you here today?", 0.98),
    (SpeakerRole.PATIENT, "I have throat pain for two months.", 0.93),
    (SpeakerRole.DOCTOR, "Any difficulty swallowing?", 0.97),
    (SpeakerRole.PATIENT, "Yes, mostly with solid foods.", 0.9),
    (SpeakerRole.DOCTOR, "Any fever?", 0.99),
    (SpeakerRole.PATIENT, "No.", 0.99),
    (SpeakerRole.DOCTOR, "Any other medical problems?", 0.96),
    (SpeakerRole.PATIENT, "No.", 0.99),
    (SpeakerRole.DOCTOR, "You also mentioned nasal discharge?", 0.92),
    (SpeakerRole.PATIENT, "Yes, frequent discharge.", 0.88),
    (SpeakerRole.DOCTOR, "Examination shows granular posterior pharyngeal wall, "
                         "grade 2 tonsillar hypertrophy, and DNS towards left.", 0.84),
]


class MockSarvamSTT:
    available = False  # signals "not the real provider" to callers/telemetry

    def transcribe(self, audio: bytes, *, session_id: str) -> RawTranscript:
        segments = [
            TranscriptSegment(
                id=f"seg-{i + 1:04d}", speaker=spk, text=text, language="en-IN",
                start_ms=i * 4000, end_ms=i * 4000 + 3500, confidence=conf,
            )
            for i, (spk, text, conf) in enumerate(_CANNED)
        ]
        return RawTranscript(session_id=session_id, segments=segments)

    def transcribe_for_session(self, audio: bytes, *, session_id: str, diarize: bool | None = None) -> RawTranscript:
        return self.transcribe(audio, session_id=session_id)


def get_stt(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.use_sarvam:
        try:
            return SarvamSTT(settings)
        except Exception:
            return MockSarvamSTT()
    return MockSarvamSTT()
