"""Production-hardening: durable encrypted store + JWT auth resolution."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.schemas.session import ConsultationSession, ReviewState
from app.security.auth import AuthError, principal_from
from app.security.rbac import Role


# ── Persistent SQLite store ──────────────────────────────────────────────────
def test_sqlite_store_persists_across_instances(tmp_path):
    from app.store_sql import SqlSessionStore

    db = str(tmp_path / "t.db")
    s = Settings(store_backend="sqlite", sqlite_path=db, phi_encryption_key_b64="")

    store = SqlSessionStore(s)
    sess = ConsultationSession(session_id="sess-abc", template_id="soap")
    store.create(sess)
    sess.transition(ReviewState.PROCESSING)
    sess.transition(ReviewState.DRAFT)
    store.persist(sess)

    # A fresh store instance (simulating a restart) reloads from disk.
    reopened = SqlSessionStore(s)
    assert reopened.exists("sess-abc")
    assert reopened.get("sess-abc").state is ReviewState.DRAFT


def test_sqlite_store_encrypts_at_rest(tmp_path):
    import base64
    from app.store_sql import SqlSessionStore
    from app.security.crypto import generate_key_b64
    import app.security.crypto as crypto

    crypto._cipher = None  # reset the cached cipher so our key is used
    key = generate_key_b64()
    db = str(tmp_path / "enc.db")
    s = Settings(store_backend="sqlite", sqlite_path=db, phi_encryption_key_b64=key)
    store = SqlSessionStore(s)
    store.create(ConsultationSession(session_id="sess-secret-xyz", template_id="soap", patient_id="PATIENT-PHI-42"))

    # The PHI must not appear as plaintext in the DB file.
    raw = open(db, "rb").read()
    assert b"PATIENT-PHI-42" not in raw
    crypto._cipher = None  # don't leak the test cipher to other tests


# ── JWT auth ─────────────────────────────────────────────────────────────────
def test_dev_mode_uses_headers():
    s = Settings(auth_mode="dev")
    p = principal_from(s, authorization=None, x_user_id="u1", x_role="doctor")
    assert p.id == "u1" and p.role is Role.DOCTOR


def test_jwt_mode_requires_valid_token():
    jwt = pytest.importorskip("jwt")
    # ≥32 bytes per RFC 7518 §3.2 (PyJWT warns on shorter HS256 keys).
    secret = "svaani-test-secret-key-0123456789abcdef"
    s = Settings(auth_mode="jwt", jwt_secret=secret)
    token = jwt.encode({"sub": "dr-rao", "role": "doctor"}, secret, algorithm="HS256")
    p = principal_from(s, authorization=f"Bearer {token}", x_user_id="x", x_role="x")
    assert p.id == "dr-rao" and p.role is Role.DOCTOR

    with pytest.raises(AuthError):
        principal_from(s, authorization="Bearer not.a.token", x_user_id="x", x_role="x")
    with pytest.raises(AuthError):
        principal_from(s, authorization=None, x_user_id="x", x_role="x")
