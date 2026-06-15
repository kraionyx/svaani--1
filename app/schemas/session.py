"""Consultation session + the doctor review/sign-off state machine.

Only a FINALIZED (doctor-signed) session is exportable / FHIR-pushable. Illegal
transitions raise — there is no path that finalizes without human approval.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.clinical import ClinicalExtraction
from app.schemas.intelligence import ConversationProfile
from app.schemas.note import ConsultationNote
from app.schemas.risk import RiskAssessment
from app.schemas.transcript import CleanTranscript, RawTranscript


class ReviewState(str, Enum):
    LISTENING = "listening"              # audio streaming in
    PROCESSING = "processing"            # STT + pipeline running
    DRAFT = "draft"                      # outputs ready, awaiting review
    IN_REVIEW = "in_review"              # doctor opened it
    EDITED = "edited"                    # doctor made changes
    APPROVED = "approved"                # doctor approved content
    FINALIZED = "finalized"              # signed & locked — exportable
    ESCALATION_REQUIRED = "escalation_required"  # STT/LLM failure or unresolved flags


#: Allowed forward/back transitions. Finalization is reachable only via APPROVED.
ALLOWED_TRANSITIONS: dict[ReviewState, set[ReviewState]] = {
    ReviewState.LISTENING: {ReviewState.PROCESSING, ReviewState.ESCALATION_REQUIRED},
    ReviewState.PROCESSING: {ReviewState.DRAFT, ReviewState.ESCALATION_REQUIRED},
    ReviewState.DRAFT: {ReviewState.IN_REVIEW, ReviewState.ESCALATION_REQUIRED},
    ReviewState.IN_REVIEW: {ReviewState.EDITED, ReviewState.APPROVED, ReviewState.ESCALATION_REQUIRED},
    ReviewState.EDITED: {ReviewState.IN_REVIEW, ReviewState.APPROVED, ReviewState.ESCALATION_REQUIRED},
    ReviewState.APPROVED: {ReviewState.FINALIZED, ReviewState.IN_REVIEW},
    ReviewState.FINALIZED: set(),
    ReviewState.ESCALATION_REQUIRED: {ReviewState.IN_REVIEW, ReviewState.PROCESSING},
}


class IllegalTransition(ValueError):
    pass


class ConsultationSession(BaseModel):
    session_id: str
    patient_id: str | None = None
    practitioner_id: str | None = None
    template_id: str | None = None
    template_version: int | None = None
    state: ReviewState = ReviewState.LISTENING
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Digital sign-off (captured at FINALIZE). ``signature_image`` is an optional
    # data-URL (drawn pad or uploaded image); the signing clinician's name is required.
    signed_by_name: str | None = None
    signature_image: str | None = None
    signed_at: datetime | None = None

    # Conversation intelligence (Goals 1-4). Who is in the room, complexity, confidence,
    # and the chosen real-time/batch mode. Not clinical content.
    conversation_profile: ConversationProfile | None = None
    inference_mode: str | None = None
    # Versioning (Goal 10) — the prompt/model that produced this consult, for rollback/audit.
    model_version: str | None = None
    prompt_version: str | None = None

    # Outputs (populated as the pipeline runs).
    raw_transcript: RawTranscript | None = None
    clean_transcript: CleanTranscript | None = None
    extraction: ClinicalExtraction | None = None
    note: ConsultationNote | None = None
    risk: RiskAssessment | None = None

    def transition(self, new_state: ReviewState) -> None:
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise IllegalTransition(f"{self.state.value} -> {new_state.value} is not allowed")
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)

    @property
    def is_exportable(self) -> bool:
        return self.state is ReviewState.FINALIZED
