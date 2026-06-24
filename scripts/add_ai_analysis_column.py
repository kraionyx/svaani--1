import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
try:
    import psycopg
except ImportError:
    psycopg = None

def main():
    settings = get_settings()
    if not psycopg:
        try:
            from psycopg_pool import ConnectionPool
            with ConnectionPool(settings.supabase_db_url, min_size=1, max_size=1, open=True) as pool:
                with pool.connection() as conn:
                    conn.execute("ALTER TABLE error_logs ADD COLUMN ai_analysis text;")
                    print("Added column via pool")
        except Exception as e:
            print("Error via pool:", e)
    else:
        with psycopg.connect(settings.supabase_db_url) as conn:
            conn.execute("ALTER TABLE error_logs ADD COLUMN ai_analysis text;")
            conn.commit()
            print("Added column via psycopg")

if __name__ == "__main__":
    main()
