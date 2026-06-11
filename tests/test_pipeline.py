"""End-to-end pipeline smoke test.

Hermetic by construction: forces the mock STT + DisabledLLM so it never touches a
live provider, even when a developer has real keys in their .env.
"""
from __future__ import annotations

from app.llm.base import DisabledLLM
from app.pipeline.orchestrator import run_pipeline
from app.schemas.note import ConsultationNote
from app.schemas.risk import RiskAssessment
from app.stt.sarvam import MockSarvamSTT
from app.templates.registry import get_registry


def test_run_pipeline_produces_note_and_risk():
    raw = MockSarvamSTT().transcribe(b"", session_id="smoke")  # canned ENT consult
    template = get_registry().get("soap")

    result = run_pipeline(raw, template, llm=DisabledLLM())

    assert isinstance(result.note, ConsultationNote)
    assert isinstance(result.risk, RiskAssessment)
    assert result.note.template_id == "soap"
    # With no LLM the extraction is empty, so nothing can be ungrounded.
    assert result.grounding.all_grounded
    # Note renders with the template's sections even when empty.
    assert {s.section_id for s in result.note.sections} == {"subjective", "objective", "assessment", "plan"}
