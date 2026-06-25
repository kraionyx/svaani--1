"""Production logging service — async, non-blocking writes to Supabase analytics tables.

All public write methods enqueue the work and return immediately; a single daemon
thread drains the queue. A Supabase failure is logged locally but never propagates
to the request path. If no DB URL is configured, every call is a silent no-op.

Read methods (used by the admin API) are synchronous and use the same pool.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime, timezone

logger = logging.getLogger("svaani.logging_svc")

# Gemini cost estimates (USD per token) — approximations; update when pricing changes.
_COST_INPUT_PER_TOKEN  = 0.075 / 1_000_000   # $0.075 / 1M input tokens
_COST_OUTPUT_PER_TOKEN = 0.30  / 1_000_000   # $0.30  / 1M output tokens


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Identities that are NOT real clinicians and must never be counted/ranked as doctors:
# the unauthenticated fallback and the dev header-auth scaffold ids. In jwt (production)
# mode a real doctor is the Supabase auth UUID, which is never in this set.
_NON_DOCTOR_IDS = {"", "anonymous", "doc", "dev-doctor", "scribe", "admin", "auditor"}
# A real doctor is an identity with genuine CLINICAL activity — not merely one that sent an
# HTTP request. Requiring sessions/AI/reports > 0 (on top of excluding the infra/dev ids)
# generically drops request-only phantoms like "adm"/"dashboard" without hardcoding them.
_REAL_DOCTOR_SQL = (
    "user_id IS NOT NULL"
    " AND user_id NOT IN ('anonymous','doc','dev-doctor','scribe','admin','auditor')"
    " AND (total_sessions > 0 OR total_ai_calls > 0 OR total_reports > 0)"
)


def _is_real_doctor(user_id: str | None) -> bool:
    return bool(user_id) and user_id not in _NON_DOCTOR_IDS


def estimate_cost(prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    if prompt_tokens is None and completion_tokens is None:
        return None
    return (prompt_tokens or 0) * _COST_INPUT_PER_TOKEN + (completion_tokens or 0) * _COST_OUTPUT_PER_TOKEN


# ── No-op fallback ─────────────────────────────────────────────────────────────

class _Noop:
    """Used when Supabase is not configured. All methods are silent no-ops."""
    available = False

    def log_request(self, **_): pass
    def log_error(self, **_): pass
    def log_ai(self, **_): pass
    def update_doctor(self, **_): pass
    def log_feedback(self, **_): pass
    def flush(self, timeout: float = 5.0): pass
    def close(self, timeout: float = 5.0): pass

    def ping(self) -> bool:
        return False

    _ERR = "Supabase not configured — set SCRIBE_SUPABASE_DB_URL"

    def query_overview(self) -> dict:
        return {"kpis": {}, "top_doctors": [], "recent_errors": [], "error": self._ERR}

    def query_doctors(self, page: int = 1, limit: int = 20, search: str = "") -> dict:
        return {"doctors": [], "total": 0, "error": self._ERR}

    def query_logs(self, *, page: int = 1, limit: int = 50, user_id: str = "",
                   endpoint: str = "", status: str = "", from_dt: str = "", to_dt: str = "") -> dict:
        return {"logs": [], "total": 0, "error": self._ERR}

    def query_errors(self, *, page: int = 1, limit: int = 50, severity: str = "",
                     source: str = "", from_dt: str = "", to_dt: str = "") -> dict:
        return {"errors": [], "total": 0, "error": self._ERR}

    def query_error_groups(self, *, limit: int = 50, severity: str = "",
                           source: str = "", from_dt: str = "", to_dt: str = "") -> dict:
        return {"groups": [], "total": 0, "error": self._ERR}

    def query_ai_analytics(self, *, from_dt: str = "", to_dt: str = "") -> dict:
        return {"summary": {}, "by_agent": [], "by_model": [], "recent_calls": [], "error": self._ERR}

    def query_feedback(self, *, page: int = 1, limit: int = 20) -> dict:
        return {"stats": {}, "feedback": [], "total": 0, "error": self._ERR}

    def query_system_health(self) -> dict:
        return {"latency": {}, "error_summary": {}, "slowest_endpoints": [], "error": self._ERR}


# ── Live service ───────────────────────────────────────────────────────────────

class SupabaseLoggingService:
    """Queue-backed, single-worker logging service backed by a psycopg connection pool."""

    available = True

    # Bounded queue so a slow/unavailable DB can never grow memory without limit. When
    # full, new log writes are dropped (counted) — observability must never add latency
    # or back-pressure to the request path.
    _QUEUE_MAXSIZE = 10_000
    _STOP = object()  # sentinel: tells the worker to drain and exit

    def __init__(self, db_url: str, pool_max: int = 4) -> None:
        from app.data.pg_pool import make_pool

        # Health-checked pool: Supabase's pooler drops idle connections, so without
        # check/max_idle a write or read would crash on a dead connection
        # (OperationalError: server closed the connection). timeout caps how long a write
        # waits for a free connection — without it, pool exhaustion would deadlock the worker.
        self._pool = make_pool(db_url, min_size=1, max_size=pool_max, open=True, timeout=10.0)
        self._queue: queue.Queue = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._agent_queue: queue.Queue = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._dropped = 0          # writes discarded because the queue was full
        self._consecutive_errors = 0
        self._closing = False
        self._thread = threading.Thread(target=self._worker, daemon=True, name="svaani-logging")
        self._thread.start()
        self._agent_thread = threading.Thread(target=self._agent_worker, daemon=True, name="svaani-agent")
        self._agent_thread.start()
        logger.info("Supabase logging service started (pool_max=%d, queue_max=%d)",
                    pool_max, self._QUEUE_MAXSIZE)

    # ── Background worker ──────────────────────────────────────────────────────

    def _worker(self) -> None:
        # The loop must never die: a bug in one write would otherwise silently stop ALL
        # logging. Every iteration is individually guarded.
        while True:
            try:
                item = self._queue.get()
            except Exception:  # pragma: no cover — Queue.get is robust, belt-and-braces
                continue
            if item is self._STOP:
                self._queue.task_done()
                return
            fn, args, kwargs = item
            try:
                fn(*args, **kwargs)
                self._consecutive_errors = 0
            except Exception:
                # Escalate from debug to warning when failures persist (e.g. DB down) so
                # the operator notices instead of losing telemetry silently.
                self._consecutive_errors += 1
                if self._consecutive_errors in (1, 10) or self._consecutive_errors % 100 == 0:
                    logger.warning("logging worker write failed (%d consecutive)",
                                   self._consecutive_errors, exc_info=True)
            finally:
                self._queue.task_done()

    def _agent_worker(self) -> None:
        try:
            from app.config import get_settings
            agent_key = get_settings().agent_api_key
        except Exception:
            return
        if not agent_key:
            return
        
        try:
            from sarvamai import SarvamAI
            client = SarvamAI(api_subscription_key=agent_key)
        except Exception:
            return
            
        while True:
            try:
                item = self._agent_queue.get()
            except Exception:
                continue
            if item is self._STOP:
                self._agent_queue.task_done()
                return
            
            try:
                error_id, error_type, error_message, stack_trace, source = item
                prompt = (
                    f"You are an autonomous AI debugging agent. Analyze this error and stack trace. "
                    f"Provide a concise root cause and a code-level fix.\n\n"
                    f"Error Type: {error_type}\nMessage: {error_message}\nSource: {source}\n\nStacktrace:\n{stack_trace}"
                )
                
                response = client.chat.completions(
                    model="sarvam-105b",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0
                )
                analysis = response.choices[0].message.content
                
                with self._pool.connection() as conn:
                    conn.execute("UPDATE error_logs SET ai_analysis = %s WHERE id = %s", (analysis, error_id))
            except Exception as e:
                logger.warning("Agent analysis failed", exc_info=True)
            finally:
                self._agent_queue.task_done()

    def _enqueue(self, fn, *args, **kwargs) -> None:
        if self._closing:
            return
        try:
            self._queue.put_nowait((fn, args, kwargs))
        except queue.Full:
            self._dropped += 1
            if self._dropped in (1, 100) or self._dropped % 1000 == 0:
                logger.warning("logging queue full — dropped %d events", self._dropped)
        except Exception:
            pass  # never block caller

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def flush(self, timeout: float = 5.0) -> None:
        """Wait for queued writes to drain (used at shutdown).

        queue.join() counts unfinished tasks, so it only unblocks after every
        task_done() is called — i.e. after the DB write commits, not just after
        the item is dequeued. Runs on a daemon thread to honour the timeout.
        """
        t = threading.Thread(target=self._queue.join, daemon=True)
        t.start()
        t.join(timeout)

    def close(self, timeout: float = 5.0) -> None:
        """Drain, stop the worker, and close the pool. Safe to call once at shutdown."""
        if self._closing:
            return
        self._closing = True
        self.flush(timeout)
        try:
            self._queue.put_nowait(self._STOP)
            self._agent_queue.put_nowait(self._STOP)
        except Exception:
            pass
        self._thread.join(timeout=timeout)
        self._agent_thread.join(timeout=timeout)
        try:
            self._pool.close()
        except Exception:
            logger.debug("pool close error", exc_info=True)
        if self._dropped:
            logger.warning("logging service closed — %d events were dropped total", self._dropped)

    def ping(self) -> bool:
        """Readiness probe: can we acquire a connection and run a trivial query?"""
        try:
            with self._pool.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            logger.debug("logging service ping failed", exc_info=True)
            return False

    # ── Public write API (non-blocking) ───────────────────────────────────────

    def log_request(self, *, request_id: str, user_id: str, method: str, endpoint: str,
                    status_code: int, duration_ms: int, success: bool = True,
                    metadata: dict | None = None) -> None:
        self._enqueue(self._write_request, request_id, user_id, method, endpoint,
                      status_code, duration_ms, success, metadata or {})
        # NOTE: we deliberately do NOT create/update a doctor_analytics row per request.
        # Counting every HTTP identity as a "doctor" was the phantom-doctor source (an
        # X-User-Id header of "adm"/"dashboard", or the "anonymous" fallback, became a
        # top-ranked doctor with thousands of "requests"). Doctor rows are now only written
        # on genuine clinical events: session create / finalize (update_doctor) and AI usage
        # (_bump_doctor_ai). Per-doctor request counts, when needed, come from app_logs.

    def log_error(self, *, request_id: str | None = None, user_id: str | None = None,
                  endpoint: str | None = None, error_type: str, error_message: str,
                  stack_trace: str | None = None, severity: str = "error",
                  source: str = "backend", browser_info: dict | None = None) -> None:
        self._enqueue(self._write_error, request_id, user_id, endpoint, error_type,
                      error_message, stack_trace, severity, source, browser_info or {})

    def log_ai(self, *, session_id: str | None = None, user_id: str | None = None,
               model: str, agent: str | None = None, prompt_tokens: int | None = None,
               completion_tokens: int | None = None, total_tokens: int | None = None,
               latency_ms: int, success: bool = True, retry_count: int = 0,
               error_message: str | None = None) -> None:
        cost = estimate_cost(prompt_tokens, completion_tokens)
        self._enqueue(self._write_ai, session_id, user_id, model, agent, prompt_tokens,
                      completion_tokens, total_tokens, cost, latency_ms, success,
                      retry_count, error_message)
        if user_id:
            self._enqueue(self._bump_doctor_ai, user_id)

    def update_doctor(self, *, user_id: str, increment_sessions: int = 0,
                      increment_reports: int = 0, feature: str | None = None,
                      full_name: str | None = None, email: str | None = None) -> None:
        self._enqueue(self._upsert_doctor, user_id, increment_sessions,
                      increment_reports, feature, full_name, email)

    def log_feedback(self, *, user_id: str, session_id: str | None = None,
                     rating: int | None = None, feedback_text: str | None = None,
                     feature: str | None = None, metadata: dict | None = None) -> None:
        self._enqueue(self._write_feedback, user_id, session_id, rating,
                      feedback_text, feature, metadata or {})

    # ── Private DB writers ─────────────────────────────────────────────────────

    def _write_request(self, request_id, user_id, method, endpoint, status_code,
                       duration_ms, success, metadata):
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO app_logs(request_id, user_id, method, endpoint, status_code,"
                " duration_ms, success, metadata, created_at)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (request_id, user_id, method, endpoint, status_code, duration_ms,
                 success, json.dumps(metadata), _now()))

    def _write_error(self, request_id, user_id, endpoint, error_type, error_message,
                     stack_trace, severity, source, browser_info):
        with self._pool.connection() as conn:
            res = conn.execute(
                "INSERT INTO error_logs(request_id, user_id, endpoint, error_type,"
                " error_message, stack_trace, severity, source, browser_info, created_at)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (request_id, user_id, endpoint, error_type, error_message,
                 stack_trace, severity, source, json.dumps(browser_info), _now()))
            error_id = res.fetchone()[0]
            
            if severity in ("error", "critical") and stack_trace:
                try:
                    self._agent_queue.put_nowait((error_id, error_type, error_message, stack_trace, source))
                except Exception:
                    pass

    def _write_ai(self, session_id, user_id, model, agent, prompt_tokens,
                  completion_tokens, total_tokens, cost_usd, latency_ms,
                  success, retry_count, error_message):
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO ai_analytics(session_id, user_id, model, agent,"
                " prompt_tokens, completion_tokens, total_tokens, cost_usd,"
                " latency_ms, success, retry_count, error_message, created_at)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (session_id, user_id, model, agent, prompt_tokens, completion_tokens,
                 total_tokens, cost_usd, latency_ms, success, retry_count,
                 error_message, _now()))

    def _upsert_doctor(self, user_id, inc_sessions, inc_reports, feature,
                       full_name=None, email=None):
        with self._pool.connection() as conn:
            # COALESCE(EXCLUDED, existing) so a later call without identity never wipes a
            # name/email we already learned — the admin Doctors view shows real identities
            # (e.g. dr@hospital.org) in jwt mode instead of a bare auth.users UUID.
            conn.execute(
                "INSERT INTO doctor_analytics(user_id, full_name, email, first_seen, last_active,"
                " total_sessions, total_reports)"
                " VALUES(%s, %s, %s, now(), now(), %s, %s)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                "   last_active = now(),"
                "   full_name = COALESCE(EXCLUDED.full_name, doctor_analytics.full_name),"
                "   email = COALESCE(EXCLUDED.email, doctor_analytics.email),"
                "   total_sessions = doctor_analytics.total_sessions + EXCLUDED.total_sessions,"
                "   total_reports  = doctor_analytics.total_reports  + EXCLUDED.total_reports",
                [user_id, full_name, email, inc_sessions, inc_reports])
            if feature:
                conn.execute(
                    "UPDATE doctor_analytics SET"
                    "  feature_usage = jsonb_set("
                    "    feature_usage, ARRAY[%s],"
                    "    to_jsonb(COALESCE((feature_usage->>%s)::int, 0) + 1)"
                    "  ) WHERE user_id = %s",
                    [feature, feature, user_id])

    def _bump_doctor_requests(self, user_id):
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO doctor_analytics(user_id, first_seen, last_active, total_requests)"
                " VALUES(%s, now(), now(), 1)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                "   last_active = now(),"
                "   total_requests = doctor_analytics.total_requests + 1",
                [user_id])

    def _bump_doctor_ai(self, user_id):
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO doctor_analytics(user_id, first_seen, last_active, total_ai_calls)"
                " VALUES(%s, now(), now(), 1)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                "   last_active = now(),"
                "   total_ai_calls = doctor_analytics.total_ai_calls + 1",
                [user_id])

    def _write_feedback(self, user_id, session_id, rating, feedback_text, feature, metadata):
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO user_feedback(user_id, session_id, rating, feedback_text,"
                " feature, metadata, created_at)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (user_id, session_id, rating, feedback_text, feature,
                 json.dumps(metadata), _now()))

    # ── Public read API (synchronous — for admin queries only) ─────────────────

    def query_overview(self) -> dict:
        with self._pool.connection() as conn:
            active_24h = conn.execute(
                "SELECT COUNT(*) FROM doctor_analytics"
                f" WHERE last_active > now() - interval '24 hours' AND {_REAL_DOCTOR_SQL}").fetchone()[0]
            totals = conn.execute(
                "SELECT COALESCE(SUM(total_sessions),0), COALESCE(SUM(total_reports),0)"
                f" FROM doctor_analytics WHERE {_REAL_DOCTOR_SQL}").fetchone()
            req = conn.execute(
                "SELECT COUNT(*), COALESCE(AVG(duration_ms),0)::int,"
                " SUM(CASE WHEN NOT success THEN 1 ELSE 0 END)"
                " FROM app_logs WHERE created_at > now() - interval '24 hours'").fetchone()
            ai = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(cost_usd),0)"
                " FROM ai_analytics WHERE created_at > now() - interval '24 hours'").fetchone()
            top_docs = conn.execute(
                "SELECT user_id, full_name, total_sessions, total_requests, last_active"
                f" FROM doctor_analytics WHERE {_REAL_DOCTOR_SQL}"
                " ORDER BY total_sessions DESC, total_requests DESC"
                " LIMIT 5").fetchall()
            recent_err = conn.execute(
                "SELECT created_at, error_type, error_message, source, severity"
                " FROM error_logs ORDER BY created_at DESC LIMIT 8").fetchall()
        total_req_24h = req[0]
        failed = req[2] or 0
        return {
            "kpis": {
                "total_requests_24h": total_req_24h,
                "error_rate_pct": round(failed / total_req_24h * 100, 2) if total_req_24h else 0.0,
                "avg_latency_ms": req[1],
                "active_doctors_24h": active_24h,
                "ai_calls_24h": ai[0],
                "ai_cost_24h_usd": float(ai[1]),
                "total_sessions": int(totals[0]),
                "total_reports": int(totals[1]),
            },
            "top_doctors": [{
                "user_id": r[0], "full_name": r[1], "total_sessions": r[2],
                "total_requests": r[3], "last_active": str(r[4]),
            } for r in top_docs],
            "recent_errors": [{
                "created_at": str(r[0]), "error_type": r[1], "error_message": r[2],
                "source": r[3], "severity": r[4],
            } for r in recent_err],
        }

    def query_doctors(self, page: int = 1, limit: int = 20, search: str = "") -> dict:
        offset = (page - 1) * limit
        with self._pool.connection() as conn:
            # Always exclude infra/dev identities; AND the search on top when present.
            if search:
                where = f"WHERE {_REAL_DOCTOR_SQL} AND (user_id ILIKE %s OR full_name ILIKE %s OR email ILIKE %s)"
                params_search = [f"%{search}%"] * 3
            else:
                where = f"WHERE {_REAL_DOCTOR_SQL}"
                params_search = []
            total = conn.execute(
                f"SELECT COUNT(*) FROM doctor_analytics {where}",
                params_search).fetchone()[0]
            rows = conn.execute(
                f"SELECT user_id, full_name, email, organization, first_seen, last_active,"
                f" total_sessions, total_requests, total_ai_calls, total_reports,"
                f" total_session_seconds, feature_usage"
                f" FROM doctor_analytics {where}"
                f" ORDER BY last_active DESC LIMIT %s OFFSET %s",
                params_search + [limit, offset]).fetchall()
        doctors = [{
            "user_id": r[0], "full_name": r[1], "email": r[2], "organization": r[3],
            "first_seen": str(r[4]), "last_active": str(r[5]),
            "total_sessions": r[6], "total_requests": r[7],
            "total_ai_calls": r[8], "total_reports": r[9],
            "total_session_seconds": r[10], "feature_usage": r[11] or {},
        } for r in rows]
        return {"doctors": doctors, "total": total, "page": page, "limit": limit}

    def query_logs(self, *, page: int = 1, limit: int = 50, user_id: str = "",
                   endpoint: str = "", status: str = "",
                   from_dt: str = "", to_dt: str = "") -> dict:
        offset = (page - 1) * limit
        clauses, params = [], []
        if user_id:
            clauses.append("user_id = %s"); params.append(user_id)
        if endpoint:
            clauses.append("endpoint ILIKE %s"); params.append(f"%{endpoint}%")
        if status:
            if status == "error":
                clauses.append("success = false")
            elif status == "ok":
                clauses.append("success = true")
            else:
                try: clauses.append("status_code = %s"); params.append(int(status))
                except ValueError: pass
        if from_dt:
            clauses.append("created_at >= %s"); params.append(from_dt)
        if to_dt:
            clauses.append("created_at <= %s"); params.append(to_dt)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._pool.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM app_logs {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT id, request_id, user_id, method, endpoint, status_code,"
                f" duration_ms, success, metadata, created_at"
                f" FROM app_logs {where}"
                f" ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset]).fetchall()
        logs = [{
            "id": r[0], "request_id": r[1], "user_id": r[2], "method": r[3],
            "endpoint": r[4], "status_code": r[5], "duration_ms": r[6],
            "success": r[7], "metadata": r[8] or {}, "created_at": str(r[9]),
        } for r in rows]
        return {"logs": logs, "total": total, "page": page, "limit": limit}

    def query_errors(self, *, page: int = 1, limit: int = 50, severity: str = "",
                     source: str = "", from_dt: str = "", to_dt: str = "") -> dict:
        offset = (page - 1) * limit
        clauses, params = [], []
        if severity:
            clauses.append("severity = %s"); params.append(severity)
        if source:
            clauses.append("source = %s"); params.append(source)
        if from_dt:
            clauses.append("created_at >= %s"); params.append(from_dt)
        if to_dt:
            clauses.append("created_at <= %s"); params.append(to_dt)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._pool.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM error_logs {where}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT id, request_id, user_id, endpoint, error_type, error_message,"
                f" stack_trace, severity, source, browser_info, created_at, ai_analysis"
                f" FROM error_logs {where}"
                f" ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset]).fetchall()
        errors = [{
            "id": r[0], "request_id": r[1], "user_id": r[2], "endpoint": r[3],
            "error_type": r[4], "error_message": r[5], "stack_trace": r[6],
            "severity": r[7], "source": r[8], "browser_info": r[9] or {},
            "created_at": str(r[10]),
            "ai_analysis": r[11],
        } for r in rows]
        return {"errors": errors, "total": total, "page": page, "limit": limit}

    def query_error_groups(self, *, limit: int = 50, severity: str = "",
                            source: str = "", from_dt: str = "", to_dt: str = "") -> dict:
        """Distinct error signatures with occurrence counts — the debuggable view.

        Groups by (type, source, severity, message prefix) so a repeated failure collapses
        into ONE row showing how many times it happened and when it first/last occurred,
        instead of flooding the timeline. Carries the most-recent stack trace + agent
        analysis as a representative sample so a group is still actionable.
        """
        clauses, params = [], []
        if severity:
            clauses.append("severity = %s"); params.append(severity)
        if source:
            clauses.append("source = %s"); params.append(source)
        if from_dt:
            clauses.append("created_at >= %s"); params.append(from_dt)
        if to_dt:
            clauses.append("created_at <= %s"); params.append(to_dt)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"SELECT error_type, source, severity, LEFT(error_message, 120) AS sig,"
                f" COUNT(*) AS n, MIN(created_at) AS first_seen, MAX(created_at) AS last_seen,"
                f" (array_agg(stack_trace ORDER BY created_at DESC)"
                f"    FILTER (WHERE stack_trace IS NOT NULL))[1] AS sample_stack,"
                f" (array_agg(ai_analysis ORDER BY created_at DESC)"
                f"    FILTER (WHERE ai_analysis IS NOT NULL))[1] AS sample_ai,"
                f" (array_agg(endpoint ORDER BY created_at DESC)"
                f"    FILTER (WHERE endpoint IS NOT NULL))[1] AS sample_endpoint,"
                f" MAX(id) AS sample_id"
                f" FROM error_logs {where}"
                f" GROUP BY error_type, source, severity, LEFT(error_message, 120)"
                f" ORDER BY COUNT(*) DESC, MAX(created_at) DESC LIMIT %s",
                params + [limit]).fetchall()
        groups = [{
            "error_type": r[0], "source": r[1], "severity": r[2], "message": r[3],
            "count": r[4], "first_seen": str(r[5]), "last_seen": str(r[6]),
            "sample_stack": r[7], "sample_ai": r[8], "sample_endpoint": r[9],
            "sample_id": r[10],
        } for r in rows]
        return {"groups": groups, "total": len(groups)}

    def query_ai_analytics(self, *, from_dt: str = "", to_dt: str = "") -> dict:
        clauses, params = [], []
        if from_dt:
            clauses.append("created_at >= %s"); params.append(from_dt)
        if to_dt:
            clauses.append("created_at <= %s"); params.append(to_dt)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self._pool.connection() as conn:
            summary = conn.execute(
                f"SELECT COUNT(*),"
                f" COALESCE(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END), 0),"
                f" COALESCE(AVG(latency_ms), 0)::int,"
                f" COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms), 0)::int,"
                f" COALESCE(SUM(total_tokens), 0),"
                f" COALESCE(SUM(cost_usd), 0),"
                f" COALESCE(AVG(retry_count), 0)"
                f" FROM ai_analytics {where}", params).fetchone()
            by_agent = conn.execute(
                f"SELECT COALESCE(agent, 'unknown'), COUNT(*),"
                f" COALESCE(AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END), 0),"
                f" COALESCE(AVG(latency_ms), 0)::int,"
                f" COALESCE(SUM(total_tokens), 0),"
                f" COALESCE(SUM(cost_usd), 0)"
                f" FROM ai_analytics {where}"
                f" GROUP BY agent ORDER BY COUNT(*) DESC", params).fetchall()
            by_model = conn.execute(
                f"SELECT model, COUNT(*),"
                f" COALESCE(AVG(latency_ms), 0)::int,"
                f" COALESCE(SUM(total_tokens), 0),"
                f" COALESCE(SUM(cost_usd), 0)"
                f" FROM ai_analytics {where}"
                f" GROUP BY model ORDER BY COUNT(*) DESC", params).fetchall()
            recent = conn.execute(
                f"SELECT created_at, model, agent, total_tokens, cost_usd,"
                f" latency_ms, success, retry_count"
                f" FROM ai_analytics {where}"
                f" ORDER BY created_at DESC LIMIT 50", params).fetchall()
        return {
            "summary": {
                "total_calls": summary[0],
                "success_rate_pct": round(float(summary[1]) * 100, 2),
                "avg_latency_ms": summary[2],
                "p95_latency_ms": summary[3],
                "total_tokens": int(summary[4]),
                "total_cost_usd": float(summary[5]),
                "avg_retry_count": round(float(summary[6]), 2),
            },
            "by_agent": [{"agent": r[0], "calls": r[1],
                          "success_pct": round(float(r[2]) * 100, 2),
                          "avg_latency_ms": r[3], "total_tokens": int(r[4]),
                          "total_cost_usd": float(r[5])} for r in by_agent],
            "by_model": [{"model": r[0], "calls": r[1], "avg_latency_ms": r[2],
                          "total_tokens": int(r[3]), "total_cost_usd": float(r[4])} for r in by_model],
            "recent_calls": [{"created_at": str(r[0]), "model": r[1], "agent": r[2],
                              "total_tokens": r[3], "cost_usd": float(r[4] or 0),
                              "latency_ms": r[5], "success": r[6],
                              "retry_count": r[7]} for r in recent],
        }

    def query_feedback(self, *, page: int = 1, limit: int = 20) -> dict:
        offset = (page - 1) * limit
        with self._pool.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM user_feedback").fetchone()[0]
            rows = conn.execute(
                "SELECT id, user_id, session_id, rating, feedback_text, feature, created_at"
                " FROM user_feedback ORDER BY created_at DESC LIMIT %s OFFSET %s",
                [limit, offset]).fetchall()
            avg_rating = conn.execute(
                "SELECT COALESCE(AVG(rating), 0) FROM user_feedback WHERE rating IS NOT NULL"
            ).fetchone()[0]
            dist_rows = conn.execute(
                "SELECT rating, COUNT(*) FROM user_feedback"
                " WHERE rating IS NOT NULL GROUP BY rating").fetchall()
        rating_distribution = {str(r[0]): r[1] for r in dist_rows}
        feedback = [{"id": r[0], "user_id": r[1], "session_id": r[2], "rating": r[3],
                     "feedback_text": r[4], "feature": r[5], "created_at": str(r[6])}
                    for r in rows]
        return {
            "stats": {
                "total": total,
                "avg_rating": round(float(avg_rating), 2),
                "rating_distribution": rating_distribution,
            },
            "feedback": feedback, "total": total, "page": page, "limit": limit,
        }

    def query_system_health(self) -> dict:
        with self._pool.connection() as conn:
            lat = conn.execute(
                "SELECT"
                "  COALESCE(AVG(duration_ms),0)::int,"
                "  COALESCE(percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ms),0)::int,"
                "  COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms),0)::int,"
                "  COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms),0)::int,"
                "  COALESCE(MAX(duration_ms),0),"
                "  COUNT(*)"
                " FROM app_logs WHERE created_at > now() - interval '1 hour'").fetchone()
            err_summary = conn.execute(
                "SELECT error_type, COUNT(*)"
                " FROM error_logs WHERE created_at > now() - interval '24 hours'"
                " GROUP BY error_type ORDER BY COUNT(*) DESC LIMIT 20").fetchall()
            slowest = conn.execute(
                "SELECT endpoint, COALESCE(AVG(duration_ms),0)::int,"
                " COALESCE(MAX(duration_ms),0), COUNT(*)"
                " FROM app_logs WHERE created_at > now() - interval '24 hours'"
                " GROUP BY endpoint ORDER BY AVG(duration_ms) DESC LIMIT 10").fetchall()
        return {
            "latency": {"avg_ms": lat[0], "p50_ms": lat[1], "p95_ms": lat[2],
                        "p99_ms": lat[3], "max_ms": lat[4], "count": lat[5]},
            "error_summary": {r[0]: r[1] for r in err_summary},
            "slowest_endpoints": [{"endpoint": r[0], "avg_ms": r[1], "max_ms": r[2],
                                   "count": r[3]} for r in slowest],
        }


# ── Singleton factory ──────────────────────────────────────────────────────────

_svc: SupabaseLoggingService | _Noop | None = None
_lock = threading.Lock()


def get_logging_service() -> "SupabaseLoggingService | _Noop":
    global _svc
    if _svc is not None:
        return _svc
    with _lock:
        if _svc is not None:
            return _svc
        try:
            from app.config import get_settings
            s = get_settings()
            if s.supabase_db_url:
                _svc = SupabaseLoggingService(s.supabase_db_url, pool_max=s.supabase_pool_max)
            else:
                logger.info("SCRIBE_SUPABASE_DB_URL not set — logging service is a no-op")
                _svc = _Noop()
        except Exception:
            logger.warning("Failed to init logging service; using no-op", exc_info=True)
            _svc = _Noop()
    return _svc
