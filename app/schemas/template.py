"""Dynamic template definition — the JSON contract behind the drag-and-drop builder.

Doctors compose templates from a fixed component catalog. Each section can be
enabled/disabled, reordered, renamed, and (for CUSTOM) bound to a sub-path of the
clinical extraction via ``schema_hint``. Templates are versioned and immutable per
version so a finalized note can pin ``template_id@version`` for reproducibility.

Note: there is deliberately **no PRESCRIPTION component** — the AI does not author
prescriptions. Medications that were discussed surface (verbatim, non-authoritative)
under TREATMENT_PLAN / DOCTOR_NOTES if the template includes them.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ComponentType(str, Enum):
    PATIENT_INFORMATION = "PATIENT_INFORMATION"
    CHIEF_COMPLAINTS = "CHIEF_COMPLAINTS"
    HISTORY_OF_PRESENT_ILLNESS = "HISTORY_OF_PRESENT_ILLNESS"
    PAST_MEDICAL_HISTORY = "PAST_MEDICAL_HISTORY"
    FAMILY_HISTORY = "FAMILY_HISTORY"
    ALLERGIES = "ALLERGIES"
    VITALS = "VITALS"
    EXAMINATION = "EXAMINATION"
    INVESTIGATIONS = "INVESTIGATIONS"
    ASSESSMENT = "ASSESSMENT"
    DIAGNOSIS = "DIAGNOSIS"
    TREATMENT_PLAN = "TREATMENT_PLAN"
    FOLLOW_UP = "FOLLOW_UP"
    DOCTOR_NOTES = "DOCTOR_NOTES"
    CUSTOM = "CUSTOM"


#: Maps every component to the extraction key it reads by default.
#: CUSTOM has no default mapping — it must declare a ``schema_hint``.
COMPONENT_DEFAULT_SOURCE: dict[ComponentType, str] = {
    ComponentType.PATIENT_INFORMATION: "patient_information",
    ComponentType.CHIEF_COMPLAINTS: "chief_complaints",
    ComponentType.HISTORY_OF_PRESENT_ILLNESS: "history_of_present_illness",
    ComponentType.PAST_MEDICAL_HISTORY: "past_medical_history",
    ComponentType.FAMILY_HISTORY: "family_history",
    ComponentType.ALLERGIES: "allergies",
    ComponentType.VITALS: "vitals",
    ComponentType.EXAMINATION: "examination",
    ComponentType.INVESTIGATIONS: "investigations",
    ComponentType.ASSESSMENT: "assessment",
    ComponentType.DIAGNOSIS: "diagnosis",
    ComponentType.TREATMENT_PLAN: "treatment_plan",
    ComponentType.FOLLOW_UP: "follow_up",
    ComponentType.DOCTOR_NOTES: "doctor_notes",
}


class TemplateSection(BaseModel):
    id: str
    component: ComponentType
    label: str
    enabled: bool = True
    order: int = 0
    schema_hint: str | None = Field(
        default=None,
        description="Dotted path into the extraction data map, e.g. 'examination.nose'. "
        "Required for CUSTOM components.",
    )

    @model_validator(mode="after")
    def _custom_requires_hint(self) -> "TemplateSection":
        if self.component is ComponentType.CUSTOM and not self.schema_hint:
            raise ValueError(f"CUSTOM section '{self.id}' must declare a schema_hint")
        return self


class TemplateDefinition(BaseModel):
    template_id: str
    name: str
    version: int = Field(default=1, ge=1)
    hospital_id: str | None = None
    description: str | None = None
    sections: list[TemplateSection] = Field(default_factory=list)
    # When True, sections with no grounded content are dropped from the rendered note
    # entirely (a "dynamic" note that shows ONLY what was actually discussed — no empty
    # headings, no "Not discussed" placeholders). Default False so existing templates keep
    # rendering every enabled section (and stay editable section-by-section).
    omit_empty_sections: bool = False

    @model_validator(mode="after")
    def _unique_section_ids(self) -> "TemplateDefinition":
        ids = [s.id for s in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("Template section ids must be unique")
        return self

    def active_sections(self) -> list[TemplateSection]:
        """Enabled sections, in display order."""
        return sorted((s for s in self.sections if s.enabled), key=lambda s: s.order)

    @property
    def pinned_ref(self) -> str:
        return f"{self.template_id}@{self.version}"
