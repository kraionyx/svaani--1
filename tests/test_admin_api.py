"""Tests for the admin dashboard API (app/admin_routes.py).

Covers:
- Auth: no-token → 401, wrong password → 200 ok=False, correct password → ok + token
- Rate limiting on /auth: 429 after max_hits wrong attempts
- All protected GET endpoints require the token (401 without it)
- Observability endpoints return the expected shape (Noop data — no Supabase needed)
- Operational endpoints (prompts, models, flags, reviews, improvements) round-trip via
  the in-memory Repository
- Ingestion endpoints (frontend errors, feedback) accept input without auth and return ok
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.admin_routes import _auth_limiter
from app.logging_service import _Noop
from app.main import app

client = TestClient(app)

_GOOD_PW = "admin@kraionyx"

_cached_token = None

def _token() -> dict:
    """Return an X-Admin-Token header with a valid admin JWT."""
    global _cached_token
    if not _cached_token:
        r = client.post("/admin1/api/auth", json={"password": _GOOD_PW})
        _cached_token = r.json()["token"]
    return {"X-Admin-Token": _cached_token}


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Isolate every test: fresh in-memory repo, cleared rate-limiter, Noop logging service.

    Monkeypatching both get_repo and get_logging_service ensures that even when a local
    .env sets SCRIBE_STORE_BACKEND=supabase / SCRIBE_SUPABASE_DB_URL, admin route tests
    never touch external services and have a clean slate every test.
    """
    from app.data.repo import Repository, _seed

    fresh_repo = Repository()
    _seed(fresh_repo)

    _auth_limiter._hits.clear()
    _noop = _Noop()
    monkeypatch.setattr("app.admin_routes.get_logging_service", lambda: _noop)
    monkeypatch.setattr("app.admin_routes.get_repo", lambda: fresh_repo)
    yield


# ── Auth endpoint ──────────────────────────────────────────────────────────────

def test_auth_no_body_returns_422():
    r = client.post("/admin1/api/auth", json={})
    assert r.status_code == 422


def test_auth_wrong_password_returns_ok_false():
    r = client.post("/admin1/api/auth", json={"password": "wrong"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_auth_correct_password_returns_token():
    r = client.post("/admin1/api/auth", json={"password": _GOOD_PW})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert isinstance(data["token"], str)
    assert len(data["token"]) > 32


def test_protected_endpoint_without_token_returns_401():
    r = client.get("/admin1/api/overview")
    assert r.status_code == 401


def test_protected_endpoint_wrong_token_returns_403():
    r = client.get("/admin1/api/overview", headers={"X-Admin-Token": "badtoken"})
    assert r.status_code == 403


def test_auth_rate_limiting():
    """After max_hits wrong-password attempts the limiter fires 429."""
    # Drain existing window for our test IP first.
    _auth_limiter._hits.clear()
    limit = _auth_limiter.max_hits

    for _ in range(limit):
        client.post("/admin1/api/auth", json={"password": "wrong"})

    r = client.post("/admin1/api/auth", json={"password": "wrong"})
    assert r.status_code == 429


def test_successful_auth_does_not_reset_rate_limiter():
    """A correct password no longer clears the counter to prevent sustained brute force."""
    _auth_limiter._hits.clear()
    limit = _auth_limiter.max_hits

    # Fill up to the limit - 1 wrong attempts.
    for _ in range(limit - 1):
        client.post("/admin1/api/auth", json={"password": "wrong"})

    # Correct password → success, but does NOT reset the counter.
    r = client.post("/admin1/api/auth", json={"password": _GOOD_PW})
    assert r.json()["ok"] is True

    # Should NOT be allowed immediately (we no longer reset limit on success).
    r = client.post("/admin1/api/auth", json={"password": "wrong"})
    assert r.status_code == 429


# ── Observability endpoints (Noop — no Supabase) ──────────────────────────────

def test_overview_shape():
    r = client.get("/admin1/api/overview", headers=_token())
    assert r.status_code == 200
    body = r.json()
    assert "kpis" in body
    assert "top_doctors" in body


def test_health_shape():
    r = client.get("/admin1/api/health", headers=_token())
    assert r.status_code == 200
    body = r.json()
    assert "latency" in body
    assert "error_summary" in body


def test_doctors_shape():
    r = client.get("/admin1/api/doctors", headers=_token())
    assert r.status_code == 200
    body = r.json()
    assert "doctors" in body
    assert "total" in body


def test_logs_shape():
    r = client.get("/admin1/api/logs", headers=_token())
    assert r.status_code == 200
    assert "logs" in r.json()


def test_errors_shape():
    r = client.get("/admin1/api/errors", headers=_token())
    assert r.status_code == 200
    assert "errors" in r.json()


def test_ai_analytics_shape():
    r = client.get("/admin1/api/ai-analytics", headers=_token())
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert "latency_stages" in body  # merged operational metric


def test_feedback_shape():
    r = client.get("/admin1/api/feedback", headers=_token())
    assert r.status_code == 200
    body = r.json()
    assert "feedback" in body


# ── Operational endpoints (Repository) ────────────────────────────────────────

def test_prompts_list_is_seeded():
    r = client.get("/admin1/api/prompts", headers=_token())
    assert r.status_code == 200
    prompts = r.json()
    assert isinstance(prompts, list)
    assert any(p["name"] == "extract" for p in prompts)


def test_prompts_create_and_activate():
    r = client.post(
        "/admin1/api/prompts",
        json={"name": "test-prompt", "content": "v1 content", "activate": False},
        headers=_token(),
    )
    assert r.status_code == 200
    created = r.json()
    assert created["version"] == 1
    assert created["active"] is False

    pid = created["id"]
    r2 = client.post(f"/admin1/api/prompts/{pid}/activate", headers=_token())
    assert r2.status_code == 200
    assert r2.json()["active"] is True


def test_prompts_activate_unknown_returns_404():
    r = client.post("/admin1/api/prompts/nonexistent/activate", headers=_token())
    assert r.status_code == 404


def test_models_list():
    r = client.get("/admin1/api/models", headers=_token())
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_feature_flags_read_and_set():
    r = client.get("/admin1/api/feature-flags", headers=_token())
    assert r.status_code == 200
    body = r.json()
    assert "config" in body and "runtime" in body
    assert "single_pass_llm" in body["config"]

    r2 = client.post(
        "/admin1/api/feature-flags",
        json={"key": "test-flag", "enabled": True, "value": {}},
        headers=_token(),
    )
    assert r2.status_code == 200
    assert r2.json()["enabled"] is True


def test_reviews_empty_by_default():
    r = client.get("/admin1/api/admin/reviews", headers=_token())
    assert r.status_code == 200
    assert r.json() == []


def test_improvements_empty_by_default():
    r = client.get("/admin1/api/admin/improvements", headers=_token())
    assert r.status_code == 200
    assert r.json() == []


def test_ab_metrics_unknown_prompt():
    r = client.get("/admin1/api/admin/prompts/no-such/ab/metrics", headers=_token())
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert "arms" in body


# ── Ingestion endpoints (no auth) ──────────────────────────────────────────────

def test_frontend_error_ingestion():
    r = client.post(
        "/admin1/api/errors/frontend",
        json={
            "error_type": "TypeError",
            "error_message": "Cannot read property 'x' of undefined",
            "stack_trace": "at App.tsx:42",
            "user_id": "u1",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_feedback_ingestion():
    r = client.post(
        "/admin1/api/feedback",
        json={"user_id": "u2", "rating": 5, "feedback_text": "Works great"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_feedback_minimal_fields():
    r = client.post("/admin1/api/feedback", json={"user_id": "u3"})
    assert r.status_code == 200


# ── AI Agent Chat endpoint ───────────────────────────────────────────────────

def test_admin_chat_unconfigured_returns_500(monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_api_key", "")
    
    r = client.post(
        "/admin1/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers=_token()
    )
    assert r.status_code == 500
    assert "SCRIBE_AGENT_API_KEY is not configured" in r.json()["detail"]


def test_admin_chat_success(monkeypatch):
    from app.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_api_key", "test-key")
    
    class MockMessage:
        content = "Mocked DevOps agent response"
        
    class MockChoice:
        message = MockMessage()
        
    class MockCompletion:
        choices = [MockChoice()]
        
    class MockChat:
        def completions(self, *args, **kwargs):
            return MockCompletion()
            
    class MockSarvamAI:
        def __init__(self, api_subscription_key):
            assert api_subscription_key == "test-key"
            self.chat = MockChat()
            
    import sys
    from types import ModuleType
    
    mock_module = ModuleType("sarvamai")
    mock_module.SarvamAI = MockSarvamAI
    sys.modules["sarvamai"] = mock_module
    
    try:
        r = client.post(
            "/admin1/api/chat",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers=_token()
        )
        assert r.status_code == 200
        assert r.json()["response"] == "Mocked DevOps agent response"
    finally:
        sys.modules.pop("sarvamai", None)

