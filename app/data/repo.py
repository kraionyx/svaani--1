"""In-memory operational repository.

Backs the feedback / admin / improvement / versioning / document / edit-history APIs.
Thread-safe enough for the dev server (FastAPI runs sync handlers in a threadpool).
A Supabase-backed repository with the same method surface drops in later; callers go
through ``get_repo()`` so the swap is invisible.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from app.schemas.document import DocumentStatus, DocumentTemplate, RenderedDocument
from app.schemas.review import (
    IMPROVEMENT_ORDER,
    AdminReview,
    AdminStatus,
    ConsultationReview,
    ErrorCategory,
    ImprovementItem,
    ImprovementStage,
    ModelVersion,
    PromptVersion,
    ReviewRating,
)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


#: Maps a doctor-reported error category to the prompt most likely responsible — used to
#: seed an improvement item when an admin approves a review (Goal 9).
_CATEGORY_TO_PROMPT: dict[ErrorCategory, str] = {
    ErrorCategory.WRONG_PATIENT_IDENTIFIED: "relationship",
    ErrorCategory.WRONG_SPEAKER_ASSIGNMENT: "relationship",
    ErrorCategory.INCORRECT_SOAP_SUMMARY: "extract",
    ErrorCategory.MEDICATION_EXTRACTION_ERROR: "extract",
    ErrorCategory.TIMELINE_ERROR: "extract",
    ErrorCategory.PROMPT_MISUNDERSTANDING: "combined",
    ErrorCategory.MISSING_DIAGNOSIS: "extract",
    ErrorCategory.HALLUCINATION: "extract",
    ErrorCategory.OTHER: "combined",
}


class Repository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reviews: dict[str, ConsultationReview] = {}
        self.admin_reviews: dict[str, AdminReview] = {}
        self.improvements: dict[str, ImprovementItem] = {}
        self.prompts: dict[str, PromptVersion] = {}
        self.models: dict[str, ModelVersion] = {}
        self.doc_templates: dict[str, DocumentTemplate] = {}
        self.rendered_docs: dict[str, RenderedDocument] = {}
        self.edits: dict[str, list] = {}        # session_id -> [ConsultationEdit-like dict]
        self.flags: dict[str, dict] = {}        # key -> {enabled, value}
        self.ab_metrics: list[dict] = []        # prompt A/B outcome rows (Goal 13)
        self.stage_latencies: list[dict] = []    # per-stage timing rows (Goals 4/12/13)

    def close(self) -> None:
        """Release backing resources. No-op for the in-memory repo; the persistent
        backend overrides to close its connection pool at app shutdown."""

    # ── Goal 7: doctor reviews (+ auto-enqueue to admin) ───────────────────────
    def add_review(self, review: ConsultationReview) -> ConsultationReview:
        with self._lock:
            self.reviews[review.id] = review
            if review.rating is ReviewRating.NEEDS_IMPROVEMENT:
                ar = AdminReview(id=_id("adm"), review_id=review.id, session_id=review.session_id)
                self.admin_reviews[ar.id] = ar
            return review

    def list_reviews(self, session_id: str | None = None) -> list[ConsultationReview]:
        with self._lock:
            items = list(self.reviews.values())
        if session_id:
            items = [r for r in items if r.session_id == session_id]
        return sorted(items, key=lambda r: r.created_at, reverse=True)

    # ── Goal 8: admin console ──────────────────────────────────────────────────
    def list_admin_reviews(
        self, status: AdminStatus | None = None, error_category: ErrorCategory | None = None
    ) -> list[dict]:
        with self._lock:
            out: list[dict] = []
            for ar in self.admin_reviews.values():
                if status and ar.status is not status:
                    continue
                review = self.reviews.get(ar.review_id)
                if error_category and (not review or error_category not in review.error_categories):
                    continue
                out.append({"admin_review": ar.model_dump(mode="json"),
                            "review": review.model_dump(mode="json") if review else None})
        return sorted(out, key=lambda x: x["admin_review"]["created_at"], reverse=True)

    def update_admin_review(
        self, admin_id: str, *, status: AdminStatus | None = None,
        assigned_to: str | None = None, notes: str | None = None,
    ) -> AdminReview:
        with self._lock:
            ar = self.admin_reviews[admin_id]
            if status is not None:
                ar.status = status
                if status in (AdminStatus.RESOLVED, AdminStatus.REJECTED):
                    ar.resolved_at = datetime.now(timezone.utc)
            if assigned_to is not None:
                ar.assigned_to = assigned_to
            if notes is not None:
                ar.admin_notes = notes
            ar.updated_at = datetime.now(timezone.utc)
            # Goal 9: approving an admin review seeds the improvement pipeline (offline).
            if status is AdminStatus.APPROVED:
                self._seed_improvement(ar)
            return ar

    def _seed_improvement(self, ar: AdminReview) -> None:
        review = self.reviews.get(ar.review_id)
        cat = review.error_categories[0] if review and review.error_categories else ErrorCategory.OTHER
        item = ImprovementItem(
            id=_id("imp"), admin_review_id=ar.id, error_category=cat,
            prompt_name=_CATEGORY_TO_PROMPT.get(cat, "combined"),
        )
        self.improvements[item.id] = item

    # ── Goal 9: improvement pipeline ───────────────────────────────────────────
    def list_improvements(self, stage: ImprovementStage | None = None) -> list[ImprovementItem]:
        with self._lock:
            items = list(self.improvements.values())
        if stage:
            items = [i for i in items if i.stage is stage]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def advance_improvement(
        self, item_id: str, *, candidate_prompt: str | None = None,
        eval_results: dict | None = None, approved_by: str | None = None, reject: bool = False,
    ) -> ImprovementItem:
        with self._lock:
            item = self.improvements[item_id]
            if reject:
                item.stage = ImprovementStage.REJECTED
            else:
                idx = IMPROVEMENT_ORDER.index(item.stage) if item.stage in IMPROVEMENT_ORDER else -1
                if idx + 1 < len(IMPROVEMENT_ORDER):
                    item.stage = IMPROVEMENT_ORDER[idx + 1]
            if candidate_prompt is not None:
                item.candidate_prompt = candidate_prompt
            if eval_results is not None:
                item.eval_results = eval_results
            if approved_by is not None:
                item.approved_by = approved_by
            item.updated_at = datetime.now(timezone.utc)
            return item

    def set_improvement_eval(
        self, item_id: str, eval_results: dict, regression_test_id: str | None = None
    ) -> ImprovementItem:
        """Record an offline eval-harness result on an improvement item (Goal 9)."""
        with self._lock:
            item = self.improvements[item_id]
            item.eval_results = eval_results
            if regression_test_id:
                item.regression_test_id = regression_test_id
            item.updated_at = datetime.now(timezone.utc)
            return item

    # ── Goal 13: prompt A/B metrics ─────────────────────────────────────────────
    def record_ab_metric(self, metric: dict) -> dict:
        with self._lock:
            self.ab_metrics.append(metric)
            return metric

    def list_ab_metrics(self, prompt_name: str | None = None) -> list[dict]:
        with self._lock:
            items = list(self.ab_metrics)
        if prompt_name:
            items = [m for m in items if m.get("prompt_name") == prompt_name]
        return items

    # ── Goals 4/12/13: per-stage latency telemetry ──────────────────────────────
    def record_stage_latency(self, row: dict) -> dict:
        with self._lock:
            self.stage_latencies.append(row)
            return row

    def list_stage_latencies(self, stage: str | None = None) -> list[dict]:
        with self._lock:
            items = list(self.stage_latencies)
        if stage:
            items = [r for r in items if r.get("stage") == stage]
        return items

    # ── Goal 10: prompt/model versions ─────────────────────────────────────────
    def add_prompt_version(self, pv: PromptVersion) -> PromptVersion:
        with self._lock:
            if pv.active:  # only one active per name
                for other in self.prompts.values():
                    if other.name == pv.name:
                        other.active = False
            self.prompts[pv.id] = pv
            return pv

    def activate_prompt(self, prompt_id: str) -> PromptVersion:
        with self._lock:
            pv = self.prompts[prompt_id]
            for other in self.prompts.values():
                if other.name == pv.name:
                    other.active = False
            pv.active = True
            return pv

    def list_prompts(self, name: str | None = None) -> list[PromptVersion]:
        with self._lock:
            items = list(self.prompts.values())
        if name:
            items = [p for p in items if p.name == name]
        return sorted(items, key=lambda p: (p.name, p.version))

    def active_prompt(self, name: str) -> PromptVersion | None:
        with self._lock:
            actives = [p for p in self.prompts.values() if p.name == name and p.active]
        return actives[0] if actives else None

    def add_model_version(self, mv: ModelVersion) -> ModelVersion:
        with self._lock:
            self.models[mv.id] = mv
            return mv

    def list_models(self) -> list[ModelVersion]:
        with self._lock:
            return list(self.models.values())

    # ── Prescription preview: document templates + rendered docs ───────────────
    def add_document_template(self, dt: DocumentTemplate) -> DocumentTemplate:
        with self._lock:
            self.doc_templates[dt.id] = dt
            return dt

    def get_document_template(self, template_id: str) -> DocumentTemplate | None:
        with self._lock:
            return self.doc_templates.get(template_id)

    def list_document_templates(
        self, hospital_id: str | None = None, doc_type: str | None = None
    ) -> list[DocumentTemplate]:
        with self._lock:
            items = list(self.doc_templates.values())
        if hospital_id is not None:
            items = [d for d in items if d.hospital_id == hospital_id]
        if doc_type:
            items = [d for d in items if d.doc_type == doc_type]
        return items

    def default_document_template(self, doc_type: str = "prescription") -> DocumentTemplate | None:
        with self._lock:
            for d in self.doc_templates.values():
                if d.doc_type == doc_type and d.active:
                    return d
        return None

    def save_rendered_document(self, doc: RenderedDocument) -> RenderedDocument:
        with self._lock:
            doc.updated_at = datetime.now(timezone.utc)
            self.rendered_docs[doc.id] = doc
            return doc

    def get_rendered_document(self, doc_id: str) -> RenderedDocument | None:
        with self._lock:
            return self.rendered_docs.get(doc_id)

    def list_rendered_documents(self, session_id: str) -> list[RenderedDocument]:
        with self._lock:
            return [d for d in self.rendered_docs.values() if d.session_id == session_id]

    # ── Goal 11: AI edit history (undo/redo) ───────────────────────────────────
    def add_edit(self, session_id: str, edit: dict) -> dict:
        with self._lock:
            seq = len(self.edits.get(session_id, [])) + 1
            edit = {"undone": False, **edit, "seq": seq}
            self.edits.setdefault(session_id, []).append(edit)
            return edit

    def list_edits(self, session_id: str) -> list[dict]:
        with self._lock:
            return list(self.edits.get(session_id, []))

    def set_edit_undone(self, session_id: str, seq: int, undone: bool) -> dict:
        """Mark an edit undone/redone (Goal 11 undo/redo). Returns the updated edit."""
        with self._lock:
            for e in self.edits.get(session_id, []):
                if e.get("seq") == seq:
                    e["undone"] = undone
                    return e
            raise KeyError(seq)

    def drop_undone_edits(self, session_id: str) -> list[int]:
        """Discard the redo branch (called when a NEW edit is applied). Returns dropped seqs."""
        with self._lock:
            kept, dropped = [], []
            for e in self.edits.get(session_id, []):
                (dropped if e.get("undone") else kept).append(e)
            self.edits[session_id] = kept
            return [e["seq"] for e in dropped]

    # ── Goal 13: feature flags ─────────────────────────────────────────────────
    def set_flag(self, key: str, enabled: bool, value: dict | None = None) -> dict:
        with self._lock:
            self.flags[key] = {"enabled": enabled, "value": value or {}}
            return {"key": key, **self.flags[key]}

    def list_flags(self) -> list[dict]:
        with self._lock:
            return [{"key": k, **v} for k, v in self.flags.items()]


_repo: Repository | None = None


def get_repo() -> Repository:
    """Return the process-wide operational repository for the configured backend.

    ``memory`` (default) keeps everything in RAM; ``sqlite`` / ``supabase`` return a
    write-through PersistentRepository that survives restarts (same logic, durable store).
    """
    global _repo
    if _repo is None:
        _repo = _build_repo()
    return _repo


def _build_repo() -> Repository:
    from app.config import get_settings

    backend = getattr(get_settings(), "store_backend", "memory")
    if backend in ("sqlite", "supabase"):
        try:
            from app.data.repo_sql import (
                build_persistent_repository,
                make_postgres_store,
                make_sqlite_store,
            )

            settings = get_settings()
            store = (make_sqlite_store(settings) if backend == "sqlite"
                     else make_postgres_store(settings))
            return build_persistent_repository(store, settings)
        except Exception:  # noqa: BLE001 — never crash the app over operational persistence
            import logging

            logging.getLogger("svaani.repo").warning(
                "durable repo unavailable for backend=%s; falling back to in-memory", backend,
                exc_info=True,
            )
    r = Repository()
    _seed(r)
    return r


def reset_repo() -> None:
    """Drop the cached repository (tests / backend switch)."""
    global _repo
    _repo = None


def _seed(repo: Repository) -> None:
    """Seed v1 prompts (from the live prompt strings), the current model, and a default
    hospital prescription template so the prescription preview works out of the box."""
    from app.config import get_settings
    from app.pipeline.prompts import (
        CLEAN_INSTRUCTION,
        EXTRACT_INSTRUCTION,
        RELATIONSHIP_INSTRUCTION,
        RISK_INSTRUCTION,
    )
    from app.templates.document_renderer import DEFAULT_PRESCRIPTION_TEMPLATE

    for name, content in (
        ("clean", CLEAN_INSTRUCTION), ("extract", EXTRACT_INSTRUCTION),
        ("risk", RISK_INSTRUCTION), ("relationship", RELATIONSHIP_INSTRUCTION),
    ):
        repo.add_prompt_version(PromptVersion(id=_id("pv"), name=name, version=1, content=content, active=True))

    model_id = get_settings().gemini_model
    repo.add_model_version(ModelVersion(id=_id("mv"), provider="vertex", model_id=model_id, label="seed", active=True))

    repo.add_document_template(DEFAULT_PRESCRIPTION_TEMPLATE())
