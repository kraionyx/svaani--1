"""FastAPI application — REST routes + the consultation WebSocket.

Auth in this scaffold is header-driven (``X-User-Id`` / ``X-Role``); replace the
``get_principal`` dependency with verified OIDC/JWT (Keycloak) in production. Every
PHI-touching action is permission-checked and audited.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Response, UploadFile, WebSocket
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.audio.ws import consultation_ws
from app.config import get_settings
from app.export import exporter
from app.export.pdf import note_to_pdf
from app.pipeline.orchestrator import run_pipeline
from app.security.audit import AuditEvent, get_audit_log
from app.security.rbac import AccessDenied, Permission, Principal, Role, require_permission
from app.schemas.session import ConsultationSession, IllegalTransition, ReviewState
from app.schemas.template import TemplateDefinition
from app.schemas.transcript import RawTranscript
from app.stt.sarvam import MockSarvamSTT, get_stt
from app.store import get_store
from app.templates.registry import get_registry
from pydantic import BaseModel

app = FastAPI(title="Karaionyx AI Medical Scribe", version="0.1.0")

logger = logging.getLogger("karaionyx.audio")

# Minimum uploaded-audio size; anything smaller is effectively a silent/empty
# recording (a bare 16k mono WAV header is ~44 bytes).
_MIN_AUDIO_BYTES = 1024


def _has_speech(raw: RawTranscript) -> bool:
    """True if the transcript carries any non-empty utterance text."""
    return any((seg.text or "").strip() for seg in raw.segments)

# ── Dashboard (single-page UI served by the API) ─────────────────────────────
_STATIC_DIR = Path(__file__).parent / "static"
# Where the registry loads seed templates from (project_root/docs/templates).
_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "docs" / "templates"
if _STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_STATIC_DIR), html=True), name="ui")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/ui/")


# ── Auth (scaffold) ──────────────────────────────────────────────────────────
def get_principal(
    x_user_id: str = Header(default="dev-doctor"),
    x_role: str = Header(default="doctor"),
) -> Principal:
    try:
        return Principal(id=x_user_id, role=Role(x_role))
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
        raw = get_stt(get_settings()).transcribe_for_session(audio, session_id=sid)
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
        return _process(session, raw, principal)
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
    try:
        session.transition(req.state)
    except IllegalTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
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
    if fmt == "markdown":
        return Response(content=exporter.export_note_markdown(session), media_type="text/markdown")
    if fmt == "pdf":
        if session.note is None:
            raise HTTPException(status_code=409, detail="no note to export")
        pdf = note_to_pdf(session.note)
        return Response(
            content=pdf, media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{sid}.pdf"'},
        )
    raise HTTPException(status_code=404, detail=f"unknown format '{fmt}'")


# ── WebSocket ────────────────────────────────────────────────────────────────
@app.websocket("/ws/consultation")
async def ws_consultation(websocket: WebSocket) -> None:
    await consultation_ws(websocket, get_store(), get_settings())
