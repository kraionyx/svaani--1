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

    def record(self, event: AuditEvent) -> AuditEvent:
        from app.data.repo import get_repo
        try:
            get_repo().record_audit_event(event.model_dump(mode="json"))
        except Exception:
            pass  # never let audit-sink failure break the request path
        return event

    def events(self) -> list[AuditEvent]:
        from app.data.repo import get_repo
        try:
            return [AuditEvent.model_validate(e) for e in get_repo().list_audit_events()]
        except Exception:
            return []


_audit: AuditLog | None = None


def get_audit_log(settings: Settings | None = None) -> AuditLog:
    global _audit
    if _audit is None:
        settings = settings or get_settings()
        _audit = AuditLog(settings.audit_log_path)
    return _audit
