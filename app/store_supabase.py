"""Durable, PHI-encrypted Supabase (Postgres) session store.

A drop-in ``SessionStore`` (selected via ``SCRIBE_STORE_BACKEND=supabase``) backed by
the Supabase Postgres schema in ``supabase/schema.sql``. Like ``SqlSessionStore`` it
keeps clinical content **encrypted at rest**: the whole session/result record is
serialized to JSON and encrypted with the existing ``FieldCipher`` (AES-256-GCM)
before being written to the ``session_enc`` / ``result_enc`` columns — the database
never holds plaintext PHI. Non-PHI metadata (state, template, sign-off) is written to
plain columns so the admin console / analytics can query without decrypting.

Connection is a libpq URI in ``SCRIBE_SUPABASE_DB_URL`` (prefer the Supabase **pooler**
endpoint — the small instance caps total connections). The server-side DB role (or
service_role) bypasses RLS; browsers never use this connection.

Live objects are cached in memory so mutation semantics match the in-memory store
within a run; ``create`` / ``set_result`` / ``persist`` write through to Postgres.
Sessions are loaded lazily on first ``get`` / ``exists`` (no full-table preload).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.config import Settings
from app.pipeline.orchestrator import PipelineResult
from app.schemas.session import ConsultationSession
from app.security.crypto import get_cipher
from app.store import SessionStore

logger = logging.getLogger("svaani.store")

_UPSERT = """
insert into consultations
  (session_id, patient_ref, template_id, template_version, state,
   conversation_kind, complexity_score, is_complex, inference_mode, speaker_count,
   audio_confidence, confidence_band, referenced_patient, model_version, prompt_version,
   signed_by_name, signed_at, session_enc, result_enc)
values (%(session_id)s, %(patient_ref)s, %(template_id)s, %(template_version)s, %(state)s,
        %(conversation_kind)s, %(complexity_score)s, %(is_complex)s, %(inference_mode)s,
        %(speaker_count)s, %(audio_confidence)s, %(confidence_band)s, %(referenced_patient)s,
        %(model_version)s, %(prompt_version)s,
        %(signed_by_name)s, %(signed_at)s, %(session_enc)s, %(result_enc)s)
on conflict (session_id) do update set
  patient_ref       = excluded.patient_ref,
  template_id       = excluded.template_id,
  template_version  = excluded.template_version,
  state             = excluded.state,
  conversation_kind = excluded.conversation_kind,
  complexity_score  = excluded.complexity_score,
  is_complex        = excluded.is_complex,
  inference_mode    = excluded.inference_mode,
  speaker_count     = excluded.speaker_count,
  audio_confidence  = excluded.audio_confidence,
  confidence_band   = excluded.confidence_band,
  referenced_patient = excluded.referenced_patient,
  model_version     = excluded.model_version,
  prompt_version    = excluded.prompt_version,
  signed_by_name    = excluded.signed_by_name,
  signed_at         = excluded.signed_at,
  session_enc       = excluded.session_enc,
  result_enc        = excluded.result_enc
"""

_SELECT = "select session_enc, result_enc from consultations where session_id = %(session_id)s"


class SupabaseSessionStore(SessionStore):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._cipher = get_cipher(settings)
        if not settings.supabase_db_url:
            raise RuntimeError(
                "SCRIBE_STORE_BACKEND=supabase requires SCRIBE_SUPABASE_DB_URL "
                "(the Supabase Postgres connection string; prefer the pooler endpoint)."
            )
        from psycopg_pool import ConnectionPool  # deferred — only needed for this backend

        # Small pool: the demo instance caps connections; the pooler endpoint handles
        # multiplexing. open=True validates the connection at startup (fail fast).
        self._pool = ConnectionPool(
            settings.supabase_db_url, min_size=1, max_size=settings.supabase_pool_max, open=True
        )

    # ── persistence helpers ──────────────────────────────────────────────────
    def _enc(self, obj: Any) -> str:
        return self._cipher.encrypt(json.dumps(obj))

    def _dec(self, token: str | None) -> Any:
        return json.loads(self._cipher.decrypt(token)) if token else None

    def _row(self, session: ConsultationSession) -> dict[str, Any]:
        result = self._results.get(session.session_id)
        prof = session.conversation_profile
        return {
            "session_id": session.session_id,
            "patient_ref": session.patient_id,
            "template_id": session.template_id,
            "template_version": session.template_version,
            "state": session.state.value,
            # Queryable conversation-intelligence metadata (non-PHI) for the admin console.
            # conversation_kind / inference_mode are NOT NULL in the schema (with defaults).
            # A freshly-created session has no profile/mode yet; the UPSERT lists every column
            # explicitly, so a NULL here would bypass the column default and trip the NOT NULL
            # constraint. Emit the schema's own defaults until the pipeline fills them in.
            "conversation_kind": prof.kind.value if prof else "unknown",
            "complexity_score": prof.complexity_score if prof else None,
            "is_complex": prof.is_complex if prof else False,
            "inference_mode": session.inference_mode or "realtime",
            "speaker_count": prof.speaker_count if prof else 0,
            "audio_confidence": prof.audio_confidence if prof else None,
            "confidence_band": prof.confidence_band.value if prof else None,
            "referenced_patient": prof.referenced_patient if prof else None,
            "model_version": session.model_version,
            "prompt_version": session.prompt_version,
            "signed_by_name": session.signed_by_name,
            "signed_at": session.signed_at.isoformat() if session.signed_at else None,
            "session_enc": self._enc(session.model_dump(mode="json")),
            "result_enc": self._enc(result.model_dump(mode="json")) if result else None,
        }

    def _save(self, session: ConsultationSession) -> None:
        with self._pool.connection() as conn:
            conn.execute(_UPSERT, self._row(session))

    def _hydrate(self, session_id: str) -> bool:
        """Load a session (and its result) from Postgres into the cache. Returns hit/miss."""
        with self._pool.connection() as conn:
            row = conn.execute(_SELECT, {"session_id": session_id}).fetchone()
        if not row:
            return False
        s_enc, r_enc = row
        try:
            self._sessions[session_id] = ConsultationSession.model_validate(self._dec(s_enc))
            if r_enc:
                self._results[session_id] = PipelineResult.model_validate(self._dec(r_enc))
            return True
        except Exception:  # noqa: BLE001 — a corrupt/incompatible row should not 500 the route
            logger.warning("failed to hydrate session %s from Supabase", session_id, exc_info=True)
            return False

    # ── SessionStore overrides ─────────────────────────────────────────────────
    def create(self, session: ConsultationSession) -> ConsultationSession:
        super().create(session)
        self._save(session)
        return session

    def exists(self, session_id: str) -> bool:
        return session_id in self._sessions or self._hydrate(session_id)

    def get(self, session_id: str) -> ConsultationSession:
        if session_id not in self._sessions:
            self._hydrate(session_id)
        return self._sessions[session_id]

    def set_result(self, session_id: str, result: PipelineResult) -> None:
        super().set_result(session_id, result)
        if session_id in self._sessions:
            self._save(self._sessions[session_id])

    def persist(self, session: ConsultationSession) -> None:
        self._save(session)
