"""Grounding validation — the core safety mechanism: "only what was said".

Every extracted item must cite transcript span(s) that actually exist. Items whose
provenance is empty or references unknown spans are treated as ungrounded (the model
inferred or hallucinated them) and are either **dropped** or **flagged** depending on
``settings.drop_ungrounded_fields``. This is what keeps the note faithful to the
conversation — the AI may reorganize what was said, never add to it.
"""
from __future__ import annotations

from typing import Callable

from pydantic import BaseModel

from app.schemas.clinical import ClinicalExtraction, Provenance


class GroundingReport(BaseModel):
    kept: int = 0
    dropped: list[str] = []
    flagged: list[str] = []

    @property
    def all_grounded(self) -> bool:
        return not self.dropped and not self.flagged


def _grounded(prov: Provenance, valid: set[str]) -> bool:
    return bool(prov.span_ids) and all(s in valid for s in prov.span_ids)


def ground_extraction(
    extraction: ClinicalExtraction,
    valid_span_ids: set[str],
    *,
    drop: bool = True,
) -> tuple[ClinicalExtraction, GroundingReport]:
    report = GroundingReport()

    def filter_items(items: list, describe: Callable[[object], str]) -> list:
        kept: list = []
        for it in items:
            if _grounded(it.provenance, valid_span_ids):
                report.kept += 1
                kept.append(it)
                continue
            it.provenance.grounded = False
            label = describe(it)
            if drop:
                report.dropped.append(label)
            else:
                report.flagged.append(label)
                kept.append(it)
        return kept

    extraction.chief_complaints = filter_items(
        extraction.chief_complaints, lambda x: f"chief_complaint:{x.symptom}"
    )
    extraction.allergies = filter_items(extraction.allergies, lambda x: f"allergy:{x.substance}")
    extraction.examination = filter_items(
        extraction.examination, lambda x: f"examination:{x.region}.{x.finding}"
    )
    extraction.medications_discussed = filter_items(
        extraction.medications_discussed, lambda x: f"medication:{x.name}"
    )
    extraction.diagnosis = filter_items(extraction.diagnosis, lambda x: f"diagnosis:{x.text[:40]}")
    extraction.treatment_plan = filter_items(
        extraction.treatment_plan, lambda x: f"treatment_plan:{x.text[:40]}"
    )
    extraction.investigations = filter_items(
        extraction.investigations, lambda x: f"investigation:{x.text[:40]}"
    )
    extraction.past_medical_history = filter_items(
        extraction.past_medical_history, lambda x: f"pmh:{x.text[:40]}"
    )
    extraction.family_history = filter_items(
        extraction.family_history, lambda x: f"family_history:{x.text[:40]}"
    )

    # Scalar grounded-text fields.
    for attr in ("history_of_present_illness", "assessment", "follow_up", "doctor_notes"):
        val = getattr(extraction, attr)
        if val is None:
            continue
        if _grounded(val.provenance, valid_span_ids):
            report.kept += 1
        else:
            val.provenance.grounded = False
            if drop:
                setattr(extraction, attr, None)
                report.dropped.append(attr)
            else:
                report.flagged.append(attr)

    return extraction, report
