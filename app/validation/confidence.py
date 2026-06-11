"""STT-confidence gating.

Flags transcript spans whose ASR confidence is below threshold so the reviewer can
double-check easily-misheard content (drug names, numbers, dosages). These spans
also seed ``LOW_STT_CONFIDENCE`` risk markers.
"""
from __future__ import annotations

from app.schemas.transcript import CleanTranscript, RawTranscript


def low_confidence_span_ids(
    transcript: RawTranscript | CleanTranscript,
    threshold: float,
) -> list[str]:
    return [s.id for s in transcript.segments if s.confidence < threshold]
