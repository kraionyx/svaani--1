"""Append-only audit log.

Every PHI access and state transition is recorded. The scaffold writes newline-
delimited JSON to a local file; in production point this at an append-only/WORM
sink (e.g. a Kafka ``audit.events`` topic, as the Svaani platform does).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import Settings, get_settings


class AuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor_id: str
    action: str
    resource: str
    session_id: str | None = None
    phi_accessed: bool = False
    detail: str | None = None


class AuditLog:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> AuditEvent:
        self._events.append(event)
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(event.model_dump_json() + "\n")
        except OSError:
            pass  # never let audit-sink failure break the request path
        return event

    def events(self) -> list[AuditEvent]:
        return list(self._events)


_audit: AuditLog | None = None


def get_audit_log(settings: Settings | None = None) -> AuditLog:
    global _audit
    if _audit is None:
        settings = settings or get_settings()
        _audit = AuditLog(settings.audit_log_path)
    return _audit
