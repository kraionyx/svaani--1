"""Export the five artifacts: raw / clean / note / extraction-JSON / full record.

PDF rendering lives in ``app.export.pdf``. Only FINALIZED sessions should be
exported — the caller (route) enforces that.
"""
from __future__ import annotations

from typing import Any

from app.export.fhir import note_to_fhir_bundle
from app.schemas.session import ConsultationSession


def export_fhir(session: ConsultationSession) -> dict[str, Any]:
    """FHIR R4 document Bundle for EHR interoperability."""
    return note_to_fhir_bundle(session)


def export_raw(session: ConsultationSession) -> str:
    return session.raw_transcript.full_text if session.raw_transcript else ""


def export_clean(session: ConsultationSession) -> str:
    return session.clean_transcript.full_text if session.clean_transcript else ""


def export_note_markdown(session: ConsultationSession) -> str:
    if not session.note:
        return ""
    md = session.note.to_markdown()
    if session.signed_by_name:
        signed = session.signed_at.strftime("%Y-%m-%d %H:%M UTC") if session.signed_at else ""
        md += f"\n---\n\n**Electronically signed by:** {session.signed_by_name}"
        md += f"  \n_{signed}_\n" if signed else "\n"
    return md


def export_extraction_json(session: ConsultationSession) -> dict[str, Any]:
    return session.extraction.model_dump(mode="json") if session.extraction else {}


def export_record(session: ConsultationSession) -> dict[str, Any]:
    """The complete JSON record — all outputs + provenance + risk + state."""
    return {
        "session_id": session.session_id,
        "patient_id": session.patient_id,
        "practitioner_id": session.practitioner_id,
        "template": {"id": session.template_id, "version": session.template_version},
        "state": session.state.value,
        "signature": {
            "signed_by_name": session.signed_by_name,
            "signed_at": session.signed_at.isoformat() if session.signed_at else None,
            "signature_image": session.signature_image,
        } if session.signed_by_name else None,
        "raw_transcript": session.raw_transcript.model_dump(mode="json") if session.raw_transcript else None,
        "clean_transcript": session.clean_transcript.model_dump(mode="json") if session.clean_transcript else None,
        "extraction": session.extraction.model_dump(mode="json") if session.extraction else None,
        "note": session.note.model_dump(mode="json") if session.note else None,
        "risk": session.risk.model_dump(mode="json") if session.risk else None,
    }
