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
from app.export import exporter
from app.export.pdf import note_to_pdf
from app.observability import setup_observability
from app.llm.base import get_llm
from app.pipeline.coding import suggest_icd10
from app.pipeline.orchestrator import rebuild_from_extraction, run_pipeline
from app.pipeline.risk import aggregate_score
from app.security.audit import AuditEvent, get_audit_log
from app.security.auth import AuthError, principal_from
from app.security.rbac import AccessDenied, Permission, Principal, Role, require_permission
from app.schemas.clinical import ClinicalExtraction
from app.schemas.risk import RiskAssessment, RiskMarker
from app.schemas.session import ConsultationSession, IllegalTransition, ReviewState
from app.schemas.template import TemplateDefinition
from app.schemas.transcript import RawTranscript
from app.stt.sarvam import MockSarvamSTT, get_stt
from app.store import get_store
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
    session.template_version = template.version
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


# ── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws/consultation")
async def ws_consultation(websocket: WebSocket) -> None:
    await consultation_ws(websocket, get_store(), get_settings())
