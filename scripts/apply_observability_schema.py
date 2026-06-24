"""Apply ONLY the observability/logging tables (section 12 of supabase/schema.sql)
to the configured Supabase database. Idempotent — every statement is
`create ... if not exists`, so it is safe to re-run.

Usage:  python scripts/apply_observability_schema.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402

SCHEMA = ROOT / "supabase" / "schema.sql"
MARKER = "create table if not exists doctor_analytics"


def main() -> int:
    settings = get_settings()
    db_url = settings.supabase_db_url
    if not db_url:
        print("SCRIBE_SUPABASE_DB_URL not set — nothing to do.")
        return 1

    sql = SCHEMA.read_text(encoding="utf-8")
    idx = sql.find(MARKER)
    if idx == -1:
        print(f"Could not find marker '{MARKER}' in {SCHEMA}")
        return 1
    ddl = sql[idx:]
    print(f"Applying {ddl.count('create table')} tables + "
          f"{ddl.count('create index')} indexes to Supabase…")

    import psycopg

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()
        # Verify
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema='public'"
                " AND table_name IN"
                " ('doctor_analytics','app_logs','error_logs','ai_analytics','user_feedback')"
                " ORDER BY table_name")
            present = [r[0] for r in cur.fetchall()]
    print("Tables present:", ", ".join(present))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
