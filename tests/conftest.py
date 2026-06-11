"""Shared fixtures: the brief's ENT example as a transcript + grounded extraction."""
from __future__ import annotations

import pytest

from app.schemas.clinical import (
    ChiefComplaint,
    ClinicalExtraction,
    ExaminationFinding,
    Provenance,
)
from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment
from app.templates.registry import TemplateRegistry


@pytest.fixture
def registry() -> TemplateRegistry:
    reg = TemplateRegistry()
    reg.load_dir()  # loads docs/templates/*.json
    return reg


@pytest.fixture
def ent_transcript() -> RawTranscript:
    rows = [
        (SpeakerRole.PATIENT, "I have throat pain for two months."),
        (SpeakerRole.PATIENT, "Yes, mostly with solid foods."),
        (SpeakerRole.PATIENT, "Yes, frequent discharge."),
        (SpeakerRole.DOCTOR, "Granular posterior pharyngeal wall, grade 2 tonsillar hypertrophy, DNS left."),
    ]
    segs = [
        TranscriptSegment(id=f"seg-{i + 1:04d}", speaker=spk, text=text, confidence=0.9)
        for i, (spk, text) in enumerate(rows)
    ]
    return RawTranscript(session_id="ent-demo", segments=segs)


@pytest.fixture
def ent_extraction() -> ClinicalExtraction:
    """Matches the brief's 'Expected Extraction', with provenance into ent_transcript."""
    return ClinicalExtraction(
        session_id="ent-demo",
        chief_complaints=[
            ChiefComplaint(symptom="Throat Pain", duration="2 Months",
                           provenance=Provenance(span_ids=["seg-0001"])),
            ChiefComplaint(symptom="Difficulty Swallowing", type="Solids > Liquids",
                           provenance=Provenance(span_ids=["seg-0002"])),
            ChiefComplaint(symptom="Frequent Nasal Discharge",
                           provenance=Provenance(span_ids=["seg-0003"])),
        ],
        examination=[
            ExaminationFinding(region="throat", finding="granular_ppw", value=True,
                               provenance=Provenance(span_ids=["seg-0004"])),
            ExaminationFinding(region="throat", finding="tonsillar_hypertrophy", value="Grade 2",
                               provenance=Provenance(span_ids=["seg-0004"])),
            ExaminationFinding(region="nose", finding="dns", value="Left",
                               provenance=Provenance(span_ids=["seg-0004"])),
        ],
    )


def section_by_id(note, section_id: str):
    return next(s for s in note.sections if s.section_id == section_id)
