"""Durable, PHI-encrypted SQLite session store.

A drop-in ``SessionStore`` (selected via ``SCRIBE_STORE_BACKEND=sqlite``) that survives
restarts. The whole session/result record is a PHI payload, so it is serialized to JSON
and **encrypted at rest** with the existing ``FieldCipher`` (AES-256-GCM) before being
written — the database file never holds plaintext clinical content.

Live objects are cached in memory (so mutation semantics match the in-memory store
within a run); ``create``/``set_result``/``persist`` write through to disk. On startup
the table is loaded back into the cache so prior consults are available again.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.config import Settings
from app.pipeline.orchestrator import PipelineResult
from app.schemas.session import ConsultationSession
from app.security.crypto import get_cipher
from app.store import SessionStore


class SqlSessionStore(SessionStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._cipher = get_cipher(settings)
        self._db = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "session_id TEXT PRIMARY KEY, session_enc TEXT, result_enc TEXT, updated TEXT)"
        )
        self._db.commit()
        self._load_all()

    # ── persistence helpers ──────────────────────────────────────────────────
    def _enc(self, obj: Any) -> str:
        return self._cipher.encrypt(json.dumps(obj))

    def _dec(self, token: str | None) -> Any:
        return json.loads(self._cipher.decrypt(token)) if token else None

    def _save(self, session: ConsultationSession) -> None:
        result = self._results.get(session.session_id)
        self._db.execute(
            "INSERT INTO sessions(session_id, session_enc, result_enc, updated) VALUES(?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET session_enc=excluded.session_enc, "
            "result_enc=excluded.result_enc, updated=excluded.updated",
            (
                session.session_id,
                self._enc(session.model_dump(mode="json")),
                self._enc(result.model_dump(mode="json")) if result else None,
                session.updated_at.isoformat(),
            ),
        )
        self._db.commit()

    def _load_all(self) -> None:
        for sid, s_enc, r_enc, _ in self._db.execute(
            "SELECT session_id, session_enc, result_enc, updated FROM sessions"
        ).fetchall():
            try:
                self._sessions[sid] = ConsultationSession.model_validate(self._dec(s_enc))
                if r_enc:
                    self._results[sid] = PipelineResult.model_validate(self._dec(r_enc))
            except Exception:  # noqa: BLE001 — skip a corrupt/incompatible row, keep serving
                continue

    # ── write-through overrides ────────────────────────────────────────────────
    def create(self, session: ConsultationSession) -> ConsultationSession:
        super().create(session)
        self._save(session)
        return session

    def set_result(self, session_id: str, result: PipelineResult) -> None:
        super().set_result(session_id, result)
        if session_id in self._sessions:
            self._save(self._sessions[session_id])

    def persist(self, session: ConsultationSession) -> None:
        self._save(session)

    def delete(self, session_id: str) -> None:
        """Remove a cancelled consult from the cache and the durable table."""
        super().delete(session_id)
        try:
            self._db.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            self._db.commit()
        except Exception:  # noqa: BLE001 — cancellation cleanup is best-effort
            pass

    def close(self) -> None:
        """Close the SQLite connection (called at app shutdown)."""
        try:
            self._db.close()
        except Exception:  # noqa: BLE001 — shutdown best-effort
            pass
