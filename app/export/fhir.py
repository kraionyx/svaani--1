"""FHIR R4 export — interoperable clinical document for EHR ingestion.

Maps a FINALIZED session's grounded artifacts onto a FHIR R4 ``document`` Bundle:
  • Composition       — the consultation note (one section per note section).
  • Condition         — each diagnosis.
  • MedicationStatement — each discussed medication (``status: unknown``; these are
    documentation of what was *discussed*, never an authoritative prescription).
  • AllergyIntolerance — each allergy.
  • Observation       — each vital sign.
  • Patient           — a minimal subject the other resources reference.

Built as plain dicts (no FHIR SDK dependency) so the app stays importable and the
output is plain JSON. Faithful by construction: it only serializes the grounded
extraction, which already passed grounding + fact verification.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.schemas.session import ConsultationSession


def _ref(resource: dict[str, Any]) -> str:
    return f"{resource['resourceType']}/{resource['id']}"


def _entry(resource: dict[str, Any]) -> dict[str, Any]:
    return {"fullUrl": f"urn:uuid:{resource['id']}", "resource": resource}


def note_to_fhir_bundle(session: ConsultationSession) -> dict[str, Any]:
    now = (session.signed_at or datetime.now(timezone.utc)).isoformat()
    ext = session.extraction
    note = session.note

    patient = {
        "resourceType": "Patient", "id": str(uuid.uuid4()),
        "identifier": [{"system": "urn:svaani:patient", "value": session.patient_id or session.session_id}],
    }
    patient_ref = {"reference": _ref(patient)}
    entries: list[dict[str, Any]] = [_entry(patient)]
    section_refs: list[dict[str, Any]] = []

    def add(resource: dict[str, Any]) -> dict[str, Any]:
        entries.append(_entry(resource))
        return resource

    if ext is not None:
        for dx in ext.diagnosis:
            cond = add({
                "resourceType": "Condition", "id": str(uuid.uuid4()),
                "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
                "code": {"text": dx.text}, "subject": patient_ref,
            })
            section_refs.append({"reference": _ref(cond)})
        for med in ext.medications_discussed:
            dosage = " ".join(p for p in (med.dose, med.route, med.frequency, med.duration) if p)
            stmt = add({
                "resourceType": "MedicationStatement", "id": str(uuid.uuid4()),
                "status": "unknown",  # discussed, NOT an authoritative prescription
                "medicationCodeableConcept": {"text": med.name}, "subject": patient_ref,
                **({"dosage": [{"text": dosage}]} if dosage else {}),
                "note": [{"text": "Discussed in consultation — non-authoritative; not a prescription."}],
            })
            section_refs.append({"reference": _ref(stmt)})
        for alg in ext.allergies:
            ai = add({
                "resourceType": "AllergyIntolerance", "id": str(uuid.uuid4()),
                "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]},
                "code": {"text": alg.substance}, "patient": patient_ref,
                **({"reaction": [{"manifestation": [{"text": alg.reaction}]}]} if alg.reaction else {}),
            })
            section_refs.append({"reference": _ref(ai)})
        for name, value in (ext.vitals or {}).items():
            obs = add({
                "resourceType": "Observation", "id": str(uuid.uuid4()), "status": "final",
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
                "code": {"text": name}, "subject": patient_ref, "valueString": str(value),
            })
            section_refs.append({"reference": _ref(obs)})

    composition = {
        "resourceType": "Composition", "id": str(uuid.uuid4()),
        "status": "final" if session.is_exportable else "preliminary",
        "type": {"coding": [{"system": "http://loinc.org", "code": "11488-4", "display": "Consult note"}]},
        "subject": patient_ref, "date": now,
        "title": "Consultation note",
        "author": [{"display": session.signed_by_name or session.practitioner_id or "Svaani AI Medical Scribe"}],
        "section": (
            [{"title": s.label, "text": {"status": "generated",
              "div": f"<div xmlns=\"http://www.w3.org/1999/xhtml\">{(s.content_text or 'Not discussed.')}</div>"}}
             for s in sorted(note.sections, key=lambda x: x.order)] if note else []
        ) + ([{"title": "Clinical entries", "entry": section_refs}] if section_refs else []),
    }
    # Composition must be the FIRST entry of a document Bundle.
    entries.insert(0, _entry(composition))

    return {
        "resourceType": "Bundle", "type": "document",
        "identifier": {"system": "urn:svaani:session", "value": session.session_id},
        "timestamp": now, "entry": entries,
    }
