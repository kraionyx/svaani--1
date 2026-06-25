"""Resilient Postgres connection-pool factory (shared by all DB-backed services).

Supabase fronts Postgres with a connection pooler (pgbouncer-style) that silently
closes idle/long-lived server connections. A plain ``ConnectionPool`` hands those dead
connections straight to the caller, producing the
``OperationalError: server closed the connection unexpectedly`` crash seen in prod.

``make_pool`` hardens every pool against that with three settings:

* ``check=ConnectionPool.check_connection`` — validate a connection on checkout and
  transparently discard + replace a dead one (one cheap round-trip, no caller-visible error).
* ``max_idle`` — proactively retire connections idle longer than the pooler's own idle
  timeout, so we rarely even reach the ``check`` path.
* ``max_lifetime`` — cap absolute connection age so a connection never outlives the
  pooler's server-side recycle.

``run`` wraps a unit of work with one automatic retry: if a connection still turns out
to be stale at *use* time (the race between checkout and first statement), we reset the
pool and try once more before surfacing the error.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from psycopg import OperationalError
from psycopg_pool import ConnectionPool

logger = logging.getLogger("svaani.pgpool")

T = TypeVar("T")

# Retire idle connections well before Supabase's pooler does (its default idle window is
# minutes). 120s keeps the pool warm under load but cold connections never go stale.
_MAX_IDLE_S = 120.0
# Absolute connection age cap — below the pooler's server-side recycle.
_MAX_LIFETIME_S = 1800.0


def make_pool(
    conninfo: str,
    *,
    min_size: int = 1,
    max_size: int = 5,
    timeout: float = 10.0,
    open: bool = True,
) -> ConnectionPool:
    """Create a health-checked ConnectionPool tuned for the Supabase pooler."""
    return ConnectionPool(
        conninfo,
        min_size=min_size,
        max_size=max_size,
        open=open,
        timeout=timeout,
        check=ConnectionPool.check_connection,
        max_idle=_MAX_IDLE_S,
        max_lifetime=_MAX_LIFETIME_S,
    )


def run(pool: ConnectionPool, fn: Callable[[Any], T]) -> T:
    """Run ``fn(conn)`` inside a pooled connection, retrying once on a stale connection.

    ``check`` on checkout catches almost every dead connection, but a connection can still
    be dropped in the window between checkout and the first statement. When that surfaces as
    an ``OperationalError``, we discard the broken pool state and retry exactly once.
    """
    try:
        with pool.connection() as conn:
            return fn(conn)
    except OperationalError:
        logger.warning("stale DB connection; resetting pool and retrying once", exc_info=True)
        try:
            pool.check()  # prune dead connections from the pool
        except Exception:  # noqa: BLE001 — best-effort; the retry below is the real recovery
            logger.debug("pool.check() during recovery failed", exc_info=True)
        with pool.connection() as conn:
            return fn(conn)
