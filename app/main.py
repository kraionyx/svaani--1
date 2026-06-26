"""FastAPI application — REST routes + the consultation WebSocket.

Auth in this scaffold is header-driven (``X-User-Id`` / ``X-Role``); replace the
``get_principal`` dependency with verified OIDC/JWT (Keycloak) in production. Every
PHI-touching action is permission-checked and audited.
"""
from __future__ import annotations

import asyncio
import time
import json
import logging
import uuid
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import request_id_ctx, setup_logging
from app.security.startup import validate_production

from app.admin_routes import router as admin_router
from app.audio.ws import consultation_ws
from app.config import get_settings
from app.data.repo import get_repo
from app.logging_service import get_logging_service
from app.export import exporter
from app.export.pdf import note_to_pdf
from app.observability import setup_observability
from app.llm.base import get_llm
from app.pipeline.ai_edit import propose_extraction_edit, propose_note_edit, propose_risk_edit
from app.pipeline.coding import suggest_icd10
from app.pipeline.inference_mode import decide_mode, split_mode_choice
from app.pipeline.orchestrator import rebuild_from_extraction, run_pipeline
from app.pipeline.prompt_provider import invalidate_prompts
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
from app.storage.supabase_storage import upload_consultation_files
from app.templates.document_renderer import render_for_session
from app.templates.registry import get_registry
from pydantic import BaseModel

# The sarvamai streaming SDK calls pydantic v2 models' deprecated `.dict()` internally
# (we never do). Silence that one third-party deprecation so live server logs stay clean.
warnings.filterwarnings("ignore", message=r"The `dict` method is deprecated", category=DeprecationWarning)

logger = logging.getLogger("svaani.audio")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: configure logging + validate config. Shutdown: drain + close pools."""
    settings = get_settings()
    setup_logging(settings)
    # Refuse an unsafe production boot (PHI plaintext, dev auth, default admin pw, …);
    # in development this only logs warnings.
    validate_production(settings)
    logger.info(
        "Svaani starting: env=%s store=%s auth=%s vertex=%s sarvam=%s metrics=%s debug=%s",
        settings.environment, settings.store_backend, settings.auth_mode,
        "live" if settings.use_vertex else "off", "live" if settings.use_sarvam else "mock",
        settings.enable_metrics, settings.debug,
    )
    try:
        yield
    finally:
        # Graceful shutdown: flush queued telemetry, then close every connection pool.
        logger.info("Svaani shutting down — flushing logging + closing pools")
        try:
            get_logging_service().close()
        except Exception:  # noqa: BLE001
            logger.debug("logging service close error", exc_info=True)
        for closer in (lambda: get_store().close(), lambda: get_repo().close()):
            try:
                closer()
            except Exception:  # noqa: BLE001
                logger.debug("pool close error", exc_info=True)


app = FastAPI(
    title="Svaani AI Medical Scribe",
    version=get_settings().app_version,
    debug=get_settings().debug,
    lifespan=lifespan,
)
app.include_router(admin_router)

class LimitUploadSize(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int) -> None:
        super().__init__(app)
        self.max_upload_size = max_upload_size

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_upload_size:
                return JSONResponse(status_code=413, content={"detail": "Payload too large"})
        return await call_next(request)

app.add_middleware(LimitUploadSize, max_upload_size=50 * 1024 * 1024) # 50MB

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


# ── Global exception handlers ─────────────────────────────────────────────────
# Domain errors map to the right status; everything else returns a clean 500 (full
# traceback is logged with the request-id, and only echoed to the client in debug).
@app.exception_handler(AccessDenied)
async def _access_denied_handler(request: Request, exc: AccessDenied):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(AuthError)
async def _auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse(status_code=401, content={"detail": str(exc)})


@app.exception_handler(IllegalTransition)
async def _illegal_transition_handler(request: Request, exc: IllegalTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def _unhandled_handler(request: Request, exc: Exception):
    rid = request_id_ctx.get()
    logger.exception("unhandled error rid=%s %s %s", rid, request.method, request.url.path)
    body = {"detail": "internal server error", "request_id": rid}
    if get_settings().debug:
        import traceback as _tb
        body["error"] = f"{type(exc).__name__}: {exc}"
        body["traceback"] = _tb.format_exc()
    return JSONResponse(status_code=500, content=body)


# Observability: request-id propagation, access logs, security headers, Prometheus /metrics.
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
    # Serve immutable, content-hashed build assets directly. Everything else under /app is
    # a client-side (React Router) route, so it falls back to index.html — see serve_spa().
    # This MUST be registered before the /app/{full_path:path} catch-all below so that
    # asset requests hit the static mount instead of the SPA shell.
    app.mount("/app/assets", StaticFiles(directory=str(_WEBAPP_DIR / "assets")), name="app-assets")


def _spa_index() -> FileResponse:
    """Return the SPA shell (index.html), or 503 if the frontend hasn't been built."""
    index = _WEBAPP_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=503, detail="SPA not built — run: cd web-app && npm run build")
    # index.html itself must never be cached, so a new deploy's hashed assets are picked up.
    return FileResponse(str(index), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # Prefer the new streaming SPA when it has been built; else the legacy UI.
    return RedirectResponse("/app/" if _WEBAPP_DIR.exists() else "/ui/")


@app.get("/admin1", include_in_schema=False)
@app.get("/admin1/", include_in_schema=False)
def admin_ui() -> FileResponse:
    """Serve the SPA at /admin1 so the React path check renders AdminPage."""
    return _spa_index()


@app.get("/app", include_in_schema=False)
@app.get("/app/{full_path:path}", include_in_schema=False)
def serve_spa(full_path: str = "") -> FileResponse:
    """SPA history-fallback. Serve a real built file when one exists (favicon, manifest,
    etc.); otherwise return index.html so the client-side router resolves the path. This
    is what lets enterprise deep-links like /app/templates/new survive a hard reload
    instead of 404ing. Path-traversal is blocked by confining matches to the dist root."""
    if full_path:
        candidate = (_WEBAPP_DIR / full_path).resolve()
        webapp_root = _WEBAPP_DIR.resolve()
        if candidate.is_file() and (candidate == webapp_root or webapp_root in candidate.parents):
            return FileResponse(str(candidate))
    return _spa_index()


# ── Auth ───────────────────────────────────────────────────────────────────────
def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_user_id: str = Header(default="dev-doctor"),
    x_role: str = Header(default="doctor"),
) -> Principal:
    try:
        principal = principal_from(
            get_settings(), authorization=authorization, x_user_id=x_user_id, x_role=x_role
        )
    except AuthError as e:
        # Surface the REASON in the admin console (not just a bare 401 in the access log).
        # Client-side causes are 'warning'; an unreachable verifier is 'error' (operational).
        _log_auth_event(
            request, severity=getattr(e, "severity", "warning"),
            error_type=f"auth_{getattr(e, 'reason', 'invalid_token')}", message=str(e),
        )
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError:
        _log_auth_event(request, severity="warning", error_type="auth_unknown_role",
                        message=f"unknown role '{x_role}'")
        raise HTTPException(status_code=400, detail=f"unknown role '{x_role}'")
    # Stash the resolved identity so the observability middleware logs the REAL user (in jwt
    # mode the browser sends a Bearer token, not X-User-Id, so the header would read 'anonymous').
    request.state.user_id = principal.id
    request.state.user_email = principal.email
    return principal


def _log_auth_event(request: Request, *, severity: str, error_type: str, message: str) -> None:
    """Record an auth failure to the logging service so it appears in the admin console's
    Errors view with a request-id, endpoint, and reason. Best-effort; never raises."""
    rid = request_id_ctx.get()
    logger.warning("auth rejected rid=%s %s %s: %s", rid, request.method, request.url.path, message)
    try:
        get_logging_service().log_error(
            request_id=rid, user_id=None, endpoint=request.url.path,
            error_type=error_type, error_message=message, severity=severity, source="auth",
        )
    except Exception:  # noqa: BLE001 — logging must never break the request
        logger.debug("failed to record auth event", exc_info=True)


def _check(principal: Principal, perm: Permission) -> None:
    try:
        require_permission(principal, perm)
    except AccessDenied as e:
        raise HTTPException(status_code=403, detail=str(e))


def _load_session(sid: str, principal: Principal):
    """Fetch a session by id, enforcing per-user ownership in jwt mode.

    Returns ``(store, session)``. In the dev header scaffold there are no real users, so
    ownership is not enforced. In jwt mode a consultation may be touched only by the
    practitioner who created it — defense-in-depth on top of unguessable session ids and
    Postgres RLS — while ADMIN/AUDITOR keep cross-user visibility for the review console.
    """
    store = get_store()
    if not store.exists(sid):
        raise HTTPException(status_code=404, detail="unknown session")
    session = store.get(sid)
    if (get_settings().auth_mode == "jwt"
            and session.practitioner_id
            and session.practitioner_id != principal.id
            and principal.role not in (Role.ADMIN, Role.AUDITOR)):
        # A user tried to reach a session they don't own — log it for the admin console.
        logger.warning("ownership denied: user=%s tried session=%s owner=%s",
                       principal.id, sid, session.practitioner_id)
        try:
            get_logging_service().log_error(
                request_id=request_id_ctx.get(), user_id=principal.id, endpoint=f"/sessions/{sid}",
                error_type="auth_ownership_denied",
                error_message=f"user {principal.id} attempted to access session owned by {session.practitioner_id}",
                severity="warning", source="auth",
            )
        except Exception:  # noqa: BLE001
            logger.debug("failed to record ownership denial", exc_info=True)
        raise HTTPException(status_code=403, detail="not your consultation")
    return store, session


# ── Request bodies ───────────────────────────────────────────────────────────
class CreateSessionRequest(BaseModel):
    template_id: str = "soap"
    patient_id: str | None = None
    practitioner_id: str | None = None
    # Goal 3 pre-consult mode choice: "auto" | "realtime" | "batch". ``auto`` (bool) is
    # the legacy form, kept as a fallback when ``mode`` is omitted.
    mode: str | None = None
    auto: bool = False


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


# ── Public auth config ───────────────────────────────────────────────────────
@app.get("/auth/config")
def auth_config() -> dict:
    """Public bootstrap for the SPA's Supabase client — only browser-safe values (the
    anon key is designed to be public). The SPA reads this at startup so credentials live
    in ONE place (the backend .env), not duplicated into a Vite build. ``auth_required``
    tells the SPA whether to gate the app behind login (true only in jwt mode with creds)."""
    s = get_settings()
    required = s.auth_mode == "jwt" and bool(s.supabase_url and s.supabase_anon_key)
    # Help developers spot a half-wired setup (e.g. jwt mode but no Supabase URL/key) right
    # in the logs at SPA boot, instead of debugging a silent "login never appears".
    if s.auth_mode == "jwt" and not required:
        logger.warning("auth: SCRIBE_AUTH_MODE=jwt but Supabase URL/anon key missing — "
                       "SPA will NOT gate behind login. Set SCRIBE_SUPABASE_URL + SCRIBE_SUPABASE_ANON_KEY.")
    else:
        logger.debug("auth: /auth/config served (auth_required=%s, url_set=%s)",
                     required, bool(s.supabase_url))
    return {
        "supabase_url": s.supabase_url,
        "supabase_anon_key": s.supabase_anon_key,
        "auth_mode": s.auth_mode,
        # Gate the UI only when real auth is wired (jwt mode + a configured Supabase project).
        "auth_required": required,
    }


# ── Health & templates ───────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    """Liveness probe — is the process up? No secrets/config leaked (was: key length,
    project id, backend). Provider status reflects whether live creds are configured."""
    s = get_settings()
    return {
        "status": "ok",
        "app": s.app_name,
        "version": s.app_version,
        "sarvam": "live" if s.use_sarvam else "mock",
        "vertex": "live" if s.use_vertex else "disabled",
    }


@app.get("/health/ready", include_in_schema=False)
def readiness() -> Response:
    """Readiness probe — can we serve traffic? Probes the durable store + logging DB.
    Returns 503 (not ready) if a configured backend can't be reached."""
    s = get_settings()
    checks: dict[str, str] = {}
    ready = True

    # Session store: only the durable backends have a pool to probe.
    if s.store_backend in {"sqlite", "supabase"}:
        try:
            store = get_store()
            ok = bool(store.exists("__readiness_probe__")) or True  # any answer == reachable
            checks["store"] = "ok" if ok else "fail"
        except Exception:  # noqa: BLE001
            checks["store"] = "fail"; ready = False
    else:
        checks["store"] = "memory"

    # Supabase logging service (if configured).
    svc = get_logging_service()
    if getattr(svc, "available", False):
        if svc.ping():
            checks["logging_db"] = "ok"
        else:
            checks["logging_db"] = "fail"; ready = False
    else:
        checks["logging_db"] = "disabled"

    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


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
    auto_mode, manual_mode = split_mode_choice(req.mode, legacy_auto=req.auto)
    session = ConsultationSession(
        session_id=sid, template_id=req.template_id,
        # Owner is ALWAYS the authenticated caller — a client can't assign a consult to
        # another user (the request's practitioner_id field is ignored for that reason).
        patient_id=req.patient_id, practitioner_id=principal.id,
        auto_mode=auto_mode, manual_mode=manual_mode,
    )
    get_store().create(session)
    get_audit_log().record(AuditEvent(actor_id=principal.id, action="create_session", resource="session", session_id=sid))
    get_logging_service().update_doctor(
        user_id=principal.id, increment_sessions=1, feature="session_create",
        email=principal.email,  # jwt mode: record the real identity for the admin Doctors view
    )
    return {"session_id": sid, "state": session.state.value, "template_id": req.template_id}


@app.get("/sessions")
def list_my_sessions(principal: Principal = Depends(get_principal)) -> list[dict]:
    """List the authenticated user's own consultations (most-recent first), as PHI-free
    metadata for a 'My consultations' view. Each user sees only their own sessions."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    return get_store().list_for_practitioner(principal.id)


async def _process(session: ConsultationSession, raw: RawTranscript, principal: Principal) -> dict:
    settings = get_settings()
    if session.state is ReviewState.LISTENING:
        session.transition(ReviewState.PROCESSING)
    template = get_registry().get(session.template_id)
    _t0 = time.perf_counter()
    result = await run_pipeline(raw, template, settings=settings)
    _pipeline_ms = int((time.perf_counter() - _t0) * 1000)
    session.raw_transcript = raw
    session.clean_transcript = result.clean
    session.extraction = result.extraction
    session.note = result.note
    session.risk = result.risk
    session.conversation_profile = result.profile
    if result.profile is not None:
        session.inference_mode = decide_mode(
            result.profile, settings, auto=session.auto_mode, manual=session.manual_mode
        ).value
    session.template_version = template.version
    # Goal 10: stamp the active model + extraction-prompt version for rollback/audit.
    repo = get_repo()
    session.model_version = settings.gemini_model
    _active_extract = await asyncio.to_thread(repo.active_prompt, "extract")
    session.prompt_version = f"extract@{_active_extract.version}" if _active_extract else None
    
    def _save_all():
        # Goals 4/12: record pipeline latency so the analytics tab can show p50/p95 by mode.
        repo.record_stage_latency({
            "stage": "pipeline", "session_id": session.session_id, "latency_ms": _pipeline_ms,
            "inference_mode": session.inference_mode, "model_version": session.model_version,
        })
        for _stage, _ms in (result.timings_ms or {}).items():
            if _stage == "total":
                continue
            repo.record_stage_latency({
                "stage": _stage, "session_id": session.session_id, "latency_ms": _ms,
                "inference_mode": session.inference_mode, "model_version": session.model_version,
            })
        get_store().set_result(session.session_id, result)
        if session.state is ReviewState.PROCESSING:
            session.transition(ReviewState.DRAFT)
        get_store().persist(session)
        get_audit_log().record(AuditEvent(
            actor_id=principal.id, action="process_pipeline", resource="session",
            session_id=session.session_id, phi_accessed=True,
        ))

    await asyncio.to_thread(_save_all)

    # Upload transcript + note as .txt files to Supabase Storage (background, best-effort).
    upload_consultation_files(
        session_id=session.session_id,
        transcript_text=result.clean.full_text or raw.full_text,
        note_markdown=result.note.to_markdown(),
        settings=settings,
    )
    return {
        "session_id": session.session_id, "state": session.state.value,
        "risk_score": result.risk.score, "risk_markers": len(result.risk.markers),
        "grounding": result.grounding.model_dump(),
        "note_markdown": result.note.to_markdown(),
        "inference_mode": session.inference_mode,
        "profile": result.profile.summary() if result.profile else None,
    }


@app.post("/sessions/{sid}/transcript")
async def submit_transcript(sid: str, raw: RawTranscript, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store, session = _load_session(sid, principal)
    raw.session_id = sid
    return await _process(session, raw, principal)


@app.post("/sessions/{sid}/simulate")
async def simulate(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    """Run the pipeline on a canned consultation — smoke-test aid (always mock STT)."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store, session = _load_session(sid, principal)
    raw = MockSarvamSTT().transcribe(b"", session_id=sid)
    return await _process(session, raw, principal)


@app.post("/sessions/{sid}/audio")
async def upload_audio(sid: str, file: UploadFile = File(...), principal: Principal = Depends(get_principal)) -> dict:
    """Transcribe an uploaded recording via Sarvam V3 (batch-diarized → fallback) and run the pipeline."""
    _check(principal, Permission.VIEW_TRANSCRIPT)
    store, session = _load_session(sid, principal)
    import tempfile
    import os
    import shutil
    
    # Save the upload to disk in chunks to avoid blowing up RAM (0-copy processing)
    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    audio_size = 0
    try:
        with os.fdopen(fd, "wb") as f_out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f_out.write(chunk)
                audio_size += len(chunk)
        
        logger.info("audio upload: session=%s bytes=%d content_type=%s", sid, audio_size, file.content_type)
        if audio_size < _MIN_AUDIO_BYTES:
            raise HTTPException(status_code=422, detail="no audible speech captured")
        
        try:
            # STT is a blocking SDK call — run it off the event loop.
            raw = await asyncio.to_thread(
                get_stt(get_settings()).transcribe_for_session, tmp_path, session_id=sid
            )
        except Exception as exc:  # surface STT provider errors instead of a raw 500
            logger.exception("STT failed for session %s", sid)
            raise HTTPException(status_code=502, detail=f"transcription failed: {str(exc)[:400]}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    total_chars = sum(len((s.text or "")) for s in raw.segments)
    logger.info("STT result: session=%s segments=%d total_text_chars=%d sample=%r",
                sid, len(raw.segments), total_chars,
                (raw.segments[0].text[:80] if raw.segments else ""))
    if not _has_speech(raw):
        raise HTTPException(status_code=422, detail="no speech detected in audio")
    try:
        return await _process(session, raw, principal)
    except Exception as exc:
        logger.exception("pipeline failed for session %s", sid)
        raise HTTPException(status_code=500, detail=f"processing failed: {str(exc)[:400]}") from exc


@app.get("/sessions/{sid}")
def get_session(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    _check(principal, Permission.VIEW_TRANSCRIPT)
    _store, s = _load_session(sid, principal)
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
    _store, s = _load_session(sid, principal)
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
    store, session = _load_session(sid, principal)
    if session.extraction is None:
        raise HTTPException(status_code=409, detail="no extraction yet")
    hints = suggest_icd10(session.extraction, get_llm(get_settings()))
    return hints.model_dump(mode="json")


@app.post("/sessions/{sid}/note")
async def edit_note(sid: str, req: NoteEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Save doctor edits to the generated note, then move the session to EDITED.

    Edits only the human-readable ``content_text`` of the named sections; the
    structured extraction and its provenance are left intact. Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store, session = await asyncio.to_thread(_load_session, sid, principal)
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
    
    def _save():
        store.persist(session)
        get_audit_log().record(AuditEvent(
            actor_id=principal.id, action="edit_note", resource="note",
            session_id=sid, phi_accessed=True, detail=",".join(sorted(edits)),
        ))
    await asyncio.to_thread(_save)
    return {"session_id": sid, "state": session.state.value, "note": session.note.model_dump(mode="json")}


@app.put("/sessions/{sid}/extraction")
async def edit_extraction(sid: str, req: ExtractionEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Save doctor edits to the clinical extraction, then re-derive the note + grounding.

    The doctor is the clinical authority: edited/added items are kept (grounded in flag
    mode), the note is re-rendered deterministically from the edited extraction, and
    fact verification re-runs so any value not matching the transcript is still surfaced.
    Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store, session = await asyncio.to_thread(_load_session, sid, principal)
    if session.extraction is None:
        raise HTTPException(status_code=409, detail="no extraction to edit yet")

    extraction = req.extraction
    extraction.session_id = sid
    template = get_registry().get(session.template_id)
    
    def _rebuild():
        return rebuild_from_extraction(
            extraction, template, session.clean_transcript,
            session.risk or RiskAssessment(session_id=sid), get_settings(),
            profile=session.conversation_profile,
        )
    result = await asyncio.to_thread(_rebuild)
    
    session.extraction = result.extraction
    session.note = result.note
    
    def _save():
        store.set_result(sid, result)
        _advance_to_edited(session)
        store.persist(session)
        get_audit_log().record(AuditEvent(
            actor_id=principal.id, action="edit_extraction", resource="extraction",
            session_id=sid, phi_accessed=True,
        ))
    await asyncio.to_thread(_save)
    return {
        "session_id": sid, "state": session.state.value,
        "extraction": result.extraction.model_dump(mode="json"),
        "note": result.note.model_dump(mode="json"),
        "grounding": result.grounding.model_dump(mode="json"),
    }


@app.put("/sessions/{sid}/risk")
async def edit_risk(sid: str, req: RiskEditRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Save doctor edits to the risk markers (add / remove / edit). Re-scores from the
    edited markers. Risk is a non-authoritative attention aid, so this never changes the
    note or extraction. Requires EDIT_NOTE.
    """
    _check(principal, Permission.EDIT_NOTE)
    store, session = await asyncio.to_thread(_load_session, sid, principal)
    if session.risk is None:
        raise HTTPException(status_code=409, detail="no risk assessment to edit yet")

    session.risk = RiskAssessment(
        session_id=sid, markers=req.markers, score=aggregate_score(req.markers),
    )
    _advance_to_edited(session)
    
    def _save():
        store.persist(session)
        get_audit_log().record(AuditEvent(
            actor_id=principal.id, action="edit_risk", resource="risk",
            session_id=sid, phi_accessed=True,
        ))
    await asyncio.to_thread(_save)
    return {"session_id": sid, "state": session.state.value, "risk": session.risk.model_dump(mode="json")}


@app.post("/sessions/{sid}/state")
async def transition_state(sid: str, req: StateRequest, principal: Principal = Depends(get_principal)) -> dict:
    store, session = await asyncio.to_thread(_load_session, sid, principal)
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
        def _update_doctor():
            get_logging_service().update_doctor(
                user_id=principal.id, increment_reports=1, feature="report_finalized"
            )
        await asyncio.to_thread(_update_doctor)
        
    def _save():
        store.persist(session)
        get_audit_log().record(AuditEvent(
            actor_id=principal.id, action="transition", resource="session",
            session_id=sid, detail=req.state.value,
        ))
    await asyncio.to_thread(_save)
    return {"session_id": sid, "state": session.state.value}


@app.get("/sessions/{sid}/export/{fmt}")
def export_session(sid: str, fmt: str, principal: Principal = Depends(get_principal)):
    _check(principal, Permission.EXPORT)
    store, session = _load_session(sid, principal)
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
    store, session = _load_session(sid, principal)
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
    store, session = _load_session(sid, principal)
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
    store, session = _load_session(sid, principal)
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
    _record_ab_metrics(sid, review)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="submit_review", resource="review", session_id=sid,
        detail=req.rating.value,
    ))
    return {"review_id": review.id, "rating": review.rating.value}


def _ab_arm(prompt_name: str, session_id: str, b_pct: int) -> str:
    """Deterministic A/B split: the same session always lands in the same arm."""
    import hashlib

    bucket = int(hashlib.sha1(f"{prompt_name}:{session_id}".encode()).hexdigest(), 16) % 100
    return "b" if bucket < max(0, min(100, b_pct)) else "a"


def _record_ab_metrics(sid: str, review: ConsultationReview) -> None:
    """Attach this consult's review verdict to any active prompt A/B test (Goal 13)."""
    repo = get_repo()
    for flag in repo.list_flags():
        key = flag["key"]
        if not (key.startswith("prompt.") and key.endswith(".ab") and flag.get("enabled")):
            continue
        name = key[len("prompt."):-len(".ab")]
        b_pct = int((flag.get("value") or {}).get("b_pct", 0))
        repo.record_ab_metric({
            "prompt_name": name, "arm": _ab_arm(name, sid, b_pct), "session_id": sid,
            "helpful": review.rating is ReviewRating.HELPFUL,
            "error_categories": [c.value for c in review.error_categories],
        })


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


# ── Goal 9: offline regression-eval harness (real engine behind the pipeline) ─────
class EvalRequest(BaseModel):
    candidate_prompt: str | None = None
    dataset: str = "multispeaker@v1"
    prompt_name: str = "relationship"


@app.post("/admin/improvements/{item_id}/eval")
def run_improvement_eval(item_id: str, req: EvalRequest, principal: Principal = Depends(get_principal)) -> dict:
    """Run the golden dataset (optionally with a candidate prompt) and store the scores on
    the improvement item. Pure offline — the candidate is never deployed here (Goal 9)."""
    _require_role(principal, Role.ADMIN)
    repo = get_repo()
    if item_id not in repo.improvements:
        raise HTTPException(status_code=404, detail="unknown improvement item")
    from app.eval.runner import run_eval

    try:
        result = run_eval(
            req.dataset, candidate_prompt=req.candidate_prompt,
            prompt_name=req.prompt_name, llm=get_llm(get_settings()),
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"unknown dataset '{req.dataset}'")
    repo.set_improvement_eval(item_id, result, regression_test_id=req.dataset)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="run_eval", resource="improvement",
        detail=f"{item_id}:{req.dataset}:attribution={result['attribution']}",
    ))
    return result


@app.get("/admin/improvements/{item_id}/eval")
def get_improvement_eval(item_id: str, principal: Principal = Depends(get_principal)) -> dict:
    _require_role(principal, Role.ADMIN, Role.AUDITOR)
    repo = get_repo()
    if item_id not in repo.improvements:
        raise HTTPException(status_code=404, detail="unknown improvement item")
    return repo.improvements[item_id].eval_results


# ── Goal 13: prompt A/B (flag-routed candidate versions + outcome metrics) ────────
class AbConfigRequest(BaseModel):
    enabled: bool = True
    b_version_id: str | None = None
    b_pct: int = 0  # percent of consults routed to the candidate (arm B)


@app.post("/admin/prompts/{name}/ab")
def set_prompt_ab(name: str, req: AbConfigRequest, principal: Principal = Depends(get_principal)) -> dict:
    _require_role(principal, Role.ADMIN)
    flag = get_repo().set_flag(
        f"prompt.{name}.ab", req.enabled,
        {"b_version_id": req.b_version_id, "b_pct": max(0, min(100, req.b_pct))},
    )
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="set_prompt_ab", resource="feature_flag",
        detail=f"{name}:{req.b_pct}%:{'on' if req.enabled else 'off'}",
    ))
    return flag


@app.get("/admin/prompts/{name}/ab/metrics")
def get_prompt_ab_metrics(name: str, principal: Principal = Depends(get_principal)) -> dict:
    _require_role(principal, Role.ADMIN, Role.AUDITOR)
    metrics = get_repo().list_ab_metrics(prompt_name=name)
    arms: dict[str, dict] = {}
    for arm in ("a", "b"):
        rows = [m for m in metrics if m.get("arm") == arm]
        n = len(rows)
        helpful = sum(1 for m in rows if m.get("helpful"))
        arms[arm] = {
            "n": n, "helpful": helpful, "needs_improvement": n - helpful,
            "needs_improvement_rate": round((n - helpful) / n, 3) if n else 0.0,
        }
    return {"prompt_name": name, "arms": arms, "total": len(metrics)}


# ── Goals 4/12/13: admin error & latency analytics ───────────────────────────────
@app.get("/admin/analytics/errors")
def analytics_errors(principal: Principal = Depends(get_principal)) -> dict:
    """Aggregate doctor feedback for the admin analytics tab (error categories, ratings,
    inference-mode + confidence-band mix). Reads persisted reviews — no PHI."""
    _require_role(principal, Role.ADMIN, Role.AUDITOR)
    reviews = get_repo().list_reviews()
    by_category: dict[str, int] = {}
    by_rating: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    for r in reviews:
        by_rating[r.rating.value] = by_rating.get(r.rating.value, 0) + 1
        for c in r.error_categories:
            by_category[c.value] = by_category.get(c.value, 0) + 1
        if r.inference_mode:
            by_mode[r.inference_mode.value] = by_mode.get(r.inference_mode.value, 0) + 1
    return {
        "total_reviews": len(reviews),
        "by_error_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "by_rating": by_rating,
        "by_inference_mode": by_mode,
    }


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


@app.get("/admin/analytics/latency")
def analytics_latency(principal: Principal = Depends(get_principal)) -> dict:
    """Per-stage latency p50/p95 from recorded telemetry (Goal 12)."""
    _require_role(principal, Role.ADMIN, Role.AUDITOR)
    rows = get_repo().list_stage_latencies()
    by_stage: dict[str, list[int]] = {}
    for r in rows:
        by_stage.setdefault(r.get("stage", "unknown"), []).append(int(r.get("latency_ms", 0)))
    stages = {
        stage: {"n": len(ms), "p50_ms": _percentile(ms, 50), "p95_ms": _percentile(ms, 95)}
        for stage, ms in by_stage.items()
    }
    return {"stages": stages, "total": len(rows)}


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
    if pv.active:
        invalidate_prompts()  # a freshly-activated version must drive the pipeline now
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
    invalidate_prompts()  # the pipeline reads active prompts via PromptProvider's cache
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
    store, session = _load_session(sid, principal)
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
    store, session = _load_session(sid, principal)
    if session.note is None:
        raise HTTPException(status_code=409, detail="no note to edit yet")
    known = {s.section_id for s in session.note.sections}
    repo = get_repo()
    repo.drop_undone_edits(sid)  # applying a new edit starts a fresh branch (clears redo)
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


def _apply_section_text(note, section_id: str, text: str) -> bool:
    for section in note.sections:
        if section.section_id == section_id:
            section.content_text = text
            section.empty = not (text or "").strip()
            return True
    return False


def _undo_redo(sid: str, principal: Principal, *, redo: bool) -> dict:
    _check(principal, Permission.EDIT_NOTE)
    store, session = _load_session(sid, principal)
    if session.note is None:
        raise HTTPException(status_code=409, detail="no note to edit yet")
    repo = get_repo()
    edits = repo.list_edits(sid)
    if redo:
        # Re-apply the earliest undone edit (LIFO relative to the undo order).
        target = next((e for e in edits if e.get("undone")), None)
        if target is None:
            raise HTTPException(status_code=409, detail="nothing to redo")
        _apply_section_text(session.note, target["section_id"], target.get("after", ""))
        repo.set_edit_undone(sid, target["seq"], False)
    else:
        # Revert the most recent applied, not-yet-undone edit.
        target = next((e for e in reversed(edits)
                       if e.get("applied") and not e.get("undone")), None)
        if target is None:
            raise HTTPException(status_code=409, detail="nothing to undo")
        _apply_section_text(session.note, target["section_id"], target.get("before", ""))
        repo.set_edit_undone(sid, target["seq"], True)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="ai_edit_redo" if redo else "ai_edit_undo",
        resource="note", session_id=sid, phi_accessed=True, detail=f"seq={target['seq']}",
    ))
    return {"session_id": sid, "state": session.state.value, "seq": target["seq"],
            "note": session.note.model_dump(mode="json")}


@app.post("/sessions/{sid}/ai-edit/undo")
def ai_edit_undo(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    """Undo the most recent applied AI edit, restoring the prior section text (Goal 11)."""
    return _undo_redo(sid, principal, redo=False)


@app.post("/sessions/{sid}/ai-edit/redo")
def ai_edit_redo(sid: str, principal: Principal = Depends(get_principal)) -> dict:
    """Redo the most recently undone AI edit (Goal 11)."""
    return _undo_redo(sid, principal, redo=True)


# ── AI editor for the structured tabs (Extraction, Risk) ─────────────────────
# Preview returns human-readable before/after `changes` for the UI plus the full
# `proposed` object the apply route needs. Apply reuses the deterministic save paths
# (extraction → rebuild_from_extraction; risk → re-score) so nothing is trusted blindly.

def _flatten_extraction(extraction: ClinicalExtraction) -> dict[str, str]:
    """Render each extraction field to a readable string for diffing/preview."""
    out: dict[str, str] = {}
    for key, val in extraction.to_data_map().items():
        if val is None or val == [] or val == {}:
            text = ""
        elif isinstance(val, str):
            text = val
        elif isinstance(val, list):
            text = "\n".join(
                v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in val
            )
        elif isinstance(val, dict):
            text = "\n".join(f"{k}: {v}" for k, v in val.items())
        else:
            text = str(val)
        out[key] = text
    return out


def _extraction_changes(before: ClinicalExtraction, after: ClinicalExtraction) -> list[dict]:
    b, a = _flatten_extraction(before), _flatten_extraction(after)
    return [
        {"section_id": key, "before": b.get(key, ""), "after": a.get(key, "")}
        for key in a
        if a.get(key, "") != b.get(key, "")
    ]


def _render_markers(markers: list[RiskMarker]) -> str:
    return "\n".join(f"[{m.severity.value}] {m.type.value}: {m.message}" for m in markers)


class AiEditProposalRequest(BaseModel):
    instruction: str


def _require_session_llm(sid: str, principal: Principal):
    """Shared guard for the structured AI-edit routes (feature flag + ownership)."""
    if not get_settings().ai_edit_enabled:
        raise HTTPException(status_code=403, detail="AI editor is disabled")
    return _load_session(sid, principal)


@app.post("/sessions/{sid}/ai-edit/extraction")
def ai_edit_extraction_preview(
    sid: str, req: AiEditProposalRequest, principal: Principal = Depends(get_principal)
) -> dict:
    """Preview an AI edit of the structured extraction from a natural-language instruction."""
    _check(principal, Permission.EDIT_NOTE)
    _store, session = _require_session_llm(sid, principal)
    if session.extraction is None:
        raise HTTPException(status_code=409, detail="no extraction to edit yet")
    try:
        proposed = propose_extraction_edit(session.extraction, req.instruction, get_llm(get_settings()))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"AI edit unavailable: {str(exc)[:200]}")
    return {
        "instruction": req.instruction,
        "changes": _extraction_changes(session.extraction, proposed),
        "proposed": proposed.model_dump(mode="json"),
    }


class AiEditExtractionApplyRequest(BaseModel):
    instruction: str = ""
    proposed: ClinicalExtraction


@app.post("/sessions/{sid}/ai-edit/extraction/apply")
def ai_edit_extraction_apply(
    sid: str, req: AiEditExtractionApplyRequest, principal: Principal = Depends(get_principal)
) -> dict:
    """Apply an approved AI extraction edit, re-grounding + re-rendering the note (no LLM call)."""
    _check(principal, Permission.EDIT_NOTE)
    store, session = _require_session_llm(sid, principal)
    if session.extraction is None:
        raise HTTPException(status_code=409, detail="no extraction to edit yet")
    extraction = req.proposed
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
        actor_id=principal.id, action="ai_edit_extraction", resource="extraction",
        session_id=sid, phi_accessed=True, detail=req.instruction[:120],
    ))
    return {
        "session_id": sid, "state": session.state.value,
        "extraction": result.extraction.model_dump(mode="json"),
        "note": result.note.model_dump(mode="json"),
        "grounding": result.grounding.model_dump(mode="json"),
    }


@app.post("/sessions/{sid}/ai-edit/risk")
def ai_edit_risk_preview(
    sid: str, req: AiEditProposalRequest, principal: Principal = Depends(get_principal)
) -> dict:
    """Preview an AI edit of the risk markers from a natural-language instruction."""
    _check(principal, Permission.EDIT_NOTE)
    _store, session = _require_session_llm(sid, principal)
    if session.risk is None:
        raise HTTPException(status_code=409, detail="no risk assessment to edit yet")
    try:
        markers = propose_risk_edit(session.risk, req.instruction, get_llm(get_settings()))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"AI edit unavailable: {str(exc)[:200]}")
    return {
        "instruction": req.instruction,
        "changes": [{
            "section_id": "risk_markers",
            "before": _render_markers(session.risk.markers),
            "after": _render_markers(markers),
        }],
        "proposed": [m.model_dump(mode="json") for m in markers],
    }


class AiEditRiskApplyRequest(BaseModel):
    instruction: str = ""
    proposed: list[RiskMarker] = []


@app.post("/sessions/{sid}/ai-edit/risk/apply")
def ai_edit_risk_apply(
    sid: str, req: AiEditRiskApplyRequest, principal: Principal = Depends(get_principal)
) -> dict:
    """Apply approved AI risk-marker edits and re-score (never touches note/extraction)."""
    _check(principal, Permission.EDIT_NOTE)
    store, session = _require_session_llm(sid, principal)
    if session.risk is None:
        raise HTTPException(status_code=409, detail="no risk assessment to edit yet")
    session.risk = RiskAssessment(
        session_id=sid, markers=req.proposed, score=aggregate_score(req.proposed),
    )
    _advance_to_edited(session)
    store.persist(session)
    get_audit_log().record(AuditEvent(
        actor_id=principal.id, action="ai_edit_risk", resource="risk",
        session_id=sid, phi_accessed=True, detail=req.instruction[:120],
    ))
    return {"session_id": sid, "state": session.state.value, "risk": session.risk.model_dump(mode="json")}


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
    store, session = _load_session(sid, principal)
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
def _ws_principal(websocket: WebSocket, settings) -> Principal:
    """Authenticate a WebSocket the same way as REST, but read credentials from the
    query string (browsers can't set headers on a WS handshake).

    dev mode:  ?user_id=&role=   (header scaffold, unauthenticated — local only)
    jwt mode:  ?token=<bearer>   (verified; rejected on failure)
    """
    qp = websocket.query_params
    if settings.auth_mode == "jwt":
        token = qp.get("token", "")
        return principal_from(settings, authorization=f"Bearer {token}",
                              x_user_id="", x_role="doctor")
    return principal_from(settings, authorization=None,
                          x_user_id=qp.get("user_id", "dev-doctor"),
                          x_role=qp.get("role", "doctor"))


@app.websocket("/ws/consultation")
async def ws_consultation(websocket: WebSocket) -> None:
    settings = get_settings()
    try:
        principal = _ws_principal(websocket, settings)
        require_permission(principal, Permission.VIEW_TRANSCRIPT)
    except (AuthError, AccessDenied, ValueError) as exc:
        await websocket.close(code=4401)  # 4401: application-level "unauthorized"
        logger.warning("ws auth rejected: %s", exc)
        try:  # surface in the admin console like the REST auth failures
            get_logging_service().log_error(
                endpoint="/ws/consultation", error_type="auth_ws_rejected",
                error_message=str(exc), severity=getattr(exc, "severity", "warning"), source="auth",
            )
        except Exception:  # noqa: BLE001
            pass
        return
    logger.info("ws connected: user=%s role=%s", principal.id, principal.role.value)
    await consultation_ws(websocket, get_store(), settings, principal)
