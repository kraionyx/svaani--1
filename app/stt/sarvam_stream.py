"""Real-time streaming STT over Sarvam's WebSocket (``saaras:v3`` streaming).

The WS consult handler forwards the browser's 16 kHz PCM frames here and gets back
live transcript segments as people speak. Streaming has **no diarization** (that is
batch-only), so segments arrive speaker-unlabeled; the handler runs the batch-diarized
pass on stop to recover doctor/patient labels (the hybrid in ``app/audio/ws.py``).

Validated against the live API: 16 kHz ``pcm_s16le`` chunks → first segment in <1 s.
Audio MUST be 16 kHz mono signed-16-bit little-endian PCM (the only supported rate
besides 8 kHz); the browser recorder downsamples to 16 kHz before sending.
"""
from __future__ import annotations

import base64
import io
import wave
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.config import Settings
from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment

_STREAMING_MODES = {"transcribe", "translate", "verbatim", "translit", "codemix"}


def streaming_available(settings: Settings) -> bool:
    """True when a real Sarvam key is set and streaming is enabled."""
    return bool(settings.sarvam_api_key) and settings.streaming_stt


@asynccontextmanager
async def open_stream(settings: Settings) -> AsyncIterator[Any]:
    """Open a Sarvam streaming-STT socket configured from settings.

    Yields the async socket client (``transcribe()`` to send a base64 PCM chunk,
    async-iterate / ``recv()`` to read responses, ``flush()`` to finalize).
    """
    from sarvamai import AsyncSarvamAI  # deferred — keeps the app importable without the SDK

    client = AsyncSarvamAI(api_subscription_key=settings.sarvam_api_key)
    mode = settings.sarvam_mode if settings.sarvam_mode in _STREAMING_MODES else "translate"
    # Honour SCRIBE_SARVAM_LANGUAGE_CODE. The default ("unknown") keeps per-utterance
    # auto-detect, but auto-detect re-runs on every short utterance and easily confuses
    # acoustically similar languages (e.g. Telugu↔Tamil) — the source of spurious
    # third-language words. Pinning the spoken language (e.g. "te-IN") removes that
    # misdetection. Previously this was hardcoded to "unknown" and the setting was ignored.
    lang = settings.sarvam_language_code or "unknown"
    async with client.speech_to_text_streaming.connect(
        language_code=lang,                 # 'unknown' → auto-detect; pin (e.g. 'te-IN') to stop drift
        model=settings.sarvam_streaming_model,
        mode=mode,
        input_audio_codec="pcm_s16le",      # raw 16-bit little-endian PCM frames
        sample_rate="16000",
    ) as sock:
        yield sock


def encode_chunk(pcm16: bytes) -> str:
    """Base64-encode a raw PCM16 audio chunk for ``socket.transcribe(audio=...)``."""
    return base64.b64encode(pcm16).decode("ascii")


def pcm16_to_wav(pcm16: bytes, rate: int = 16000) -> bytes:
    """Wrap raw 16 kHz mono PCM16 frames in a WAV container.

    The streaming path receives headerless PCM; the batch-diarized pass on stop needs a
    real WAV file, so we wrap the accumulated audio before handing it to ``SarvamSTT``.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16)
    return buf.getvalue()


def transcript_of(resp: Any) -> str | None:
    """Extract the transcript text from a streaming response, or None.

    Sarvam streaming is turn-based: each ``type == "data"`` message carries the
    finalized transcript for one detected utterance.
    """
    if getattr(resp, "type", None) != "data":
        return None
    data = getattr(resp, "data", None)
    text = getattr(data, "transcript", None) if data is not None else None
    return text or None


def raw_from_segments(session_id: str, segments: list[tuple[str, str]]) -> RawTranscript:
    """Build a RawTranscript from streamed ``(segment_id, text)`` pairs.

    Used as the fallback transcript when batch diarization is unavailable/fails — the
    note is never blocked; it just lacks speaker labels (all UNKNOWN).
    """
    return RawTranscript(
        session_id=session_id,
        segments=[
            TranscriptSegment(id=sid, speaker=SpeakerRole.UNKNOWN, text=text)
            for sid, text in segments
        ],
    )
