"""Central logging configuration.

Python's implicit default level is WARNING, which silently hid every ``logger.info``
/ ``logger.debug`` line in this app. ``setup_logging`` fixes that: it configures the
root logger once, at the level from ``SCRIBE_LOG_LEVEL`` (default INFO), with a
consistent format that carries the current request-id.

The request-id is stored in a ``contextvars.ContextVar`` set by the observability
middleware (one per request). A logging filter injects it into every record, so a
log line emitted anywhere during a request can be correlated by ``rid=…``.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys

from app.config import Settings

# Set per-request by the observability middleware; "-" outside any request.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_configured = False


class _RequestIdFilter(logging.Filter):
    """Attach the current request-id to every record as ``record.rid``."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.rid = request_id_ctx.get()
        return True


class _JsonFormatter(logging.Formatter):
    """One JSON object per line — for log aggregators (Loki, CloudWatch, etc.)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "rid": getattr(record, "rid", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(settings: Settings) -> None:
    """Configure the root logger. Idempotent — safe to call more than once."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.strip().upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if settings.log_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s [rid=%(rid)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn ships its own handlers; route them through ours so request-id and format
    # are consistent and the level is honoured.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    _configured = True
    logging.getLogger("svaani.logging").info(
        "logging configured: level=%s json=%s", settings.log_level.upper(), settings.log_json
    )
