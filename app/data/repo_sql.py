"""Durable operational repository (Goal 2 fix — reviews/admin/improvements/prompts/
models/documents/edits/flags survive a restart).

The in-memory ``Repository`` holds everything in RAM. This subclass keeps the same dicts as
a live cache (so mutation semantics are identical within a run) but **writes through** every
change to a small key/value table ``op_records(kind, rid, payload)`` and hydrates the cache
on startup. The repository LOGIC is unchanged and backend-agnostic; only the storage driver
differs:

  • SQLite (stdlib, no service) — used by ``SCRIBE_STORE_BACKEND=sqlite`` (docker-compose);
  • Postgres/Supabase (psycopg, lazily imported) — used by ``SCRIBE_STORE_BACKEND=supabase``.

PHI-bearing payloads (AI edit before/after text, rendered prescription HTML) are encrypted
at rest with the existing ``FieldCipher`` (AES-256-GCM); operational metadata is stored plain
so it stays debuggable. We use a simple model-aligned KV table rather than the structured
``schema.sql`` tables on purpose: the app keys entities by text ids / session_id, while those
tables use uuid PKs + FKs to ``consultations(uuid)`` — the KV table avoids that impedance and
keeps the two storage responsibilities (clinical session store vs operational repo) cleanly
separate.
"""
from __future__ import annotations

import json
import threading
from typing import Protocol

from app.config import Settings
from app.schemas.document import DocumentTemplate, RenderedDocument
from app.schemas.review import (
    AdminReview,
    ConsultationReview,
    ImprovementItem,
    ModelVersion,
    PromptVersion,
)
from app.security.crypto import get_cipher

# kind -> (cache attribute, pydantic model). Edits and flags are handled specially.
_MODEL_KINDS: dict[str, type] = {
    "review": ConsultationReview,
    "admin_review": AdminReview,
    "improvement": ImprovementItem,
    "prompt": PromptVersion,
    "model": ModelVersion,
    "doc_template": DocumentTemplate,
    "rendered_doc": RenderedDocument,
}
# Payloads that contain PHI and must be encrypted at rest.
_PHI_KINDS = {"rendered_doc", "edit"}


class _Store(Protocol):
    def upsert(self, kind: str, rid: str, payload: str) -> None: ...
    def all(self, kind: str) -> list[tuple[str, str]]: ...  # (rid, payload)
    def delete(self, kind: str, rid: str) -> None: ...


# ── SQLite driver ──────────────────────────────────────────────────────────────
class _SqliteStore:
    def __init__(self, path: str) -> None:
        import sqlite3

        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS op_records "
            "(kind TEXT, rid TEXT, payload TEXT, PRIMARY KEY(kind, rid))"
        )
        self._db.commit()

    def upsert(self, kind: str, rid: str, payload: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO op_records(kind, rid, payload) VALUES(?,?,?) "
                "ON CONFLICT(kind, rid) DO UPDATE SET payload=excluded.payload",
                (kind, rid, payload),
            )
            self._db.commit()

    def all(self, kind: str) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._db.execute(
                "SELECT rid, payload FROM op_records WHERE kind=? ORDER BY rid", (kind,)
            ).fetchall())

    def delete(self, kind: str, rid: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM op_records WHERE kind=? AND rid=?", (kind, rid))
            self._db.commit()


# ── Postgres / Supabase driver (lazy psycopg; not exercised without a live DB) ───
class _PostgresStore:
    def __init__(self, dsn: str, pool_max: int = 4) -> None:
        from psycopg_pool import ConnectionPool  # deferred — only this backend needs it

        self._pool = ConnectionPool(dsn, min_size=1, max_size=pool_max, open=True)
        with self._pool.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS op_records "
                "(kind TEXT, rid TEXT, payload TEXT, PRIMARY KEY(kind, rid))"
            )

    def upsert(self, kind: str, rid: str, payload: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO op_records(kind, rid, payload) VALUES(%s,%s,%s) "
                "ON CONFLICT(kind, rid) DO UPDATE SET payload=excluded.payload",
                (kind, rid, payload),
            )

    def all(self, kind: str) -> list[tuple[str, str]]:
        with self._pool.connection() as conn:
            return list(conn.execute(
                "SELECT rid, payload FROM op_records WHERE kind=%s ORDER BY rid", (kind,)
            ).fetchall())

    def delete(self, kind: str, rid: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM op_records WHERE kind=%s AND rid=%s", (kind, rid))


def make_sqlite_store(settings: Settings) -> _SqliteStore:
    return _SqliteStore(settings.sqlite_path)


def make_postgres_store(settings: Settings) -> _PostgresStore:
    if not settings.supabase_db_url:
        raise RuntimeError(
            "SCRIBE_STORE_BACKEND=supabase requires SCRIBE_SUPABASE_DB_URL (the Postgres "
            "connection string; prefer the pooler endpoint)."
        )
    return _PostgresStore(settings.supabase_db_url, settings.supabase_pool_max)


# ── Persistent repository ────────────────────────────────────────────────────────
def build_persistent_repository(store: _Store, settings: Settings):
    """Construct a PersistentRepository, seeding it from the constants if the store is empty."""
    from app.data.repo import Repository, _seed

    class PersistentRepository(Repository):
        def __init__(self) -> None:
            super().__init__()
            self._store = store
            self._cipher = get_cipher(settings)
            self._hydrate()

        # ── serialization ──────────────────────────────────────────────────────
        def _ser(self, kind: str, raw: str) -> str:
            return self._cipher.encrypt(raw) if kind in _PHI_KINDS else raw

        def _deser(self, kind: str, stored: str) -> str:
            return self._cipher.decrypt(stored) if kind in _PHI_KINDS else stored

        def _put(self, kind: str, rid: str, raw_json: str) -> None:
            self._store.upsert(kind, rid, self._ser(kind, raw_json))

        def _put_model(self, kind: str, obj) -> None:
            self._put(kind, obj.id, obj.model_dump_json())

        # ── hydrate cache from the store ─────────────────────────────────────────
        def _hydrate(self) -> None:
            caches = {
                "review": self.reviews, "admin_review": self.admin_reviews,
                "improvement": self.improvements, "prompt": self.prompts,
                "model": self.models, "doc_template": self.doc_templates,
                "rendered_doc": self.rendered_docs,
            }
            for kind, model in _MODEL_KINDS.items():
                for rid, payload in self._store.all(kind):
                    try:
                        caches[kind][rid] = model.model_validate_json(self._deser(kind, payload))
                    except Exception:  # noqa: BLE001 — skip a corrupt/incompatible row
                        continue
            for rid, payload in self._store.all("edit"):
                sid = rid.split("#", 1)[0]
                try:
                    self.edits.setdefault(sid, []).append(json.loads(self._deser("edit", payload)))
                except Exception:  # noqa: BLE001
                    continue
            for sid in self.edits:
                self.edits[sid].sort(key=lambda e: e.get("seq", 0))
            for rid, payload in self._store.all("flag"):
                try:
                    self.flags[rid] = json.loads(payload)
                except Exception:  # noqa: BLE001
                    continue
            for _rid, payload in self._store.all("ab_metric"):
                try:
                    self.ab_metrics.append(json.loads(payload))
                except Exception:  # noqa: BLE001
                    continue
            for _rid, payload in self._store.all("latency"):
                try:
                    self.stage_latencies.append(json.loads(payload))
                except Exception:  # noqa: BLE001
                    continue
            if not self.prompts:  # fresh store — seed v1 prompts/model/template (write-through)
                _seed(self)

        # ── write-through overrides ──────────────────────────────────────────────
        def add_review(self, review: ConsultationReview) -> ConsultationReview:
            r = super().add_review(review)
            self._put_model("review", r)
            for ar in self.admin_reviews.values():
                if ar.review_id == r.id:
                    self._put_model("admin_review", ar)
            return r

        def update_admin_review(self, admin_id, **kw) -> AdminReview:
            ar = super().update_admin_review(admin_id, **kw)
            self._put_model("admin_review", ar)
            for item in self.improvements.values():  # an approval may have seeded one
                if item.admin_review_id == ar.id:
                    self._put_model("improvement", item)
            return ar

        def advance_improvement(self, item_id, **kw) -> ImprovementItem:
            item = super().advance_improvement(item_id, **kw)
            self._put_model("improvement", item)
            return item

        def set_improvement_eval(self, item_id, eval_results, regression_test_id=None) -> ImprovementItem:
            item = super().set_improvement_eval(item_id, eval_results, regression_test_id)
            self._put_model("improvement", item)
            return item

        def record_ab_metric(self, metric: dict) -> dict:
            out = super().record_ab_metric(metric)
            import uuid as _uuid

            self._store.upsert("ab_metric", _uuid.uuid4().hex, json.dumps(out))
            return out

        def record_stage_latency(self, row: dict) -> dict:
            out = super().record_stage_latency(row)
            import uuid as _uuid

            self._store.upsert("latency", _uuid.uuid4().hex, json.dumps(out))
            return out

        def _persist_all_prompts(self) -> None:
            for pv in self.prompts.values():
                self._put_model("prompt", pv)

        def add_prompt_version(self, pv: PromptVersion) -> PromptVersion:
            out = super().add_prompt_version(pv)
            self._persist_all_prompts()  # activation may have flipped other versions
            return out

        def activate_prompt(self, prompt_id: str) -> PromptVersion:
            out = super().activate_prompt(prompt_id)
            self._persist_all_prompts()
            return out

        def add_model_version(self, mv: ModelVersion) -> ModelVersion:
            out = super().add_model_version(mv)
            self._put_model("model", out)
            return out

        def add_document_template(self, dt: DocumentTemplate) -> DocumentTemplate:
            out = super().add_document_template(dt)
            self._put_model("doc_template", out)
            return out

        def save_rendered_document(self, doc: RenderedDocument) -> RenderedDocument:
            out = super().save_rendered_document(doc)
            self._put_model("rendered_doc", out)
            return out

        def add_edit(self, session_id: str, edit: dict) -> dict:
            out = super().add_edit(session_id, edit)
            self._put("edit", f"{session_id}#{out['seq']:06d}", json.dumps(out))
            return out

        def set_edit_undone(self, session_id: str, seq: int, undone: bool) -> dict:
            e = super().set_edit_undone(session_id, seq, undone)
            self._put("edit", f"{session_id}#{seq:06d}", json.dumps(e))
            return e

        def drop_undone_edits(self, session_id: str) -> list[int]:
            dropped = super().drop_undone_edits(session_id)
            for seq in dropped:
                self._store.delete("edit", f"{session_id}#{seq:06d}")
            return dropped

        def set_flag(self, key: str, enabled: bool, value: dict | None = None) -> dict:
            out = super().set_flag(key, enabled, value)
            self._store.upsert("flag", key, json.dumps({"enabled": out["enabled"], "value": out["value"]}))
            return out

    return PersistentRepository()
