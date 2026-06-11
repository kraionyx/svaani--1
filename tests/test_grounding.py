"""Grounding = the core safety mechanism: only what was said survives."""
from __future__ import annotations

from app.schemas.clinical import ChiefComplaint, ClinicalExtraction, Provenance
from app.validation.grounding import ground_extraction


def test_ungrounded_item_is_dropped():
    valid_spans = {"seg-0001", "seg-0002"}
    ext = ClinicalExtraction(
        session_id="s",
        chief_complaints=[
            ChiefComplaint(symptom="Throat Pain", provenance=Provenance(span_ids=["seg-0001"])),
            # Not said anywhere in the transcript — model inferred / hallucinated it.
            ChiefComplaint(symptom="Chest Pain", provenance=Provenance(span_ids=["seg-9999"])),
            # No provenance at all — also ungrounded.
            ChiefComplaint(symptom="Headache"),
        ],
    )
    cleaned, report = ground_extraction(ext, valid_spans, drop=True)

    symptoms = {c.symptom for c in cleaned.chief_complaints}
    assert symptoms == {"Throat Pain"}
    assert report.kept == 1
    assert len(report.dropped) == 2
    assert not report.all_grounded


def test_flag_mode_keeps_but_marks_ungrounded():
    valid_spans = {"seg-0001"}
    ext = ClinicalExtraction(
        session_id="s",
        chief_complaints=[ChiefComplaint(symptom="Chest Pain", provenance=Provenance(span_ids=["seg-9999"]))],
    )
    cleaned, report = ground_extraction(ext, valid_spans, drop=False)

    assert len(cleaned.chief_complaints) == 1
    assert cleaned.chief_complaints[0].provenance.grounded is False
    assert report.flagged and report.kept == 0
