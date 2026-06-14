"""In-memory session store (scaffold).

Swap for a persistent, encrypted store in production (PHI fields via
``app.security.crypto.FieldCipher``). Kept deliberately tiny so the wiring is clear.
"""
from __future__ import annotations

from app.pipeline.orchestrator import PipelineResult
from app.schemas.session import ConsultationSession


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, ConsultationSession] = {}
        self._results: dict[str, PipelineResult] = {}

    def create(self, session: ConsultationSession) -> ConsultationSession:
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> ConsultationSession:
        return self._sessions[session_id]

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def set_result(self, session_id: str, result: PipelineResult) -> None:
        self._results[session_id] = result

    def get_result(self, session_id: str) -> PipelineResult | None:
        return self._results.get(session_id)

    def list(self) -> list[ConsultationSession]:
        return list(self._sessions.values())

    def persist(self, session: ConsultationSession) -> None:
        """Write-through hook after a session is mutated. No-op for the in-memory store
        (the object is shared); the SQLite backend overrides this to save durably."""


_store: SessionStore | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        from app.config import get_settings

        if get_settings().store_backend == "sqlite":
            from app.store_sql import SqlSessionStore

            _store = SqlSessionStore(get_settings())
        else:
            _store = SessionStore()
    return _store
