"""FHIR R4 export maps grounded artifacts onto a valid document Bundle."""
from __future__ import annotations

from datetime import datetime, timezone

from app.export.fhir import note_to_fhir_bundle
from app.schemas.clinical import (
    Allergy, ClinicalExtraction, GroundedText, MedicationMention, Provenance,
)
from app.schemas.note import ConsultationNote, NoteSection
from app.schemas.session import ConsultationSession, ReviewState
from app.schemas.template import ComponentType


def _session() -> ConsultationSession:
    ext = ClinicalExtraction(
        session_id="s1",
        diagnosis=[GroundedText(text="Acute febrile illness", provenance=Provenance(span_ids=["seg-0016"]))],
        medications_discussed=[MedicationMention(name="Paracetamol", dose="650 mg", provenance=Provenance(span_ids=["seg-0008"]))],
        allergies=[Allergy(substance="Penicillin", reaction="rash", provenance=Provenance(span_ids=["seg-0009"]))],
        vitals={"Temperature": "102 F", "Pulse": "104/min"},
    )
    note = ConsultationNote(
        session_id="s1", template_id="soap", template_version=1,
        sections=[NoteSection(section_id="subjective", label="Subjective",
                              component=ComponentType.CHIEF_COMPLAINTS, order=1,
                              content_text="Fever for three days.")],
    )
    s = ConsultationSession(session_id="s1", template_id="soap", state=ReviewState.FINALIZED)
    s.extraction = ext
    s.note = note
    s.signed_by_name = "Dr. Rao"
    s.signed_at = datetime.now(timezone.utc)
    return s


def test_fhir_bundle_is_a_document_with_composition_first():
    bundle = note_to_fhir_bundle(_session())
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "document"
    # A FHIR document Bundle MUST have a Composition as its first entry.
    assert bundle["entry"][0]["resource"]["resourceType"] == "Composition"


def test_fhir_includes_grounded_clinical_resources():
    bundle = note_to_fhir_bundle(_session())
    kinds = [e["resource"]["resourceType"] for e in bundle["entry"]]
    assert "Condition" in kinds            # diagnosis
    assert "MedicationStatement" in kinds  # discussed medication
    assert "AllergyIntolerance" in kinds   # allergy
    assert "Observation" in kinds          # vitals

    med = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "MedicationStatement")
    # A discussed medication is never an authoritative prescription.
    assert med["status"] == "unknown"
    assert med["medicationCodeableConcept"]["text"] == "Paracetamol"
