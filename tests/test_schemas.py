"""Schema invariants."""
from __future__ import annotations

import pytest

from app.schemas.clinical import ClinicalExtraction, ExaminationFinding, MedicationMention, Provenance
from app.schemas.session import ConsultationSession, IllegalTransition, ReviewState


def test_examination_nested_view_matches_brief():
    ext = ClinicalExtraction(
        session_id="s",
        examination=[
            ExaminationFinding(region="throat", finding="granular_ppw", value=True),
            ExaminationFinding(region="throat", finding="tonsillar_hypertrophy", value="Grade 2"),
            ExaminationFinding(region="nose", finding="dns", value="Left"),
        ],
    )
    assert ext.examination_nested() == {
        "throat": {"granular_ppw": True, "tonsillar_hypertrophy": "Grade 2"},
        "nose": {"dns": "Left"},
    }


def test_medication_mention_is_never_authoritative():
    # Even if a caller tries to force it true, the contract coerces to False.
    med = MedicationMention(name="Paracetamol", authoritative=True, provenance=Provenance(span_ids=["seg-0001"]))
    assert med.authoritative is False


def test_session_state_machine_requires_approval_before_finalize():
    s = ConsultationSession(session_id="s", template_id="soap")
    s.transition(ReviewState.PROCESSING)
    s.transition(ReviewState.DRAFT)
    s.transition(ReviewState.IN_REVIEW)
    # Cannot jump straight to FINALIZED without APPROVED.
    with pytest.raises(IllegalTransition):
        s.transition(ReviewState.FINALIZED)
    s.transition(ReviewState.APPROVED)
    s.transition(ReviewState.FINALIZED)
    assert s.is_exportable
