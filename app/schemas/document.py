"""Hospital-branded document templates + rendered documents (prescription preview).

The AI does NOT author prescriptions. A ``DocumentTemplate`` is the hospital's own
printable design (HTML + CSS with ``{{placeholders}}``); the renderer fills it with
DOCTOR-CONFIRMED content only (the finalized note/extraction + hospital branding).
The doctor previews, edits, and explicitly approves/signs — this is a formatting and
sign-off layer, never clinical decision-making.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentStatus(str, Enum):
    DRAFT = "draft"
    PREVIEWED = "previewed"
    EDITED = "edited"
    APPROVED = "approved"
    SIGNED = "signed"
    VOIDED = "voided"


class DocumentTemplate(BaseModel):
    """A hospital's printable document design. Versioned + immutable per version."""

    id: str
    hospital_id: str | None = None
    doc_type: str = "prescription"           # prescription | referral | certificate | summary
    name: str
    version: int = 1
    html: str                                # design with {{placeholder}} tokens
    css: str = ""
    placeholders: list[str] = Field(default_factory=list)
    active: bool = True
    created_by: str | None = None
    created_at: datetime = Field(default_factory=_now)


class RenderedDocument(BaseModel):
    """A previewed/edited/approved instance of a document for one consultation."""

    id: str
    session_id: str
    document_template_id: str | None = None
    doc_type: str = "prescription"
    status: DocumentStatus = DocumentStatus.DRAFT
    rendered_html: str = ""                   # template-filled draft (doctor-confirmed content)
    edited_html: str | None = None            # doctor's edited version
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def final_html(self) -> str:
        return self.edited_html if self.edited_html is not None else self.rendered_html
