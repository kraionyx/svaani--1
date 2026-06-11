"""Output 3 — Clinical Extraction JSON.

Contains ONLY entities mentioned in the conversation. Every item carries
``Provenance`` (the transcript spans it came from) so the grounding validator can
prove "only what was said". Medications that were *discussed* are captured verbatim
and marked ``authoritative=False`` — the AI never composes a prescription.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Provenance(BaseModel):
    """Where an extracted item came from, and how confident we are."""

    span_ids: list[str] = Field(default_factory=list, description="TranscriptSegment ids.")
    confidence: float = 1.0
    grounded: bool = True
    note: str | None = None


class ChiefComplaint(BaseModel):
    symptom: str
    duration: str | None = None
    type: str | None = None              # e.g. "Solids > Liquids"
    provenance: Provenance = Field(default_factory=Provenance)


class Allergy(BaseModel):
    substance: str
    reaction: str | None = None
    provenance: Provenance = Field(default_factory=Provenance)


class MedicationMention(BaseModel):
    """A medication that was *spoken about* in the consultation.

    Captured verbatim. NEVER authoritative — any real prescription is the doctor's
    explicit, manual action downstream. This is documentation of what was said.
    """

    name: str
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    duration: str | None = None
    verbatim_text: str = ""
    authoritative: bool = Field(default=False, frozen=True)  # always False by contract
    provenance: Provenance = Field(default_factory=Provenance)

    @field_validator("authoritative")
    @classmethod
    def _never_authoritative(cls, _v: bool) -> bool:
        # Hard contract: a discussed medication is never an authoritative prescription,
        # regardless of what a caller or the LLM tries to set.
        return False


class ExaminationFinding(BaseModel):
    """One examination finding, e.g. region='throat', finding='tonsillar_hypertrophy', value='Grade 2'."""

    region: str
    finding: str
    value: Any
    provenance: Provenance = Field(default_factory=Provenance)


class GroundedText(BaseModel):
    """A free-text clinical field with provenance (HPI, assessment, follow-up, ...)."""

    text: str
    provenance: Provenance = Field(default_factory=Provenance)


class ClinicalExtraction(BaseModel):
    """Output 3 — structured, grounded record of what the consultation contained."""

    session_id: str
    patient_information: dict[str, Any] = Field(default_factory=dict)
    chief_complaints: list[ChiefComplaint] = Field(default_factory=list)
    history_of_present_illness: GroundedText | None = None
    past_medical_history: list[GroundedText] = Field(default_factory=list)
    family_history: list[GroundedText] = Field(default_factory=list)
    allergies: list[Allergy] = Field(default_factory=list)
    vitals: dict[str, str] = Field(default_factory=dict)
    examination: list[ExaminationFinding] = Field(default_factory=list)
    investigations: list[GroundedText] = Field(default_factory=list)
    assessment: GroundedText | None = None
    diagnosis: list[GroundedText] = Field(default_factory=list)
    treatment_plan: list[GroundedText] = Field(default_factory=list)
    medications_discussed: list[MedicationMention] = Field(default_factory=list)
    follow_up: GroundedText | None = None
    doctor_notes: GroundedText | None = None

    # ── Views ────────────────────────────────────────────────────────────────
    def examination_nested(self) -> dict[str, dict[str, Any]]:
        """Build the nested {region: {finding: value}} view (matches the brief's example)."""
        nested: dict[str, dict[str, Any]] = {}
        for f in self.examination:
            nested.setdefault(f.region, {})[f.finding] = f.value
        return nested

    def to_data_map(self) -> dict[str, Any]:
        """Flat-ish data map used by the template renderer's ``schema_hint`` resolution."""
        return {
            "patient_information": self.patient_information,
            "chief_complaints": [c.model_dump(exclude={"provenance"}) for c in self.chief_complaints],
            "history_of_present_illness": self.history_of_present_illness.text
            if self.history_of_present_illness else None,
            "past_medical_history": [g.text for g in self.past_medical_history],
            "family_history": [g.text for g in self.family_history],
            "allergies": [a.model_dump(exclude={"provenance"}) for a in self.allergies],
            "vitals": self.vitals,
            "examination": self.examination_nested(),
            "investigations": [g.text for g in self.investigations],
            "assessment": self.assessment.text if self.assessment else None,
            "diagnosis": [g.text for g in self.diagnosis],
            "treatment_plan": [g.text for g in self.treatment_plan],
            "medications_discussed": [m.model_dump(exclude={"provenance"}) for m in self.medications_discussed],
            "follow_up": self.follow_up.text if self.follow_up else None,
            "doctor_notes": self.doctor_notes.text if self.doctor_notes else None,
        }
