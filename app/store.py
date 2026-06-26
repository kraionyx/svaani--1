"""In-memory session store (scaffold).

Swap for a persistent, encrypted store in production (PHI fields via
``app.security.crypto.FieldCipher``). Kept deliberately tiny so the wiring is clear.
"""
from __future__ import annotations

from app.pipeline.orchestrator import PipelineResult
from app.schemas.session import ConsultationSession


import threading

class SessionStore:
    def __init__(self, max_size: int = 1024) -> None:
        self._sessions: dict[str, ConsultationSession] = {}
        self._results: dict[str, PipelineResult] = {}
        self._max_size = max_size
        self._lock = threading.Lock()

    def create(self, session: ConsultationSession) -> ConsultationSession:
        with self._lock:
            self._prune_if_needed()
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> ConsultationSession:
        with self._lock:
            return self._sessions[session_id]

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    def set_result(self, session_id: str, result: PipelineResult) -> None:
        with self._lock:
            self._prune_if_needed()
            self._results[session_id] = result

    def _prune_if_needed(self) -> None:
        # Caller must hold _lock
        if len(self._sessions) > self._max_size:
            # Drop the oldest half
            keys_to_drop = list(self._sessions.keys())[: self._max_size // 2]
            for k in keys_to_drop:
                self._sessions.pop(k, None)
                self._results.pop(k, None)

    def delete(self, session_id: str) -> None:
        """Discard a session and any result (used when a consult is cancelled). Idempotent;
        durable backends override to also remove the persisted row."""
        with self._lock:
            self._sessions.pop(session_id, None)
            self._results.pop(session_id, None)

    def get_result(self, session_id: str) -> PipelineResult | None:
        with self._lock:
            return self._results.get(session_id)

    def list(self) -> list[ConsultationSession]:
        with self._lock:
            return list(self._sessions.values())

    @staticmethod
    def _summary(s: ConsultationSession) -> dict:
        """Lightweight, PHI-free row for a 'my consultations' list (no decryption needed)."""
        return {
            "session_id": s.session_id,
            "state": s.state.value,
            "template_id": s.template_id,
            "practitioner_id": s.practitioner_id,
            "signed_by_name": s.signed_by_name,
            "has_note": s.note is not None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }

    def list_for_practitioner(self, practitioner_id: str, limit: int = 100) -> list[dict]:
        """Return the given user's sessions (most-recent first) as PHI-free metadata.

        The in-memory and SQLite backends keep every session in the cache, so this filter
        is exact for them; the Supabase backend overrides this to query Postgres directly."""
        rows = [self._summary(s) for s in self._sessions.values()
                if s.practitioner_id == practitioner_id]
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows[:limit]

    def persist(self, session: ConsultationSession) -> None:
        """Write-through hook after a session is mutated. No-op for the in-memory store
        (the object is shared); the SQLite backend overrides this to save durably."""

    def close(self) -> None:
        """Release backing resources (connection pools). No-op for the in-memory store;
        durable backends override to close their pool at app shutdown."""


_store: SessionStore | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        from app.config import get_settings

        backend = get_settings().store_backend
        if backend == "sqlite":
            from app.store_sql import SqlSessionStore

            _store = SqlSessionStore(get_settings())
        elif backend == "supabase":
            from app.store_supabase import SupabaseSessionStore

            _store = SupabaseSessionStore(get_settings())
        else:
            _store = SessionStore()
    return _store
