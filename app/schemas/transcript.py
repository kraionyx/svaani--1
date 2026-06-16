"""Output 1 (raw) and Output 2 (clean) transcript schemas.

Every downstream artifact cites ``TranscriptSegment.id`` values as its provenance,
so segment ids are the unit of traceability for the whole platform.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class SpeakerRole(str, Enum):
    DOCTOR = "doctor"
    PATIENT = "patient"
    CAREGIVER = "caregiver"   # parent/spouse/guardian speaking for the patient
    NURSE = "nurse"
    TRANSLATOR = "translator"
    OTHER = "other"
    UNKNOWN = "unknown"


class TranscriptSegment(BaseModel):
    """One diarized utterance from Sarvam V3."""

    id: str = Field(..., description="Stable id, e.g. 'seg-0001' — referenced as provenance.")
    speaker: SpeakerRole = SpeakerRole.UNKNOWN
    # Raw diarization label from the STT provider (e.g. 'speaker_0'). Preserved so we can
    # re-assign clinical roles by BEHAVIOR (app.stt.doctor_detect) instead of trusting the
    # provider's first-seen order, and so the speaker timeline can show the original grouping.
    diarized_label: str | None = None
    text: str = ""
    language: str = "en-IN"          # detected source language (ISO-ish); Sarvam outputs English text
    start_ms: int = 0
    end_ms: int = 0
    confidence: float = 1.0          # ASR confidence [0,1]
    is_final: bool = True            # False for partials that may be superseded


class RawTranscript(BaseModel):
    """Output 1 — exactly what Sarvam V3 produced. Verbatim, never edited."""

    session_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(f"{s.speaker.value}: {s.text}" for s in self.segments if s.is_final)

    def segment_ids(self) -> set[str]:
        return {s.id for s in self.segments}


class Correction(BaseModel):
    """A single STT fix applied by the clean stage. Meaning must be preserved."""

    span_id: str
    original: str
    corrected: str
    reason: str = ""


class CleanTranscript(BaseModel):
    """Output 2 — obvious STT mistakes corrected, clinical meaning preserved.

    Nothing is *added*; corrections are logged and low-confidence spans flagged so
    a reviewer can audit every change against the raw transcript.
    """

    session_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    low_confidence_span_ids: list[str] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n".join(f"{s.speaker.value}: {s.text}" for s in self.segments if s.is_final)

    def segment_ids(self) -> set[str]:
        return {s.id for s in self.segments}
