"""Export the five artifacts: raw / clean / note / extraction-JSON / full record.

PDF rendering lives in ``app.export.pdf``. Only FINALIZED sessions should be
exported — the caller (route) enforces that.
"""
from __future__ import annotations

from typing import Any

from app.schemas.session import ConsultationSession


def export_raw(session: ConsultationSession) -> str:
    return session.raw_transcript.full_text if session.raw_transcript else ""


def export_clean(session: ConsultationSession) -> str:
    return session.clean_transcript.full_text if session.clean_transcript else ""


def export_note_markdown(session: ConsultationSession) -> str:
    return session.note.to_markdown() if session.note else ""


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
        "raw_transcript": session.raw_transcript.model_dump(mode="json") if session.raw_transcript else None,
        "clean_transcript": session.clean_transcript.model_dump(mode="json") if session.clean_transcript else None,
        "extraction": session.extraction.model_dump(mode="json") if session.extraction else None,
        "note": session.note.model_dump(mode="json") if session.note else None,
        "risk": session.risk.model_dump(mode="json") if session.risk else None,
    }
