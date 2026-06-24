"""Observability: request-id propagation, access logging, Prometheus, and Supabase analytics.

Every HTTP request is logged to Supabase via the non-blocking logging service.
Errors (status >= 500) are additionally recorded to error_logs.
"""
from __future__ import annotations

import logging
import re
import time
import traceback
import uuid

from fastapi import FastAPI, Request, Response

from app.config import Settings
from app.logging_config import request_id_ctx

logger = logging.getLogger("svaani.access")
_ID_SEG = re.compile(r"^(sess-[0-9a-f]+|[0-9a-f]{8,}|\d+)$", re.IGNORECASE)

# Endpoints too noisy / low-value to log to Supabase (still logged to stdout).
_SKIP_SUPABASE = {"/health", "/metrics", "/admin1/api/errors/frontend"}


def _apply_security_headers(response: Response, settings: Settings) -> None:
    """Conservative security headers safe for both the API and the bundled SPA."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-XSS-Protection", "0")
    # HSTS only outside development (it pins clients to HTTPS for a year — never on http).
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )


def _route(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    parts = [(":id" if _ID_SEG.match(p) else p) for p in request.url.path.split("/")]
    return "/".join(parts) or "/"


def setup_observability(app: FastAPI, settings: Settings) -> None:
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
        reqs = Counter("svaani_requests_total", "HTTP requests", ["method", "path", "status"])
        lat = Histogram("svaani_request_seconds", "HTTP request latency", ["method", "path"])
        have_prom = True
    except ImportError:
        have_prom = False

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        # Make the request-id available to every log line emitted during this request.
        token = request_id_ctx.set(rid)
        t0 = time.perf_counter()
        exc_info = None
        response = None
        try:
            response = await call_next(request)
        except Exception as exc:
            exc_info = exc
            logger.exception("unhandled error rid=%s %s %s", rid, request.method, request.url.path)
            raise
        finally:
            dt = time.perf_counter() - t0
            duration_ms = int(dt * 1000)
            path = _route(request)
            status = response.status_code if response else 500
            success = status < 400
            # Prefer the auth-resolved identity (set by get_principal) over the raw header:
            # in jwt mode the browser sends a Bearer token, not X-User-Id, so the header alone
            # would log every authenticated request as 'anonymous'.
            user_id = getattr(request.state, "user_id", None) or request.headers.get("x-user-id", "anonymous")

            if have_prom:
                reqs.labels(request.method, path, str(status)).inc()
                lat.labels(request.method, path).observe(dt)

            if response:
                response.headers["X-Request-ID"] = rid
                if settings.security_headers:
                    _apply_security_headers(response, settings)

            logger.info("rid=%s %s %s -> %s (%.0fms)",
                        rid, request.method, path, status, dt * 1000)

            request_id_ctx.reset(token)

            # Non-blocking write to Supabase (skips noisy health/metrics endpoints).
            if path not in _SKIP_SUPABASE:
                try:
                    from app.logging_service import get_logging_service
                    svc = get_logging_service()
                    svc.log_request(
                        request_id=rid, user_id=user_id,
                        method=request.method, endpoint=path,
                        status_code=status, duration_ms=duration_ms,
                        success=success,
                        metadata={"query": str(request.query_params) or None},
                    )
                    if status >= 500 or exc_info is not None:
                        svc.log_error(
                            request_id=rid, user_id=user_id, endpoint=path,
                            error_type=type(exc_info).__name__ if exc_info else "HTTPError",
                            error_message=str(exc_info) if exc_info else f"HTTP {status}",
                            stack_trace=traceback.format_exc() if exc_info else None,
                            severity="critical" if status >= 500 else "error",
                        )
                except Exception:
                    pass  # logging must never break the request path

        return response

    if settings.enable_metrics:
        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            if not have_prom:
                return Response("prometheus_client not installed", status_code=501,
                                media_type="text/plain")
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
