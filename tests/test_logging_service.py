"""Tests for app/logging_service.py and related security helpers.

Uses only the _Noop fallback (no Supabase connection needed) plus a fake
in-memory implementation to cover the queue + worker path without a real DB.
"""
from __future__ import annotations

import queue
import threading
import time
import unittest.mock as mock

import pytest

from app.logging_service import _Noop, estimate_cost
from app.security.ratelimit import RateLimiter, client_ip
from app.security.startup import UnsafeProductionConfig, collect_problems, validate_production
from app.config import Settings


# ── estimate_cost ─────────────────────────────────────────────────────────────

def test_estimate_cost_none_when_both_none():
    assert estimate_cost(None, None) is None


def test_estimate_cost_zero_tokens():
    assert estimate_cost(0, 0) == 0.0


def test_estimate_cost_positive():
    cost = estimate_cost(1_000_000, 0)
    assert abs(cost - 0.075) < 1e-9


def test_estimate_cost_input_and_output():
    cost = estimate_cost(1_000_000, 1_000_000)
    assert abs(cost - 0.375) < 1e-9


# ── _Noop ─────────────────────────────────────────────────────────────────────

def test_noop_available_is_false():
    n = _Noop()
    assert n.available is False


def test_noop_ping_returns_false():
    assert _Noop().ping() is False


def test_noop_write_methods_do_not_raise():
    n = _Noop()
    n.log_request(request_id="r", user_id="u", method="GET", endpoint="/",
                  status_code=200, duration_ms=10)
    n.log_error(error_type="E", error_message="msg")
    n.log_ai(model="gemini", agent="extract")
    n.update_doctor(user_id="u")
    n.log_feedback(user_id="u")


def test_noop_lifecycle_methods_do_not_raise():
    n = _Noop()
    n.flush()
    n.close()


def test_noop_query_overview_contains_error_key():
    body = _Noop().query_overview()
    assert "error" in body
    assert "kpis" in body


def test_noop_query_doctors_empty():
    body = _Noop().query_doctors()
    assert body["doctors"] == []
    assert body["total"] == 0


def test_noop_query_logs_empty():
    body = _Noop().query_logs()
    assert body["logs"] == []


def test_noop_query_errors_empty():
    body = _Noop().query_errors()
    assert body["errors"] == []


def test_noop_query_ai_analytics_shape():
    body = _Noop().query_ai_analytics()
    assert "summary" in body
    assert "by_agent" in body


def test_noop_query_feedback_shape():
    body = _Noop().query_feedback()
    assert "feedback" in body
    assert "total" in body


def test_noop_query_system_health_shape():
    body = _Noop().query_system_health()
    assert "latency" in body
    assert "error_summary" in body


# ── SupabaseLoggingService (queue + worker, mocked pool) ──────────────────────

def _make_live_service():
    """Return a SupabaseLoggingService whose pool is fully mocked.

    Bypasses __init__ (which needs a real DB URL) while setting every instance
    attribute that _worker, _agent_worker, flush, and close reference.
    """
    from app.logging_service import SupabaseLoggingService

    svc = object.__new__(SupabaseLoggingService)
    svc._dropped = 0
    svc._consecutive_errors = 0
    svc._closing = False
    svc._queue = queue.Queue(maxsize=SupabaseLoggingService._QUEUE_MAXSIZE)
    svc._agent_queue = queue.Queue(maxsize=SupabaseLoggingService._QUEUE_MAXSIZE)
    svc._pool = mock.MagicMock()
    svc._thread = threading.Thread(target=svc._worker, daemon=True, name="test-logging")
    svc._thread.start()
    # _agent_worker exits immediately when no agent_api_key is configured (which is
    # always the case in tests), so this thread does nothing and stops on its own.
    svc._agent_thread = threading.Thread(target=svc._agent_worker, daemon=True, name="test-agent")
    svc._agent_thread.start()
    return svc


def test_live_service_enqueue_and_flush():
    svc = _make_live_service()
    results = []

    def _append(value):
        results.append(value)

    svc._enqueue(_append, "hello")
    svc._enqueue(_append, "world")
    svc.flush(timeout=2.0)
    svc.close()

    assert results == ["hello", "world"]


def test_live_service_close_is_idempotent():
    svc = _make_live_service()
    svc.close()
    svc.close()  # second close must not raise


def test_live_service_enqueue_after_close_is_noop():
    svc = _make_live_service()
    svc.close()
    # Should not raise and should not increment queue size.
    svc._enqueue(lambda: None)
    assert svc._queue.empty()


def test_live_service_dropped_counter():
    from app.logging_service import SupabaseLoggingService

    # Create with a queue size of 1 so it fills immediately.
    svc = object.__new__(SupabaseLoggingService)
    svc._dropped = 0
    svc._consecutive_errors = 0
    svc._closing = False
    svc._queue = queue.Queue(maxsize=1)
    svc._agent_queue = queue.Queue(maxsize=SupabaseLoggingService._QUEUE_MAXSIZE)
    svc._pool = mock.MagicMock()

    # Fill it (without a worker draining it).
    svc._queue.put(("dummy", (), {}))
    # Now enqueue should drop.
    svc._enqueue(lambda: None)
    assert svc._dropped == 1


def test_live_service_worker_survives_exception():
    svc = _make_live_service()
    called = []

    def _bad():
        raise RuntimeError("boom")

    def _good():
        called.append(True)

    svc._enqueue(_bad)
    svc._enqueue(_good)
    svc.flush(timeout=2.0)
    svc.close()

    assert called == [True]  # worker kept going after the exception


def test_live_service_consecutive_errors_increment():
    svc = _make_live_service()

    def _bad():
        raise RuntimeError("db error")

    for _ in range(3):
        svc._enqueue(_bad)
    svc.flush(timeout=2.0)
    svc.close()

    assert svc._consecutive_errors == 3


# ── RateLimiter ───────────────────────────────────────────────────────────────

def test_ratelimiter_allows_under_limit():
    rl = RateLimiter(max_hits=3, window_s=60)
    assert rl.check("ip1") is True
    assert rl.check("ip1") is True
    assert rl.check("ip1") is True


def test_ratelimiter_blocks_over_limit():
    rl = RateLimiter(max_hits=3, window_s=60)
    for _ in range(3):
        rl.check("ip1")
    assert rl.check("ip1") is False


def test_ratelimiter_reset_clears_counter():
    rl = RateLimiter(max_hits=2, window_s=60)
    rl.check("ip1")
    rl.check("ip1")
    assert rl.check("ip1") is False
    rl.reset("ip1")
    assert rl.check("ip1") is True


def test_ratelimiter_per_key_isolation():
    rl = RateLimiter(max_hits=1, window_s=60)
    rl.check("ip1")
    assert rl.check("ip1") is False
    assert rl.check("ip2") is True  # different key → unaffected


def test_ratelimiter_window_expiry():
    rl = RateLimiter(max_hits=1, window_s=1)
    rl.check("ip1")
    assert rl.check("ip1") is False
    time.sleep(1.1)
    assert rl.check("ip1") is True  # window expired


def test_client_ip_from_forwarded_for():
    req = mock.MagicMock()
    req.headers = {"x-forwarded-for": "10.0.0.1, 192.168.1.1"}
    req.client = None
    assert client_ip(req) == "10.0.0.1"


def test_client_ip_fallback_to_client():
    req = mock.MagicMock()
    req.headers = {}
    req.client.host = "127.0.0.1"
    assert client_ip(req) == "127.0.0.1"


def test_client_ip_no_client():
    req = mock.MagicMock()
    req.headers = {}
    req.client = None
    assert client_ip(req) == "unknown"


# ── Startup guard ─────────────────────────────────────────────────────────────

def test_collect_problems_empty_in_safe_config():
    import app.security.crypto as crypto
    crypto._cipher = None

    from app.security.crypto import generate_key_b64
    key = generate_key_b64()
    s = Settings(
        environment="production",
        store_backend="memory",  # not durable — no PHI key needed
        auth_mode="jwt",
        jwt_secret="a-secret-key-that-is-long-enough-123456",
        admin_password="safe-unique-password",
        cors_allow_origins="https://app.example.com",
    )
    problems = collect_problems(s)
    assert problems == []
    crypto._cipher = None


def test_collect_problems_durable_store_without_phi_key():
    import app.security.crypto as crypto
    crypto._cipher = None

    s = Settings(
        store_backend="sqlite",
        auth_mode="jwt",
        jwt_secret="a-secret-key-that-is-long-enough-123456",
        admin_password="safe-unique-password",
        cors_allow_origins="https://app.example.com",
        phi_encryption_key_b64="",  # no key
    )
    problems = collect_problems(s)
    assert any("PHI" in p or "phi" in p.lower() or "PLAINTEXT" in p for p in problems)
    crypto._cipher = None


def test_collect_problems_dev_auth_mode():
    s = Settings(
        store_backend="memory",
        auth_mode="dev",
        admin_password="safe-unique-password",
        cors_allow_origins="https://app.example.com",
    )
    problems = collect_problems(s)
    assert any("auth_mode" in p for p in problems)


def test_collect_problems_default_admin_password():
    s = Settings(
        store_backend="memory",
        auth_mode="jwt",
        jwt_secret="a-secret-key-that-is-long-enough-123456",
        admin_password="kraionyx1",  # the hardcoded default
        cors_allow_origins="https://app.example.com",
    )
    problems = collect_problems(s)
    assert any("admin_password" in p for p in problems)


def test_collect_problems_localhost_cors():
    s = Settings(
        store_backend="memory",
        auth_mode="jwt",
        jwt_secret="a-secret-key-that-is-long-enough-123456",
        admin_password="safe-unique-password",
        cors_allow_origins="http://localhost:5173",
    )
    problems = collect_problems(s)
    assert any("localhost" in p for p in problems)


def test_validate_production_raises_on_unsafe():
    s = Settings(
        environment="production",
        store_backend="memory",
        auth_mode="dev",  # unsafe
        admin_password="kraionyx1",
        cors_allow_origins="http://localhost:5173",
    )
    with pytest.raises(UnsafeProductionConfig):
        validate_production(s)


def test_validate_production_only_warns_in_dev(caplog):
    """Development mode must never block — only warn."""
    import logging
    s = Settings(
        environment="development",
        store_backend="memory",
        auth_mode="dev",
        admin_password="kraionyx1",
        cors_allow_origins="http://localhost:5173",
    )
    with caplog.at_level(logging.WARNING, logger="svaani.startup"):
        validate_production(s)  # must not raise
    assert any("unsafe" in r.message.lower() or "production" in r.message.lower()
               for r in caplog.records)
