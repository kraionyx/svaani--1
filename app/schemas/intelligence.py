"""Conversation-intelligence schemas (Goals 1-5).

These describe *who is in the room and how confident we are* — never clinical content.
They sit alongside the five clinical outputs and feed the speaker timeline, the
complexity-driven real-time/batch decision, and the confidence indicator.

Founding-principle safe: nothing here invents or decides clinical facts. Relationship
resolution only answers "whose symptoms are these?" so the scribe attributes what was
said to the right person instead of assuming the speaker is the patient.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.transcript import SpeakerRole


class ConversationKind(str, Enum):
    SINGLE_SPEAKER = "single_speaker"
    DOCTOR_PATIENT = "doctor_patient"
    DOCTOR_PARENT = "doctor_parent"
    DOCTOR_SPOUSE = "doctor_spouse"
    DOCTOR_GUARDIAN = "doctor_guardian"
    DOCTOR_TRANSLATOR = "doctor_translator"
    MULTI_FAMILY = "multi_family"
    TELEMEDICINE_GROUP = "telemedicine_group"
    UNKNOWN = "unknown"


class SpeakerRelationship(str, Enum):
    SELF = "self"            # the speaker IS the patient
    PARENT = "parent"
    SPOUSE = "spouse"
    CHILD = "child"
    SIBLING = "sibling"
    GUARDIAN = "guardian"
    CAREGIVER = "caregiver"
    TRANSLATOR = "translator"
    CLINICIAN = "clinician"
    NURSE = "nurse"
    OTHER = "other"
    UNKNOWN = "unknown"


class ConfidenceBand(str, Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class ReferencedSubject(BaseModel):
    """A distinct person the consultation is clinically ABOUT (Goal 1, multi-patient).

    A single consult can reference more than one patient (e.g. a parent describing two
    children, or "my son has fever and I also have a cough"). Each subject carries the
    transcript spans that evidence it so the timeline/note can attribute correctly.
    """

    label: str                                   # e.g. 'son', 'father', 'patient'
    relationship: SpeakerRelationship = SpeakerRelationship.UNKNOWN
    evidence_span_ids: list[str] = Field(default_factory=list)


class SpeakerProfile(BaseModel):
    """One resolved participant in the consultation."""

    speaker_label: str                      # diarized label, e.g. 'speaker_0'
    role: SpeakerRole = SpeakerRole.UNKNOWN
    relationship: SpeakerRelationship = SpeakerRelationship.UNKNOWN
    # WHO this speaker's clinical statements are ABOUT (the referenced patient). For a
    # mother speaking for her son, the mother's subject is 'son', not herself.
    subject_patient: str | None = None
    span_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0


class ConversationProfile(BaseModel):
    """Goal 1/2/4 result — relationships, complexity, and confidence for one consult.

    NOT clinical content; a transparency + routing aid. Grounded like everything else:
    every inference cites the transcript spans (``evidence_span_ids``) it came from.
    """

    session_id: str
    kind: ConversationKind = ConversationKind.UNKNOWN
    speakers: list[SpeakerProfile] = Field(default_factory=list)
    speaker_count: int = 0
    # The patient the consultation is primarily ABOUT (e.g. 'son', 'patient', 'father').
    referenced_patient: str | None = None
    referenced_patient_evidence: list[str] = Field(default_factory=list)
    # All distinct people the consult references (Goal 1, multi-patient). The first entry
    # corresponds to ``referenced_patient``; a single-patient consult has exactly one.
    referenced_subjects: list[ReferencedSubject] = Field(default_factory=list)

    # Complexity (Goal 2)
    complexity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_complex: bool = False
    complexity_signals: list[str] = Field(default_factory=list)

    # Confidence (Goal 4)
    audio_confidence: float = 1.0
    confidence_band: ConfidenceBand = ConfidenceBand.HIGH
    confidence_reasons: list[str] = Field(default_factory=list)

    def summary(self) -> dict:
        """Compact dict for WS events / the confidence chip."""
        return {
            "kind": self.kind.value,
            "speaker_count": self.speaker_count,
            "referenced_patient": self.referenced_patient,
            "referenced_subjects": [s.model_dump(mode="json") for s in self.referenced_subjects],
            "complexity_score": round(self.complexity_score, 3),
            "is_complex": self.is_complex,
            "confidence_band": self.confidence_band.value,
            "confidence_pct": round(self.audio_confidence * 100),
            "confidence_reasons": self.confidence_reasons,
            "complexity_signals": self.complexity_signals,
        }
