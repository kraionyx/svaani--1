# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Backend**
```bash
# Install
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Run (dev, auto-reload)
uvicorn app.main:app --reload

# Run (prod-like, no reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Docker (SQLite-backed single container)
docker-compose up
```

**Tests**
```bash
pytest                              # all tests
pytest tests/test_pipeline.py       # single file
pytest tests/test_pipeline.py::test_name  # single test
pytest -x                           # stop on first failure
```

**Frontend (web-app/)**
```bash
cd web-app
npm install
npm run dev          # dev server → http://localhost:5173
npm run build        # build to web-app/dist/ (served by backend at /app)
```

**Generate a PHI encryption key**
```bash
python -c "from app.security.crypto import generate_key_b64 as g; print(g())"
```

## Environment Variables (prefix `SCRIBE_`)

The app boots with no credentials — external calls fall back to mocks. Set these for live behaviour:

| Variable | Purpose |
|---|---|
| `SCRIBE_STORE_BACKEND` | `memory` (default) / `sqlite` / `supabase` |
| `SCRIBE_SQLITE_PATH` | SQLite file path (default `svaani.db`) |
| `SCRIBE_SUPABASE_DB_URL` | libpq connection string (prefer pooler endpoint) |
| `SCRIBE_SUPABASE_URL` | `https://<ref>.supabase.co` — Auth origin; served to the SPA via `/auth/config` |
| `SCRIBE_SUPABASE_ANON_KEY` | anon/public key — browser-safe; required for jwt-mode auth |
| `SCRIBE_SUPABASE_SERVICE_KEY` | service_role JWT — bypasses RLS (server-side only) |
| `SCRIBE_PHI_ENCRYPTION_KEY_B64` | base64 32-byte AES-GCM key; empty = dev no-op |
| `SCRIBE_SARVAM_API_KEY` | Sarvam V3 STT; mocked if unset |
| `SCRIBE_VERTEX_API_KEY` | Gemini express-mode key; LLM disabled if unset |
| `SCRIBE_VERTEX_PROJECT` | Alternative to key (regional residency path) |
| `SCRIBE_VERTEX_LOCATION` | default `asia-south1` (Mumbai, India PHI residency) |
| `SCRIBE_GEMINI_MODEL` | default `gemini-2.5-pro` |
| `SCRIBE_AUTH_MODE` | `dev` (header scaffold) / `jwt` (verified bearer) |
| `SCRIBE_ENVIRONMENT` | `development` (default) / `production` — see startup guard below |
| `SCRIBE_ADMIN_PASSWORD` | password for the `/admin1` dashboard (dev fallback `admin@kraionyx`; prod boot is blocked if left at the default) |
| `SCRIBE_LOG_LEVEL` | `DEBUG`/`INFO`(default)/`WARNING`/`ERROR` |
| `SCRIBE_LOG_JSON` | `true` ⇒ one JSON object per log line (for aggregators) |
| `SCRIBE_DEBUG` | `true` ⇒ tracebacks in 500 responses (DEV ONLY) |
| `SCRIBE_SECURITY_HEADERS` | `true` (default) ⇒ nosniff/X-Frame-Options/Referrer-Policy/HSTS |
| `SCRIBE_ADMIN_AUTH_RATE_LIMIT` / `_WINDOW_S` | per-IP throttle on `/admin1/api/auth` (default 10/60s) |

See `.env.example` for a complete, annotated template.

## Production Hardening

### Startup safety guard (`app/security/startup.py`)
When `SCRIBE_ENVIRONMENT=production`, the app **refuses to boot** on unsafe config:
durable store without a PHI key (would write `PLAINTEXT:`), `auth_mode=dev`, the default
admin password, or localhost-only CORS. In `development` these are logged as warnings
instead. The check runs in the FastAPI `lifespan` startup (`app/main.py`).

### Logging / debugging (`app/logging_config.py`)
`setup_logging()` configures the root logger at `SCRIBE_LOG_LEVEL` (default INFO — Python's
implicit WARNING previously hid all `logger.info` lines). Every log line carries the current
request-id (`rid=…`) via a `contextvars` ContextVar set in the observability middleware.
`SCRIBE_LOG_JSON=true` switches to structured JSON output.

### Error handling, health, shutdown
- Global exception handlers in `app/main.py` map `AccessDenied`→403, `AuthError`→401,
  `IllegalTransition`→409, and any other exception → clean 500 (`{detail, request_id}`;
  traceback only when `SCRIBE_DEBUG`).
- `GET /health` = liveness (no secrets); `GET /health/ready` = readiness (probes store +
  logging DB, 503 when not ready).
- The `lifespan` shutdown flushes the logging queue and closes every connection pool.
- WebSocket `/ws/consultation` is authenticated: `?token=` (jwt mode) or `?user_id=&role=`
  (dev mode); unauthorized handshakes are closed with code 4401.

### User auth (Supabase: Google + email/password)
`SCRIBE_AUTH_MODE=jwt` turns on real per-user login. The React SPA bootstraps its Supabase
client from `GET /auth/config` (public; returns `supabase_url` + `supabase_anon_key` from
the backend `.env`, so creds live in one place), shows `LoginPage` (Google OAuth + email/
password), and sends the Supabase access token as `Authorization: Bearer …` on REST and as
`?token=…` on the consultation WebSocket.

**Token verification** (`app/security/auth.py`) branches on the token's `alg`:
- `RS256/ES256` → JWKS (`SCRIBE_JWT_JWKS_URL`, or auto-derived from `SCRIBE_SUPABASE_URL`);
- `HS256` with `SCRIBE_JWT_SECRET` set → fast local verify (the Supabase JWT secret);
- `HS256` with **no secret** → remote verify via Supabase `GET /auth/v1/user` using the
  anon key (works out-of-the-box, cached ~60s per token). Paste the JWT secret to upgrade.

The verified `sub` (auth.users UUID) becomes `Principal.id`; every Supabase user is a
`DOCTOR` unless a custom `app_metadata.role` claim says otherwise (ADMIN stays gated by the
separate `/admin1` password). Google login is configured in the Supabase dashboard — no app
secrets needed.

### Per-user data isolation
Every consultation is stamped with `practitioner_id = principal.id` (REST `POST /sessions`
and the WS `start` action; a client-supplied `practitioner_id` is ignored). `GET /sessions`
lists only the caller's own consultations (`store.list_for_practitioner`), and in jwt mode
`_load_session` (app/main.py) blocks cross-user access to a session by id (ADMIN/AUDITOR
excepted). The Supabase `consultations` row carries `practitioner_id` (UUID FK), a
`handle_new_user()` trigger auto-creates a `profiles` row on signup, and RLS scopes
consultations to the owner (`practitioner_id = auth.uid()`). Tests force `auth_mode=dev`
+ `memory` store via `tests/conftest.py`, so the jwt-mode `.env` never breaks them.

## Architecture

### Two Storage Abstractions

There are two completely separate persistence responsibilities, each with three backends:

**1. `SessionStore`** (`app/store*.py`) — clinical sessions  
Stores `ConsultationSession` + `PipelineResult`. Backend selected by `SCRIBE_STORE_BACKEND`:
- `SessionStore` (memory, default)
- `SqlSessionStore` (sqlite — single `sessions` table)
- `SupabaseSessionStore` (postgres — writes to `consultations` in `supabase/schema.sql`)

**2. `Repository`** (`app/data/repo*.py`) — operational data  
Stores reviews, admin queue, improvement pipeline, prompt/model versions, document templates, edits, flags, telemetry. Uses a simple KV table `op_records(kind, rid, payload)` for both SQLite and Postgres backends — intentionally avoids the structured schema to keep the two responsibilities separate.

Factory: `get_store()` / `get_repo()` — call these; never instantiate directly.

### PHI Encryption

`FieldCipher` (`app/security/crypto.py`) wraps AES-256-GCM. **The database never holds plaintext clinical content.** Session and result JSON are serialised, encrypted, and stored as `session_enc`/`result_enc`. PHI kinds (`rendered_doc`, `edit`) in the repo are also encrypted. In dev (no key set), the cipher is a no-op that prepends `PLAINTEXT:` — never use with real PHI.

### Pipeline

`app/pipeline/orchestrator.py` → `run_pipeline(raw_transcript, template, settings)`

Default path (single-pass, `SCRIBE_SINGLE_PASS_LLM=true`):
1. `combined.py` — one Gemini call produces clean transcript + extraction + risk together
2. `note.py` — deterministically renders the note from the extraction against the template
3. Falls back to staged path (clean → extract → risk separately) on any error

The pipeline **never authors prescriptions**. Medicines discussed are captured under `medications_discussed` with `authoritative=false`.

### Session State Machine

`ConsultationSession.state` follows strict transitions defined in `ALLOWED_TRANSITIONS` (`app/schemas/session.py`):

```
listening → processing → draft → in_review → edited → approved → finalized
                    ↘ escalation_required ←────────────────────────────────
```

Only `FINALIZED` sessions are exportable. `session.transition(new_state)` raises `IllegalTransition` for illegal moves.

### Multi-tenant Schema (`supabase/schema.sql`)

16 tables. Every entity is scoped by `hospital_id`. RLS enforces tenant isolation for browser clients. The server uses `service_role` (bypasses RLS). Helper SQL functions `current_hospital_id()` / `current_app_role()` drive all policies.

Key tables: `consultations` (core clinical record), `audit_events` (append-only hash chain — UPDATE/DELETE blocked by Postgres rules), `consultation_reviews` → auto-triggers `admin_reviews` insert on `needs_improvement`.

### Auth & RBAC

`app/security/auth.py` resolves a `Principal(id, role)`. Dev mode reads `X-User-Id` / `X-Role` headers. JWT mode verifies HS256 (shared secret) or RS256 (JWKS/Keycloak).

Permissions are checked via `require_permission(principal, Permission.X)` → raises `AccessDenied`. Role map is in `app/security/rbac.py`.

### Frontend

Two UIs served by the backend:
- `/ui` → `web/` (legacy static HTML)
- `/app` → `web-app/dist/` (React/Vite SPA — primary)

The SPA dev server runs separately on `:5173`. CORS is configured via `SCRIBE_CORS_ALLOW_ORIGINS` to allow both origins.

WebSocket endpoint: `GET /ws/consultation` — streams audio chunks, emits partial transcripts, triggers the diarized batch pass on stop.

### Test Patterns

Tests use `starlette.testclient.TestClient` against the FastAPI app with no mocking of internal logic — only external providers (Sarvam, Vertex) are mocked. `conftest.py` provides the ENT transcript + extraction fixtures. `pytest.ini_options` promotes `DeprecationWarning` to errors so the test suite stays clean.

### Observability

`app/observability.py` wires a middleware that adds `X-Request-ID`, logs every request, and (if `prometheus-client` is installed) increments counters/histograms. Metrics exposed at `GET /metrics`. Audit events are appended to `audit.log.jsonl` (local) and optionally to the `audit_events` Supabase table.
