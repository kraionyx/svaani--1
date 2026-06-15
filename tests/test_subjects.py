"""Goal 1 — relationship resolution: the patient is who the consult is ABOUT."""
from __future__ import annotations

from app.pipeline.subjects import resolve_relationships
from app.schemas.intelligence import ConversationKind, SpeakerRelationship
from app.schemas.transcript import RawTranscript, SpeakerRole, TranscriptSegment


def _t(rows: list[tuple[SpeakerRole, str]]) -> RawTranscript:
    return RawTranscript(
        session_id="s",
        segments=[TranscriptSegment(id=f"seg-{i+1:04d}", speaker=spk, text=txt, confidence=0.95)
                  for i, (spk, txt) in enumerate(rows)],
    )


def test_mother_speaking_for_son_resolves_son_as_patient():
    """The brief's failing case: Patient must be the son, not the speaking mother."""
    raw = _t([
        (SpeakerRole.DOCTOR, "What happened?"),
        (SpeakerRole.PATIENT, "Doctor, my son has had fever for three days."),
        (SpeakerRole.DOCTOR, "Is he vomiting?"),
        (SpeakerRole.PATIENT, "Yes, twice."),
    ])
    p = resolve_relationships(raw)  # rule-based (no LLM)
    assert p.referenced_patient == "son"
    assert p.kind is ConversationKind.DOCTOR_PARENT
    caregiver = next(s for s in p.speakers if s.role is SpeakerRole.CAREGIVER)
    assert caregiver.relationship is SpeakerRelationship.PARENT
    assert caregiver.subject_patient == "son"


def test_self_describing_patient_is_self():
    raw = _t([
        (SpeakerRole.DOCTOR, "What brings you in?"),
        (SpeakerRole.PATIENT, "I have throat pain for two months."),
    ])
    p = resolve_relationships(raw)
    assert p.referenced_patient == "patient"
    assert p.kind is ConversationKind.DOCTOR_PATIENT
    patient = next(s for s in p.speakers if s.role is SpeakerRole.PATIENT)
    assert patient.relationship is SpeakerRelationship.SELF


def test_speaking_for_father():
    raw = _t([
        (SpeakerRole.DOCTOR, "Tell me about the problem."),
        (SpeakerRole.PATIENT, "I am speaking for my father, he has chest pain."),
    ])
    p = resolve_relationships(raw)
    assert p.referenced_patient == "father"


def test_translator_detected():
    raw = _t([
        (SpeakerRole.DOCTOR, "Ask her what happened."),
        (SpeakerRole.PATIENT, "I am the translator, she says she has a headache."),
    ])
    p = resolve_relationships(raw)
    assert p.kind is ConversationKind.DOCTOR_TRANSLATOR
    assert any(s.role is SpeakerRole.TRANSLATOR for s in p.speakers)


def test_single_speaker():
    raw = _t([(SpeakerRole.DOCTOR, "Patient presents with cough.")])
    p = resolve_relationships(raw)
    assert p.kind is ConversationKind.SINGLE_SPEAKER
