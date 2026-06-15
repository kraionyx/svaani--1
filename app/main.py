"""FastAPI application — REST routes + the consultation WebSocket.

Auth in this scaffold is header-driven (``X-User-Id`` / ``X-Role``); replace the
``get_principal`` dependency with verified OIDC/JWT (Keycloak) in production. Every
PHI-touching action is permission-checked and audited.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.audio.ws import consultation_ws
from app.config import get_settings
from app.data.repo import get_repo
from app.export import exporter
from app.export.pdf import note_to_pdf
from app.observability import setup_observability
from app.llm.base import get_llm
from app.pipeline.ai_edit import propose_note_edit
from app.pipeline.coding import suggest_icd10
from app.pipeline.inference_mode import decide_mode
from app.pipeline.orchestrator import rebuild_from_extraction, run_pipeline
from app.pipeline.risk import aggregate_score
from app.security.audit import AuditEvent, get_audit_log
from app.security.auth import AuthError, principal_from
from app.security.rbac import AccessDenied, Permission, Principal, Role, require_permission
from app.schemas.clinical import ClinicalExtraction
from app.schemas.document import DocumentStatus, DocumentTemplate, RenderedDocument
from app.schemas.intelligence import SpeakerRelationship
from app.schemas.review import (
    AdminStatus,
    ConsultationReview,
    ErrorCategory,
    ImprovementStage,
    InferenceMode,
    PromptVersion,
    ReviewRating,
)
from app.schemas.risk import RiskAssessment, RiskMarker
from app.schemas.session import ConsultationSession, IllegalTransition, ReviewState
from app.schemas.template import TemplateDefinition
from app.schemas.transcript import RawTranscript, SpeakerRole
from app.stt.sarvam import MockSarvamSTT, get_stt
from app.store import get_store
from app.templates.document_renderer import render_for_session
from app.templates.registry import get_registry
from pydantic import BaseModel

# The sarvamai streaming SDK calls pydantic v2 models' deprecated `.dict()` internally
# (we never do). Silence that one third-party deprecation so live server logs stay clean.
warnings.filterwarnings("ignore", message=r"The `dict` method is deprecated", category=DeprecationWarning)

app = FastAPI(title="Svaani AI Medical Scribe", version="0.1.0")

# The frontend is a standalone static app served on its own port (default :5173),
# so cross-origin XHR/fetch and the custom auth headers must be allowed. Origins are
# configurable via SCRIBE_CORS_ALLOW_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger("svaani.audio")

# Observability: request-id propagation, access logs, and Prometheus /metrics.
setup_observability(app, get_settings())

# Minimum uploaded-audio size; anything smaller is effectively a silent/empty
# recording (a bare 16k mono WAV header is ~44 bytes).
_MIN_AUDIO_BYTES = 1024


def _has_speech(raw: RawTranscript) -> bool:
    """True if the transcript carries any non-empty utterance text."""
    return any((seg.text or "").strip() for seg in raw.segments)

# ── Dashboard ─────────────────────────────────────────────────────────────────
# The canonical frontend now lives in project_root/web and is meant to run on its
# own port (e.g. `python -m http.server 5173 -d web`). We also mount it here so the
# bundled same-origin UI at /ui keeps working without the second process.
_WEB_DIR = Path(__file__).resolve().parents[1] / "web"
# The new Vite/React streaming SPA (built to web-app/dist). Served at /app; becomes the
# default in the Phase 6 cutover. The legacy static UI stays at /ui until then.
_WEBAPP_DIR = Path(__file__).resolve().parents[1] / "web-app" / "dist"
# Where the registry loads seed templates from (project_root/docs/templates).
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "docs" / "templates"
if _WEB_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")
if _WEBAPP_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(_WEBAPP_DIR), html=True), name="app")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # Prefer the new streaming SPA when it has been built; else the legacy UI.
    return RedirectResponse("/app/" if _WEBAPP_DIR.exists() else "/ui/")


# ── Auth (scaffold) ──────────────────────────────────────────────────────────
def get_principal(
    authorization: str | None = Header(default=None),
    x_user_id: str = Header(default="dev-doctor"),
    x_role: str = Header(default="doctor"),
) -> Principal:
    try:
        return principal_from(
            get_settings(), authorization=authorization, x_user_id=x_user_id, x_role=x_role
        )
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"unknown role '{x_role}'")


def _check(principal: Principal, perm: Permission) -> None:
    try:
        require_permission(principal, perm)
    except AccessDenied as e:
        raise HTTPException(status_code=403, detail=str(e))


# ── Request bodies ───────────────────────────────────────────────────────────
class CreateSessionRequest(BaseModel):
    template_id: str = "soap"
    patient_id: str | None = None
    practitioner_id: str | None = None


class StateRequest(BaseModel):
    state: ReviewState
    # Sign-off, supplied only when transitioning to FINALIZED. A signing clinician
    # name is required; the image (drawn pad or upload) is an optional data-URL.
    signed_by_name: str | None = None
    signature_image: str | None = None


class NoteSectionEdit(BaseModel):
    section_id: str
    content_text: str


class NoteEditRequest(BaseModel):
    sections: list[NoteSectionEdit]


class ExtractionEditRequest(BaseModel):
    extraction: ClinicalExtraction


class RiskEditRequest(BaseModel):
    markers: list[RiskMarker]


def _advance_to_edited(session: ConsultationSession) -> None:
    """Reflect a human change in the review state: draft → in_review → edited."""
    try:
        if session.state is ReviewState.DRAFT:
            session.transition(ReviewState.IN_REVIEW)
        if session.state is ReviewState.IN_REVIEW:
            session.transition(ReviewState.EDITED)
    except IllegalTransition:
        pass  # already past the editable phase (e.g. approved) — content still saved


# ── Health & templates ───────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "app": s.app_name,
        "sarvam": "live" if s.use_sarvam else "mock",
        "vertex": "live" if s.use_vertex else "disabled",
        "debug_vertex_key_len": len(s.vertex_api_key),
        "debug_vertex_project": s.vertex_project,
        "debug_store": s.store_backend,
    }


@app.get("/templates")
def list_templates() -> list[dict]:
    return [
        {"template_id": t.template_id, "name": t.name, "version": t.version, "hospital_id": t.hospital_id}
        for t in get_registry().list_templates()
    ]


@app.get("/templates/components")
def template_components() -> list[dict]:
    return get_registry().component_catalog()


@app.get("/templates/{template_id}")
def get_template(template_id: str) -> dict:
    try:
        return get_registry().get(template_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown template '{template_id}'")


@app.post("/templates")
def create_template(template: TemplateDefinition, principal: Principal = Depends(get_principal)) -> dict:
    """Persist a template authored in the drag-and-drop builder.

    Validation (unique section ids, CUSTOM requires schema_hint) is enforced by the
    ``TemplateDefinition`` schema. If the ``template_id`` already exists we bump to a
    new immutable version rather than mutating the prior one.
    """
    _check(principal, Permission.MANAGE_TEMPLATES)
    registry = get_registry()
    try:
        existing = registry.get(template.template_id)
        template = template.model_copy(update={"version": existing.version + 1})
    except KeyError:
        pass  # brand-new template_id keeps its provided version (defaults to 1)

    registry.register(template)

    # Persist as pretty JSON alongside the seed templates.
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = _TEMPLATES_DIR / f"{template.template_id}.json"
    path.write_text(json.dumps(template.model_dump(mode="json"), indent=2), encoding="utf-8")

    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="create_template", resource="template",
        detail=template.pinned_ref,
    ))
    return {"template_id": template.template_id, "version": template.version}


# ── Sessions ─────────────────────────────────────────────────────────────────
@app.post("/sessions")
def create_session(req: CreateSessionRequest, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    try:
        get_registry().get(req.template_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown template '{req.template_id}'")
    sid = f"sess-{uuid.uuid4().hex[:12]}"
    session = ConsultationSession(
        session_id=sid, template_id=req.template_id,
        patient_id=req.patient_id, practitioner_id=req.practitioner_id or principal.id,
    )
    get_store().create(session)
    get_audit_log().record(AuditEvent(actor_id=principal.id, action="create_session", resource="session", session_id=sid))
    return {"session_id": sid, "state": session.state.value, "template_id": req.template_id}


def _process(session: ConsultationSession, raw: RawTranscript, principal: Principal) -> dict:
    settings = get_settings()
    if session.state is ReviewState.LISTENING:
        session.transition(ReviewState.PROCESSING)
    template = get_registry().get(session.template_id)
    result = run_pipeline(raw, template, settings=settings)
    session.raw_transcript = raw
    session.clean_transcript = result.clean
    session.extraction = result.extraction
    session.note = result.note
    session.risk = result.risk
    session.conversation_profile = result.profile
    if result.profile is not None:
        session.inference_mode = decide_mode(result.profile, settings).value
    session.template_version = template.version
    # Goal 10: stamp the active model + extraction-prompt version for rollback/audit.
    repo = get_repo()
    session.model_version = settings.gemini_model
    _active_extract = repo.active_prompt("extract")
    session.prompt_version = f"extract@{_active_extract.version}" if _active_extract else None
    get_store().set_result(session.session_id, result)
    if session.state is ReviewState.PROCESSING:
        session.transition(ReviewState.DRAFT)
    get_store().persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="process_pipeline", resource="session",
        session_id=session.session_id, phi_accessed=True,
    ))
    return {
        "session_id": session.session_id, "state": session.state.value,
        "risk_score": result.risk.score, "risk_markers": len(result.risk.markers),
        "grounding": result.grounding.model_dump(),
        "note_markdown": result.note.to_markdown(),
        "inference_mode": session.inference_mode,
        "profile": result.profile.summary() if result.profile else None,
    }


@app.post("/sessions/{sid}/transcript")
def submit_transcript(sid: str, raw: RawTranscript, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    raw.session_id = sid
    return _process(session, raw, principal)


@app.post("/sessions/{sid}/simulate")
def simulate(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    """Run the pipeline on a canned consultation — smoke-test aid (always mock STT)."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    raw = MockSarvamSTT().transcribe(b"", session_id=sid)
    return _process(session, raw, principal)


@app.post("/sessions/{sid}/audio")
async def upload_audio(sid: str, file: UploadFile = File(...), principal: Principal = Depends(get_principal)) -> dict:
    """Transcribe an uploaded recording via Sarvam V3 (batch-diarized → fallback) and run the pipeline."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    audio = await file.read()
    logger.info("audio upload: session=%s bytes=%d content_type=%s", sid, len(audio), file.content_type)
    if len(audio) < _MIN_AUDIO_BYTES:
        raise HTTPException(status_code=422, detail="no audible speech captured")
    try:
        # STT is a blocking SDK call — run it off the event loop.
        raw = await asyncio.to_thread(
            get_stt(get_settings()).transcribe_for_session, audio, session_id=sid
        )
    except Exception as exc:  # surface STT provider errors instead of a raw 500
        logger.exception("STT failed for session %s", sid)
        raise HTTPException(status_code=502, detail=f"transcription failed: {str(exc)[:400]}") from exc
    total_chars = sum(len((s.text or "")) for s in raw.segments)
    logger.info("STT result: session=%s segments=%d total_text_chars=%d sample=%r",
                sid, len(raw.segments), total_chars,
                (raw.segments[0].text[:80] if raw.segments else ""))
    if not _has_speech(raw):
        raise HTTPException(status_code=422, detail="no speech detected in audio")
    try:
        return await asyncio.to_thread(_process, session, raw, principal)
    except Exception as exc:
        logger.exception("pipeline failed for session %s", sid)
        raise HTTPException(status_code=500, detail=f"processing failed: {str(exc)[:400]}") from exc


@app.get("/sessions/{sid}")
def get_session(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    s = store.get(sid)
    return {
        "session_id": s.session_id, "state": s.state.value,
        "template": {"id": s.template_id, "version": s.template_version},
        "has_outputs": s.note is not None,
        "risk_score": s.risk.score if s.risk else None,
        "signed_by_name": s.signed_by_name,
        "signed_at": s.signed_at.isoformat() if s.signed_at else None,
    }


@app.get("/sessions/{sid}/outputs/{kind}")
def get_output(sid: str, kind: str, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    s = store.get(sid)
    mapping = {
        "raw": s.raw_transcript, "clean": s.clean_transcript,
        "extraction": s.extraction, "note": s.note, "risk": s.risk,
    }
    if kind not in mapping:
        raise HTTPException(status_code=404, detail=f"unknown output '{kind}'")
    obj = mapping[kind]
    if obj is None:
        raise HTTPException(status_code=409, detail=f"output '{kind}' not yet produced")
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action=f"view_{kind}", resource="output",
        session_id=sid, phi_accessed=True,
    ))
    return obj.model_dump(mode="json")


@app.get("/sessions/{sid}/coding")
def get_coding_hints(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    """On-demand, NON-AUTHORITATIVE ICD-10 hints for the session's documented diagnoses.

    Computed lazily (kept off the consult latency path); empty without an LLM. Each hint
    is grounded to the diagnosis it codes — the scribe never invents a diagnosis.
    """
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.extraction is None:
        raise HTTPException(status_code=409, detail="no extraction yet")
    hints = suggest_icd10(session.extraction, get_llm(get_settings()))
    return hints.model_dump(mode="json")


@app.post("/sessions/{sid}/note")
def edit_note(sid: str, req: NoteEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Save doctor edits to the generated note, then move the session to EDITED.

    Edits only the human-readable ``content_text`` of the named sections; the
    structured extraction and its provenance are left intact. Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.note is None:
        raise HTTPException(status_code=409, detail="no note to edit yet")

    edits = {e.section_id: e.content_text for e in req.sections}
    known = {s.section_id for s in session.note.sections}
    unknown = set(edits) - known
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown section(s): {', '.join(sorted(unknown))}")
    for section in session.note.sections:
        if section.section_id in edits:
            section.content_text = edits[section.section_id]
            section.empty = not section.content_text.strip()

    _advance_to_edited(session)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="edit_note", resource="note",
        session_id=sid, phi_accessed=True, detail=",".join(sorted(edits)),
    ))
    return {"session_id": sid, "state": session.state.value, "note": session.note.model_dump(mode="json")}


@app.put("/sessions/{sid}/extraction")
def edit_extraction(sid: str, req: ExtractionEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Save doctor edits to the clinical extraction, then re-derive the note + grounding.

    The doctor is the clinical authority: edited/added items are kept (grounded in flag
    mode), the note is re-rendered deterministically from the edited extraction, and
    fact verification re-runs so any value not matching the transcript is still surfaced.
    Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.extraction is None:
        raise HTTPException(status_code=409, detail="no extraction to edit yet")

    extraction = req.extraction
    extraction.session_id = sid
    template = get_registry().get(session.template_id)
    result = rebuild_from_extraction(
        extraction, template, session.clean_transcript,
        session.risk or RiskAssessment(session_id=sid), get_settings(),
        profile=session.conversation_profile,
    )
    session.extraction = result.extraction
    session.note = result.note
    store.set_result(sid, result)
    _advance_to_edited(session)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="edit_extraction", resource="extraction",
        session_id=sid, phi_accessed=True,
    ))
    return {
        "session_id": sid, "state": session.state.value,
        "extraction": result.extraction.model_dump(mode="json"),
        "note": result.note.model_dump(mode="json"),
        "grounding": result.grounding.model_dump(mode="json"),
    }


@app.put("/sessions/{sid}/risk")
def edit_risk(sid: str, req: RiskEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Save doctor edits to the risk markers (add / remove / edit). Re-scores from the
    edited markers. Risk is a non-authoritative attention aid, so this never changes the
    note or extraction. Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.risk is None:
        raise HTTPException(status_code=409, detail="no risk assessment to edit yet")

    session.risk = RiskAssessment(
        session_id=sid, markers=req.markers, score=aggregate_score(req.markers),
    )
    _advance_to_edited(session)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="edit_risk", resource="risk",
        session_id=sid, phi_accessed=True,
    ))
    return {"session_id": sid, "state": session.state.value, "risk": session.risk.model_dump(mode="json")}


@app.post("/sessions/{sid}/state")
def transition_state(sid: str, req: StateRequest, principal: Principal = Depends(get_principal)) -> dict:
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    perm = Permission.FINALIZE_NOTE if req.state is ReviewState.FINALIZED else (
        Permission.APPROVE_NOTE if req.state is ReviewState.APPROVED else Permission.EDIT_NOTE
    )
    _check(principal, perm)
    if req.state is ReviewState.FINALIZED and not (req.signed_by_name or "").strip():
        raise HTTPException(status_code=422, detail="a signing clinician name is required to finalize")
    try:
        session.transition(req.state)
    except IllegalTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
    if req.state is ReviewState.FINALIZED:
        session.signed_by_name = req.signed_by_name.strip()
        session.signature_image = req.signature_image
        session.signed_at = datetime.now(timezone.utc)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="transition", resource="session",
        session_id=sid, detail=req.state.value,
    ))
    return {"session_id": sid, "state": session.state.value}


@app.get("/sessions/{sid}/export/{fmt}")
def export_session(sid: str, fmt: str, principal: Principal = Depends(get_principal)):
    _check(principal, Permission.EXPORT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if not session.is_exportable:
        raise HTTPException(status_code=409, detail="session is not FINALIZED; cannot export")
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action=f"export_{fmt}", resource="session",
        session_id=sid, phi_accessed=True,
    ))
    if fmt == "json":
        return exporter.export_record(session)
    if fmt == "fhir":
        return exporter.export_fhir(session)
    if fmt == "markdown":
        return Response(content=exporter.export_note_markdown(session), media_type="text/markdown")
    if fmt == "pdf":
        if session.note is None:
            raise HTTPException(status_code=409, detail="no note to export")
        pdf = note_to_pdf(
            session.note,
            signed_by_name=session.signed_by_name,
            signed_at=session.signed_at,
            signature_image=session.signature_image,
        )
        return Response(
            content=pdf, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{sid}.pdf"'},
        )
    raise HTTPException(status_code=404, detail=f"unknown format '{fmt}'")


# ── Admin RBAC helper ──────────────────────────────────────────────────────────
def _require_role(principal: Principal, *roles: Role) -> None:
    if principal.role not in roles:
        raise HTTPException(
            status_code=403,
            detail=f"{principal.role.value} not permitted; requires {', '.join(r.value for r in roles)}",
        )


# ── Goal 1/2/4: conversation profile ────────────────────────────────────────────
@app.get("/sessions/{sid}/profile")
def get_profile(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    """Relationships, referenced patient, complexity, and confidence for the consult."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.conversation_profile is None:
        raise HTTPException(status_code=409, detail="no conversation profile yet")
    p = session.conversation_profile
    return {
        "session_id": sid, "inference_mode": session.inference_mode,
        "kind": p.kind.value, "referenced_patient": p.referenced_patient,
        "speakers": [s.model_dump(mode="json") for s in p.speakers],
        **p.summary(),
    }


# ── Goal 6: speaker timeline correction ─────────────────────────────────────────
class SpeakerCorrection(BaseModel):
    speaker_label: str
    role: SpeakerRole | None = None
    relationship: SpeakerRelationship | None = None
    subject_patient: str | None = None


class SpeakerCorrectionRequest(BaseModel):
    corrections: list[SpeakerCorrection] = []
    referenced_patient: str | None = None


@app.patch("/sessions/{sid}/speakers")
def correct_speakers(sid: str, req: SpeakerCorrectionRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Doctor corrects speaker roles/relationships (and optionally the referenced patient).

    If the referenced patient changes, the note is re-rendered immediately so the
    correction is reflected. Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.conversation_profile is None:
        raise HTTPException(status_code=409, detail="no conversation profile to correct")

    profile = session.conversation_profile
    by_label = {s.speaker_label: s for s in profile.speakers}
    for c in req.corrections:
        sp = by_label.get(c.speaker_label)
        if sp is None:
            raise HTTPException(status_code=422, detail=f"unknown speaker '{c.speaker_label}'")
        if c.role is not None:
            sp.role = c.role
        if c.relationship is not None:
            sp.relationship = c.relationship
        if c.subject_patient is not None:
            sp.subject_patient = c.subject_patient

    note_changed = False
    if req.referenced_patient is not None and req.referenced_patient != profile.referenced_patient:
        profile.referenced_patient = req.referenced_patient
        if session.extraction is not None:
            session.extraction.referenced_patient = req.referenced_patient
            template = get_registry().get(session.template_id)
            result = rebuild_from_extraction(
                session.extraction, template, session.clean_transcript,
                session.risk or RiskAssessment(session_id=sid), get_settings(), profile=profile,
            )
            session.note = result.note
            store.set_result(sid, result)
            note_changed = True

    _advance_to_edited(session)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="correct_speakers", resource="session",
        session_id=sid, phi_accessed=True,
    ))
    return {
        "session_id": sid, "referenced_patient": profile.referenced_patient,
        "speakers": [s.model_dump(mode="json") for s in profile.speakers],
        "note": session.note.model_dump(mode="json") if note_changed and session.note else None,
    }


# ── Goal 7: doctor consultation review ──────────────────────────────────────────
class ReviewRequest(BaseModel):
    rating: ReviewRating
    error_categories: list[ErrorCategory] = []
    comment: str | None = None


@app.post("/sessions/{sid}/review")
def submit_review(sid: str, req: ReviewRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Capture the doctor's 👍/👎 verdict (+ structured error categories). A
    needs_improvement review is auto-enqueued to the admin console (Goal 8)."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    profile = session.conversation_profile
    try:
        inf_mode = InferenceMode(session.inference_mode) if session.inference_mode else None
    except ValueError:
        inf_mode = None
    review = ConsultationReview(
        id=f"rev-{uuid.uuid4().hex[:12]}", session_id=sid, reviewer_id=principal.id,
        rating=req.rating, error_categories=req.error_categories, comment=req.comment,
        model_version=session.model_version, prompt_version=session.prompt_version,
        inference_mode=inf_mode, audio_confidence=profile.audio_confidence if profile else None,
        speaker_count=profile.speaker_count if profile else None,
    )
    get_repo().add_review(review)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="submit_review", resource="review", session_id=sid,
        detail=req.rating.value,
    ))
    return {"review_id": review.id, "rating": review.rating.value}


@app.get("/sessions/{sid}/reviews")
def list_session_reviews(sid: str, principal: Principal = Depends(get_principal)) -> list[dict]:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    return [r.model_dump(mode="json") for r in get_repo().list_reviews(sid)]


# ── Goal 8: admin review console ─────────────────────────────────────────────────
@app.get("/admin/reviews")
def admin_list_reviews(
    status: AdminStatus | None = None, error_category: ErrorCategory | None = None,
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    _require_role(principal, Role.ADMIN, Role.AUDITOR)
    return get_repo().list_admin_reviews(status=status, error_category=error_category)


class AdminReviewUpdate(BaseModel):
    status: AdminStatus | None = None
    assigned_to: str | None = None
    admin_notes: str | None = None


@app.patch("/admin/reviews/{admin_id}")
def admin_update_review(admin_id: str, req: AdminReviewUpdate, principal: Principal = Depends(get_principal)) -> dict:
    """Triage a review. Approving it seeds the improvement pipeline (Goal 9)."""
    _require_role(principal, Role.ADMIN)
    try:
        ar = get_repo().update_admin_review(
            admin_id, status=req.status, assigned_to=req.assigned_to, notes=req.admin_notes
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown admin review")
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="admin_triage", resource="admin_review",
        detail=f"{admin_id}:{req.status.value if req.status else 'update'}",
    ))
    return ar.model_dump(mode="json")


# ── Goal 9: improvement pipeline (human-gated; never auto-deploys) ───────────────
@app.get("/admin/improvements")
def list_improvements(stage: ImprovementStage | None = None, principal: Principal = Depends(get_principal)) -> list[dict]:
    _require_role(principal, Role.ADMIN, Role.AUDITOR)
    return [i.model_dump(mode="json") for i in get_repo().list_improvements(stage=stage)]


class AdvanceImprovementRequest(BaseModel):
    candidate_prompt: str | None = None
    eval_results: dict | None = None
    reject: bool = False


@app.post("/admin/improvements/{item_id}/advance")
def advance_improvement(item_id: str, req: AdvanceImprovementRequest, principal: Principal = Depends(get_principal)) -> dict:
    _require_role(principal, Role.ADMIN)
    try:
        item = get_repo().advance_improvement(
            item_id, candidate_prompt=req.candidate_prompt, eval_results=req.eval_results,
            approved_by=principal.id, reject=req.reject,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown improvement item")
    return item.model_dump(mode="json")


# ── Goal 10: prompt + model versioning ──────────────────────────────────────────
@app.get("/prompts")
def list_prompts(name: str | None = None, principal: Principal = Depends(get_principal)) -> list[dict]:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    return [p.model_dump(mode="json") for p in get_repo().list_prompts(name=name)]


class NewPromptRequest(BaseModel):
    name: str
    content: str
    activate: bool = False


@app.post("/prompts")
def create_prompt(req: NewPromptRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Register a NEW prompt version (immutable). Production rollout is a deliberate
    activation, never automatic (Goal 9 contract)."""
    _require_role(principal, Role.ADMIN)
    repo = get_repo()
    existing = repo.list_prompts(name=req.name)
    version = (max((p.version for p in existing), default=0)) + 1
    pv = PromptVersion(
        id=f"pv-{uuid.uuid4().hex[:12]}", name=req.name, version=version,
        content=req.content, active=req.activate, created_by=principal.id,
    )
    repo.add_prompt_version(pv)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="create_prompt", resource="prompt",
        detail=f"{pv.name}@{pv.version}",
    ))
    return pv.model_dump(mode="json")


@app.post("/prompts/{prompt_id}/activate")
def activate_prompt(prompt_id: str, principal: Principal = Depends(get_principal)) -> dict:
    _require_role(principal, Role.ADMIN)
    try:
        pv = get_repo().activate_prompt(prompt_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown prompt version")
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="activate_prompt", resource="prompt",
        detail=f"{pv.name}@{pv.version}",
    ))
    return pv.model_dump(mode="json")


@app.get("/models")
def list_models(principal: Principal = Depends(get_principal)) -> list[dict]:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    return [m.model_dump(mode="json") for m in get_repo().list_models()]


# ── Goal 11: AI consultation editor ──────────────────────────────────────────────
class AiEditRequest(BaseModel):
    instruction: str


@app.post("/sessions/{sid}/ai-edit")
def ai_edit_preview(sid: str, req: AiEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Preview an AI edit of the note from a natural-language instruction. Does NOT apply."""
    _check(principal, Permission.EDIT_NOTE)
    if not get_settings().ai_edit_enabled:
        raise HTTPException(status_code=403, detail="AI editor is disabled")
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.note is None:
        raise HTTPException(status_code=409, detail="no note to edit yet")
    try:
        proposal = propose_note_edit(session.note, req.instruction, get_llm(get_settings()))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"AI edit unavailable: {str(exc)[:200]}")
    current = {s.section_id: s.content_text for s in session.note.sections}
    return {
        "instruction": req.instruction,
        "changes": [
            {"section_id": c.section_id, "before": current.get(c.section_id, ""), "after": c.content_text}
            for c in proposal.changes
        ],
    }


class AiEditApplyRequest(BaseModel):
    instruction: str = ""
    changes: list[NoteSectionEdit] = []


@app.post("/sessions/{sid}/ai-edit/apply")
def ai_edit_apply(sid: str, req: AiEditApplyRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Apply approved AI-edit changes to the note and record them for undo/redo (Goal 11)."""
    _check(principal, Permission.EDIT_NOTE)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.note is None:
        raise HTTPException(status_code=409, detail="no note to edit yet")
    known = {s.section_id for s in session.note.sections}
    repo = get_repo()
    for edit in req.changes:
        if edit.section_id not in known:
            raise HTTPException(status_code=422, detail=f"unknown section '{edit.section_id}'")
        for section in session.note.sections:
            if section.section_id == edit.section_id:
                repo.add_edit(sid, {
                    "instruction": req.instruction, "section_id": edit.section_id,
                    "before": section.content_text, "after": edit.content_text,
                    "applied": True, "by": principal.id,
                })
                section.content_text = edit.content_text
                section.empty = not edit.content_text.strip()
    _advance_to_edited(session)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="ai_edit_apply", resource="note", session_id=sid,
        phi_accessed=True, detail=req.instruction[:120],
    ))
    return {"session_id": sid, "state": session.state.value, "note": session.note.model_dump(mode="json")}


@app.get("/sessions/{sid}/edits")
def list_edits(sid: str, principal: Principal = Depends(get_principal)) -> list[dict]:
    _check(principal, Permission.EDIT_NOTE)
    return get_repo().list_edits(sid)


# ── Prescription preview: hospital document templates ────────────────────────────
@app.get("/document-templates")
def list_document_templates(
    hospital_id: str | None = None, doc_type: str | None = None,
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    return [d.model_dump(mode="json") for d in get_repo().list_document_templates(hospital_id, doc_type)]


@app.post("/document-templates")
def create_document_template(template: DocumentTemplate, principal: Principal = Depends(get_principal)) -> dict:
    """Register a hospital's printable design (HTML/CSS with {{placeholders}})."""
    _check(principal, Permission.MANAGE_TEMPLATES)
    if not template.id:
        template = template.model_copy(update={"id": f"doc-{uuid.uuid4().hex[:12]}"})
    get_repo().add_document_template(template)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="create_document_template", resource="document_template",
        detail=f"{template.doc_type}:{template.name}",
    ))
    return template.model_dump(mode="json")


class PreviewRequest(BaseModel):
    template_id: str | None = None
    doc_type: str = "prescription"
    branding: dict = {}


@app.post("/sessions/{sid}/document/preview")
def preview_document(sid: str, req: PreviewRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Render a hospital-branded document for the consult and store it as a draft.

    Fills the template with DOCTOR-CONFIRMED content only (note/extraction + branding);
    the AI authors nothing. The doctor previews, edits, and approves. Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if session.extraction is None:
        raise HTTPException(status_code=409, detail="no clinical content to render yet")
    repo = get_repo()
    template = (
        repo.get_document_template(req.template_id) if req.template_id
        else repo.default_document_template(req.doc_type)
    )
    if template is None:
        raise HTTPException(status_code=404, detail="no document template available")
    html = render_for_session(template, session, req.branding)
    doc = RenderedDocument(
        id=f"rdoc-{uuid.uuid4().hex[:12]}", session_id=sid, document_template_id=template.id,
        doc_type=template.doc_type, status=DocumentStatus.PREVIEWED, rendered_html=html,
    )
    repo.save_rendered_document(doc)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="preview_document", resource="document",
        session_id=sid, phi_accessed=True, detail=template.doc_type,
    ))
    return doc.model_dump(mode="json")


class DocumentEditRequest(BaseModel):
    edited_html: str


@app.put("/documents/{doc_id}")
def edit_document(doc_id: str, req: DocumentEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.EDIT_NOTE)
    repo = get_repo()
    doc = repo.get_rendered_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="unknown document")
    doc.edited_html = req.edited_html
    doc.status = DocumentStatus.EDITED
    repo.save_rendered_document(doc)
    return doc.model_dump(mode="json")


@app.post("/documents/{doc_id}/approve")
def approve_document(doc_id: str, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.EDIT_NOTE)
    repo = get_repo()
    doc = repo.get_rendered_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="unknown document")
    doc.status = DocumentStatus.APPROVED
    doc.approved_by = principal.id
    doc.approved_at = datetime.now(timezone.utc)
    repo.save_rendered_document(doc)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="approve_document", resource="document",
        session_id=doc.session_id, phi_accessed=True,
    ))
    return doc.model_dump(mode="json")


@app.get("/sessions/{sid}/documents")
def list_documents(sid: str, principal: Principal = Depends(get_principal)) -> list[dict]:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    return [d.model_dump(mode="json") for d in get_repo().list_rendered_documents(sid)]


# ── Goal 13: feature flags ───────────────────────────────────────────────────────
@app.get("/feature-flags")
def get_feature_flags(principal: Principal = Depends(get_principal)) -> dict:
    """Runtime feature flags + the relevant config toggles (read-only view)."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    s = get_settings()
    return {
        "config": {
            "resolve_subjects": s.resolve_subjects,
            "auto_inference_mode": s.auto_inference_mode,
            "default_inference_mode": s.default_inference_mode,
            "complexity_threshold": s.complexity_threshold,
            "ai_edit_enabled": s.ai_edit_enabled,
            "single_pass_llm": s.single_pass_llm,
            "streaming_stt": s.streaming_stt,
        },
        "runtime": get_repo().list_flags(),
    }


class FlagRequest(BaseModel):
    key: str
    enabled: bool
    value: dict = {}


@app.post("/feature-flags")
def set_feature_flag(req: FlagRequest, principal: Principal = Depends(get_principal)) -> dict:
    _require_role(principal, Role.ADMIN)
    return get_repo().set_flag(req.key, req.enabled, req.value)


# ── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws/consultation")
async def ws_consultation(websocket: WebSocket) -> None:
    await consultation_ws(websocket, get_store(), get_settings())
