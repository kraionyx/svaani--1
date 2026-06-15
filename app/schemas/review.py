"""Feedback, admin-review, improvement-pipeline, and versioning schemas (Goals 7-10).

These power the doctor review prompt, the admin console, the human-gated prompt
improvement pipeline, and prompt/model version history. None of this is clinical
content; it is the operational/quality layer around the scribe.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InferenceMode(str, Enum):
    REALTIME = "realtime"
    BATCH = "batch"
    AUTO_REALTIME = "auto_realtime"   # auto mode resolved to realtime
    AUTO_BATCH = "auto_batch"         # auto mode escalated to batch


class ReviewRating(str, Enum):
    HELPFUL = "helpful"
    NEEDS_IMPROVEMENT = "needs_improvement"


class ErrorCategory(str, Enum):
    WRONG_PATIENT_IDENTIFIED = "wrong_patient_identified"
    WRONG_SPEAKER_ASSIGNMENT = "wrong_speaker_assignment"
    INCORRECT_SOAP_SUMMARY = "incorrect_soap_summary"
    MEDICATION_EXTRACTION_ERROR = "medication_extraction_error"
    TIMELINE_ERROR = "timeline_error"
    PROMPT_MISUNDERSTANDING = "prompt_misunderstanding"
    MISSING_DIAGNOSIS = "missing_diagnosis"
    HALLUCINATION = "hallucination"
    OTHER = "other"


class AdminStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class ImprovementStage(str, Enum):
    ISSUE_CLASSIFICATION = "issue_classification"
    PROMPT_EVALUATION = "prompt_evaluation"
    REGRESSION_TEST_GENERATION = "regression_test_generation"
    PROMPT_OPTIMIZATION = "prompt_optimization"
    OFFLINE_VALIDATION = "offline_validation"
    HUMAN_APPROVAL = "human_approval"
    DEPLOYED = "deployed"
    REJECTED = "rejected"


#: The fixed forward order of the improvement pipeline (Goal 9).
IMPROVEMENT_ORDER: list[ImprovementStage] = [
    ImprovementStage.ISSUE_CLASSIFICATION,
    ImprovementStage.PROMPT_EVALUATION,
    ImprovementStage.REGRESSION_TEST_GENERATION,
    ImprovementStage.PROMPT_OPTIMIZATION,
    ImprovementStage.OFFLINE_VALIDATION,
    ImprovementStage.HUMAN_APPROVAL,
    ImprovementStage.DEPLOYED,
]


class ConsultationReview(BaseModel):
    """Goal 7 — a doctor's end-of-consult verdict."""

    id: str
    session_id: str
    hospital_id: str | None = None
    reviewer_id: str | None = None
    rating: ReviewRating
    error_categories: list[ErrorCategory] = Field(default_factory=list)
    comment: str | None = None
    # Context snapshot for the admin console (so it needs no re-derivation).
    model_version: str | None = None
    prompt_version: str | None = None
    inference_mode: InferenceMode | None = None
    audio_confidence: float | None = None
    speaker_count: int | None = None
    created_at: datetime = Field(default_factory=_now)


class AdminReview(BaseModel):
    """Goal 8 — an item in the admin triage queue (auto-created for needs_improvement)."""

    id: str
    review_id: str
    session_id: str
    status: AdminStatus = AdminStatus.PENDING
    assigned_to: str | None = None
    admin_notes: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ImprovementItem(BaseModel):
    """Goal 9 — a staged, human-gated prompt-improvement candidate (offline only)."""

    id: str
    admin_review_id: str | None = None
    error_category: ErrorCategory | None = None
    stage: ImprovementStage = ImprovementStage.ISSUE_CLASSIFICATION
    prompt_name: str | None = None
    candidate_prompt: str | None = None
    regression_test_id: str | None = None
    eval_results: dict = Field(default_factory=dict)
    approved_by: str | None = None
    deployed_prompt_version_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PromptVersion(BaseModel):
    """Goal 10 — a versioned, immutable prompt. Only `active` is read by the pipeline."""

    id: str
    name: str                     # 'extract' | 'clean' | 'risk' | 'combined' | 'relationship'
    version: int
    content: str
    model_version: str | None = None
    inference_mode: InferenceMode | None = None
    active: bool = False
    created_by: str | None = None
    created_at: datetime = Field(default_factory=_now)


class ModelVersion(BaseModel):
    id: str
    provider: str                 # 'vertex' | 'sarvam'
    model_id: str                 # 'gemini-3.5-flash'
    label: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
