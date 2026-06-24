"""Internal admin dashboard API — served under /admin1/api/*.

Two data sources, unified behind one token-protected router:

* **New observability metrics** (requests, errors, AI usage, doctors, feedback) come
  from the Supabase logging tables via ``app.logging_service`` — written non-blocking by
  the request middleware and the LLM layer.
* **Old operational metrics** (prompt/model versions, feature flags, doctor reviews,
  improvement pipeline, A/B metrics) come from the operational ``Repository``
  (``app.data.repo``) — the same store the main app uses.

Auth: a single ``X-Admin-Token`` header compared (constant-time) against the configured
``SCRIBE_ADMIN_PASSWORD``. ``POST /auth`` exchanges the password for that token and is
rate-limited per IP against brute force. This is intentionally simple for an internal,
unlinked dashboard — swap for JWT/OIDC if it is ever exposed beyond a trusted network.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import json
from typing import Optional


from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import get_settings
from app.data.repo import get_repo
from app.logging_service import get_logging_service
from app.security.audit import AuditEvent, get_audit_log
from app.security.ratelimit import RateLimiter, client_ip
from app.schemas.review import AdminStatus, PromptVersion

router = APIRouter(prefix="/admin1/api", tags=["admin"])


# ── Auth ─────────────────────────────────────────────────────────────────────
def _token_hash() -> str:
    return hashlib.sha256(get_settings().admin_password.encode()).hexdigest()


def _require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="X-Admin-Token required")
    if not hmac.compare_digest(hashlib.sha256(x_admin_token.encode()).hexdigest(), _token_hash()):
        raise HTTPException(status_code=403, detail="invalid admin token")


_auth_limiter = RateLimiter(
    get_settings().admin_auth_rate_limit, get_settings().admin_auth_rate_window_s
)


class AuthRequest(BaseModel):
    password: str


@router.post("/auth", include_in_schema=False)
def admin_auth(req: AuthRequest, request: Request) -> dict:
    ip = client_ip(request)
    if not _auth_limiter.check(ip):
        raise HTTPException(status_code=429, detail="too many attempts — try again later")
    if not hmac.compare_digest(
        hashlib.sha256(req.password.encode()).hexdigest(), _token_hash()
    ):
        return {"ok": False}
    _auth_limiter.reset(ip)
    return {"ok": True, "token": req.password}


# ── New observability metrics (Supabase logging tables) ──────────────────────
@router.get("/overview", include_in_schema=False)
def admin_overview(_: None = Depends(_require_admin)) -> dict:
    return get_logging_service().query_overview()


@router.get("/health", include_in_schema=False)
def admin_health(_: None = Depends(_require_admin)) -> dict:
    return get_logging_service().query_system_health()


@router.get("/doctors", include_in_schema=False)
def admin_doctors(
    page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), search: str = "",
    _: None = Depends(_require_admin),
) -> dict:
    return get_logging_service().query_doctors(page=page, limit=limit, search=search)


@router.get("/logs", include_in_schema=False)
def admin_logs(
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
    user_id: str = "", endpoint: str = "", status: str = "", from_dt: str = "", to_dt: str = "",
    _: None = Depends(_require_admin),
) -> dict:
    return get_logging_service().query_logs(
        page=page, limit=limit, user_id=user_id, endpoint=endpoint,
        status=status, from_dt=from_dt, to_dt=to_dt,
    )


@router.get("/errors", include_in_schema=False)
def admin_errors(
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
    severity: str = "", source: str = "", from_dt: str = "", to_dt: str = "",
    _: None = Depends(_require_admin),
) -> dict:
    return get_logging_service().query_errors(
        page=page, limit=limit, severity=severity, source=source, from_dt=from_dt, to_dt=to_dt,
    )


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


@router.get("/ai-analytics", include_in_schema=False)
def admin_ai_analytics(
    from_dt: str = "", to_dt: str = "", _: None = Depends(_require_admin),
) -> dict:
    data = get_logging_service().query_ai_analytics(from_dt=from_dt, to_dt=to_dt)
    # Merge the operational per-stage pipeline latencies (old metric) so the AI tab can
    # show the deterministic stage breakdown alongside the LLM-call analytics.
    by_stage: dict[str, list[int]] = {}
    for row in get_repo().list_stage_latencies():
        by_stage.setdefault(row.get("stage", "unknown"), []).append(int(row.get("latency_ms", 0)))
    data["latency_stages"] = {
        stage: {"n": len(ms), "p50_ms": _percentile(ms, 50), "p95_ms": _percentile(ms, 95)}
        for stage, ms in by_stage.items()
    }
    return data


@router.get("/feedback", include_in_schema=False)
def admin_feedback(
    page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100),
    _: None = Depends(_require_admin),
) -> dict:
    return get_logging_service().query_feedback(page=page, limit=limit)


# ── Global AI Chat Assistant ─────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]

@router.post("/chat", include_in_schema=False)
def admin_chat(req: ChatRequest, _: None = Depends(_require_admin)) -> dict:
    svc = get_logging_service()
    
    try:
        overview = svc.query_overview()
        health = svc.query_system_health()
        recent_errs = overview.get("recent_errors", [])
        kpis = overview.get("kpis", {})
        
        ctx = "LIVE SYSTEM CONTEXT:\n"
        ctx += f"- Requests (24h): {kpis.get('total_requests_24h', 0)}\n"
        ctx += f"- Error Rate: {kpis.get('error_rate_pct', 0)}%\n"
        ctx += f"- Avg Latency: {kpis.get('avg_latency_ms', 0)}ms\n"
        ctx += f"- AI Calls (24h): {kpis.get('ai_calls_24h', 0)}\n\n"
        
        ctx += "RECENT ERRORS SUMMARY:\n"
        for e in recent_errs[:8]:
            ctx += f"- {e.get('severity', 'error')} ({e.get('source')}): {e.get('error_type')} - {e.get('error_message')}\n"
            
        ctx += "\nSLOWEST ENDPOINTS:\n"
        for ep in health.get("slowest_endpoints", [])[:5]:
            ctx += f"- {ep.get('endpoint')}: {ep.get('avg_ms')}ms avg\n"

        # Dynamically inject the most recent detailed errors with their stack traces and AI logs
        try:
            err_data = svc.query_errors(limit=5)
            detailed_errors = err_data.get("errors", [])
            if detailed_errors:
                ctx += "\nDETAILED RECENT ERRORS (WITH STACK TRACES):\n"
                for idx, e in enumerate(detailed_errors):
                    ctx += f"[{idx+1}] ID: {e.get('id')}\n"
                    ctx += f"    Time: {e.get('created_at')}\n"
                    ctx += f"    Type: {e.get('error_type')} | Message: {e.get('error_message')}\n"
                    ctx += f"    Source: {e.get('source')} | Endpoint: {e.get('endpoint')} | Severity: {e.get('severity')}\n"
                    if e.get('stack_trace'):
                        st_lines = e.get('stack_trace', '').split('\n')[:15]
                        ctx += f"    Stack Trace excerpt:\n      " + "\n      ".join(st_lines) + "\n"
                    if e.get('ai_analysis'):
                        ctx += f"    Pre-triaged Agent Analysis: {e.get('ai_analysis')}\n"
                    ctx += "\n"
        except Exception as e_err:
            ctx += f"\nDetailed error logs query failed: {str(e_err)}\n"

        # Dynamically inject recent request logs
        try:
            log_data = svc.query_logs(limit=8)
            detailed_logs = log_data.get("logs", [])
            if detailed_logs:
                ctx += "\nRECENT APPLICATION LOGS:\n"
                for l in detailed_logs:
                    ctx += f"- [{l.get('created_at')}] {l.get('method')} {l.get('endpoint')} | Status: {l.get('status_code')} | Duration: {l.get('duration_ms')}ms | User: {l.get('user_id')}\n"
        except Exception as e_log:
            ctx += f"\nDetailed request logs query failed: {str(e_log)}\n"
            
    except Exception:
        ctx = "Live system context is currently unavailable."

    sys_prompt = {
        "role": "system",
        "content": (
            "You are the Svaani Admin Console AI Assistant, an expert DevOps and debugging agent. "
            "You help the developer monitor the system, debug errors, and answer questions. "
            "You have access to the following live metrics, request logs, and error stack traces from the database:\n\n"
            f"{ctx}\n\n"
            "Keep your answers concise, technical, and directly address the developer's question. Use markdown formatting."
        )
    }
    
    messages = [sys_prompt] + [m.model_dump() for m in req.messages]
    
    try:
        agent_key = get_settings().agent_api_key
        if not agent_key:
            raise HTTPException(status_code=500, detail="SCRIBE_AGENT_API_KEY is not configured.")
        
        from sarvamai import SarvamAI
        client = SarvamAI(api_subscription_key=agent_key)
        response = client.chat.completions(
            model="sarvam-105b",
            messages=messages,
            temperature=0.0
        )
        return {"response": response.choices[0].message.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Agent failed: {str(e)}")


# ── Old operational metrics (Repository) ─────────────────────────────────────
@router.get("/prompts", include_in_schema=False)
def admin_list_prompts(name: str = "", _: None = Depends(_require_admin)) -> list[dict]:
    return [p.model_dump(mode="json") for p in get_repo().list_prompts(name=name or None)]


class NewPromptRequest(BaseModel):
    name: str
    content: str
    activate: bool = False


@router.post("/prompts", include_in_schema=False)
def admin_create_prompt(req: NewPromptRequest, _: None = Depends(_require_admin)) -> dict:
    import uuid

    from app.pipeline.prompt_provider import invalidate_prompts

    repo = get_repo()
    existing = repo.list_prompts(name=req.name)
    version = (max((p.version for p in existing), default=0)) + 1
    pv = PromptVersion(
        id=f"pv-{uuid.uuid4().hex[:12]}", name=req.name, version=version,
        content=req.content, active=req.activate, created_by="admin",
    )
    repo.add_prompt_version(pv)
    if pv.active:
        invalidate_prompts()
    get_audit_log().record(AuditEvent(
        actor_id="admin", action="create_prompt", resource="prompt", detail=f"{pv.name}@{pv.version}",
    ))
    return pv.model_dump(mode="json")


@router.post("/prompts/{prompt_id}/activate", include_in_schema=False)
def admin_activate_prompt(prompt_id: str, _: None = Depends(_require_admin)) -> dict:
    from app.pipeline.prompt_provider import invalidate_prompts

    try:
        pv = get_repo().activate_prompt(prompt_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown prompt version")
    invalidate_prompts()
    get_audit_log().record(AuditEvent(
        actor_id="admin", action="activate_prompt", resource="prompt", detail=f"{pv.name}@{pv.version}",
    ))
    return pv.model_dump(mode="json")


@router.get("/models", include_in_schema=False)
def admin_list_models(_: None = Depends(_require_admin)) -> list[dict]:
    return [m.model_dump(mode="json") for m in get_repo().list_models()]


@router.get("/feature-flags", include_in_schema=False)
def admin_get_flags(_: None = Depends(_require_admin)) -> dict:
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


@router.post("/feature-flags", include_in_schema=False)
def admin_set_flag(req: FlagRequest, _: None = Depends(_require_admin)) -> dict:
    return get_repo().set_flag(req.key, req.enabled, req.value)


@router.get("/admin/reviews", include_in_schema=False)
def admin_reviews(_: None = Depends(_require_admin)) -> list[dict]:
    """Flattened admin-review queue (matches the dashboard's Reviews table)."""
    out: list[dict] = []
    for entry in get_repo().list_admin_reviews():
        ar = entry["admin_review"]
        rv = entry.get("review") or {}
        out.append({
            "id": ar["id"],
            "session_id": rv.get("session_id"),
            "rating": rv.get("rating"),
            "error_categories": rv.get("error_categories", []),
            "admin_status": ar.get("status"),
            "comment": rv.get("comment"),
            "created_at": ar.get("created_at"),
        })
    return out


class ReviewUpdate(BaseModel):
    status: str


@router.patch("/admin/reviews/{admin_id}", include_in_schema=False)
def admin_update_review(admin_id: str, req: ReviewUpdate, _: None = Depends(_require_admin)) -> dict:
    try:
        ar = get_repo().update_admin_review(admin_id, status=AdminStatus(req.status))
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown admin review")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid status '{req.status}'")
    get_audit_log().record(AuditEvent(
        actor_id="admin", action="admin_triage", resource="admin_review",
        detail=f"{admin_id}:{req.status}",
    ))
    return ar.model_dump(mode="json")


@router.get("/admin/improvements", include_in_schema=False)
def admin_improvements(_: None = Depends(_require_admin)) -> list[dict]:
    out = []
    for item in get_repo().list_improvements():
        d = item.model_dump(mode="json")
        d.setdefault("source_review_id", d.get("admin_review_id"))
        out.append(d)
    return out


@router.get("/admin/prompts/{name}/ab/metrics", include_in_schema=False)
def admin_ab_metrics(name: str, _: None = Depends(_require_admin)) -> dict:
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


# ── Ingestion (no admin token — called by the browser / main app) ────────────
class FrontendError(BaseModel):
    error_type: str
    error_message: str
    stack_trace: Optional[str] = None
    endpoint: Optional[str] = None
    user_id: Optional[str] = None
    browser_info: dict = {}


@router.post("/errors/frontend", include_in_schema=False)
def ingest_frontend_error(req: FrontendError, request: Request) -> dict:
    info = {**req.browser_info, "user_agent": request.headers.get("user-agent", "")}
    get_logging_service().log_error(
        user_id=req.user_id, endpoint=req.endpoint, error_type=req.error_type,
        error_message=req.error_message[:2000], stack_trace=req.stack_trace,
        severity="error", source="frontend", browser_info=info,
    )
    return {"ok": True}


class FeedbackRequest(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    rating: Optional[int] = None
    feedback_text: Optional[str] = None
    feature: Optional[str] = None


@router.post("/feedback", include_in_schema=False)
def submit_feedback(req: FeedbackRequest) -> dict:
    get_logging_service().log_feedback(
        user_id=req.user_id, session_id=req.session_id, rating=req.rating,
        feedback_text=req.feedback_text, feature=req.feature,
    )
    return {"ok": True}
