"""Supabase JWT claim resolution → Principal (id = auth.users UUID, email, app role)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.security.auth import principal_from
from app.security.rbac import Role

# ≥32 bytes per RFC 7518 §3.2 (PyJWT warns on shorter HS256 keys).
SECRET = "svaani-test-secret-key-0123456789abcdef"


def _token(claims: dict) -> str:
    jwt = pytest.importorskip("jwt")
    return jwt.encode(claims, SECRET, algorithm="HS256")


def test_jwt_resolves_uuid_email_and_defaults_to_doctor():
    s = Settings(auth_mode="jwt", jwt_secret=SECRET)
    # Supabase sets the top-level role to the Postgres role 'authenticated' — must NOT map
    # to an app role; every signed-in user defaults to DOCTOR.
    tok = _token({"sub": "8f1e-uuid", "email": "dr@hospital.org", "role": "authenticated"})
    p = principal_from(s, authorization=f"Bearer {tok}", x_user_id="ignored", x_role="ignored")
    assert p.id == "8f1e-uuid"
    assert p.email == "dr@hospital.org"
    assert p.role is Role.DOCTOR


def test_jwt_app_metadata_role_promotes_admin():
    s = Settings(auth_mode="jwt", jwt_secret=SECRET)
    tok = _token({"sub": "u2", "app_metadata": {"role": "admin"}})
    p = principal_from(s, authorization=f"Bearer {tok}", x_user_id="", x_role="")
    assert p.role is Role.ADMIN


def test_jwt_email_falls_back_to_user_metadata():
    s = Settings(auth_mode="jwt", jwt_secret=SECRET)
    tok = _token({"sub": "u3", "user_metadata": {"email": "via-meta@x.org"}})
    p = principal_from(s, authorization=f"Bearer {tok}", x_user_id="", x_role="")
    assert p.email == "via-meta@x.org"


def test_auth_failure_is_logged_to_admin_console(monkeypatch):
    """A rejected token in jwt mode must produce a structured error (source='auth') so it
    shows up in the admin console's Errors view — not just a bare 401 in the access log."""
    from fastapi.testclient import TestClient
    import app.main as main

    captured: list[dict] = []

    class _Cap:
        def log_error(self, **kw): captured.append(kw)
        def log_request(self, **kw): pass
        def update_doctor(self, **kw): pass

    monkeypatch.setattr(main, "get_settings", lambda: Settings(auth_mode="jwt", jwt_secret=SECRET))
    monkeypatch.setattr(main, "get_logging_service", lambda: _Cap())

    r = TestClient(main.app).get("/sessions", headers={"Authorization": "Bearer not.a.real.token"})
    assert r.status_code == 401
    auth_events = [c for c in captured if c.get("source") == "auth"]
    assert auth_events, "expected an auth error to be logged for the admin console"
    assert auth_events[0]["error_type"].startswith("auth_")
