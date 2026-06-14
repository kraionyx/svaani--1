"""Observability: request-id propagation, access logging, and Prometheus metrics.

Wired in ``app.main``. ``prometheus_client`` is imported lazily — if it isn't installed
the middleware still adds request IDs and access logs, and ``/metrics`` reports that the
dependency is missing rather than failing to boot.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import FastAPI, Request, Response

from app.config import Settings

logger = logging.getLogger("svaani.access")
_ID_SEG = re.compile(r"^(sess-[0-9a-f]+|[0-9a-f]{8,}|\d+)$", re.IGNORECASE)


def _route(request: Request) -> str:
    """Low-cardinality path label: prefer the matched route template, else normalize ids."""
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
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled error rid=%s %s %s", rid, request.method, request.url.path)
            raise
        dt = time.perf_counter() - t0
        path = _route(request)
        if have_prom:
            reqs.labels(request.method, path, str(response.status_code)).inc()
            lat.labels(request.method, path).observe(dt)
        response.headers["X-Request-ID"] = rid
        logger.info("rid=%s %s %s -> %s (%.0fms)", rid, request.method, path, response.status_code, dt * 1000)
        return response

    if settings.enable_metrics:
        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            if not have_prom:
                return Response("prometheus_client not installed", status_code=501, media_type="text/plain")
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
