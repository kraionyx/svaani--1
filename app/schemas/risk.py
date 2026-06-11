"""Output 5 (revised) — Risk markers / risk score.

A NON-AUTHORITATIVE annotation layer. The LLM flags risk indications that are
*already present in the conversation* (red-flag symptoms, mentioned allergies,
mentioned drugs/dosages, stated abnormal vitals) and surfaces them as preview
warnings for the doctor. It highlights; it never diagnoses, prescribes, or decides.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class RiskSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class RiskType(str, Enum):
    RED_FLAG_SYMPTOM = "red_flag_symptom"
    ALLERGY_MENTIONED = "allergy_mentioned"
    MEDICATION_MENTIONED = "medication_mentioned"
    DOSAGE_MENTIONED = "dosage_mentioned"
    ABNORMAL_VITAL = "abnormal_vital"
    LOW_STT_CONFIDENCE = "low_stt_confidence"
    OTHER = "other"


class RiskMarker(BaseModel):
    type: RiskType
    severity: RiskSeverity = RiskSeverity.INFO
    message: str
    evidence_span_ids: list[str] = Field(
        default_factory=list, description="Transcript spans that triggered this marker."
    )
    authoritative: bool = Field(default=False, frozen=True)  # always False by contract

    @field_validator("authoritative")
    @classmethod
    def _never_authoritative(cls, _v: bool) -> bool:
        # A risk marker is an attention aid, never an authoritative clinical decision.
        return False


class RiskAssessment(BaseModel):
    session_id: str
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Aggregate attention score [0,1].")
    markers: list[RiskMarker] = Field(default_factory=list)
    disclaimer: str = (
        "Risk markers highlight items already present in the conversation for the "
        "reviewing clinician's attention. They are not diagnoses, recommendations, "
        "or clinical decisions."
    )
