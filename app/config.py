"""Application configuration (pydantic-settings).

All external credentials and tunables come from environment variables (prefix
``SCRIBE_``) or a ``.env`` file — nothing is hardcoded. The app boots and the test
suite run with NO credentials set: Sarvam/Vertex calls fall back to deterministic
mocks, and PHI redaction degrades to a regex redactor.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCRIBE_", env_file=".env", extra="ignore")

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "Svaani AI Medical Scribe"
    app_version: str = "0.1.0"
    # 'development' (default) | 'production'. In production the startup guard
    # (app.security.startup.validate_production) refuses to boot on unsafe config
    # (PHI plaintext no-op, dev header-auth, default admin password, localhost CORS).
    environment: str = "development"
    # Comma-separated browser origins allowed to call the API. The frontend is now a
    # standalone static app served on its own port (default :5173), so the API must
    # opt that origin into CORS. Same-origin (:8000) is kept for the bundled UI.
    cors_allow_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    # ── Sarvam V3 STT & AI Agent ──────────────────────────────────────────────
    # Real-time/stream → immediate transcript (no speaker labels).
    # Batch API (with_diarization) → accurate, speaker-labeled transcript.
    sarvam_api_key: str = ""
    agent_api_key: str = ""
    sarvam_stt_model: str = "saaras:v3"        # saaras:v3 = speech→English
    # Capture mode. 'codemix' keeps the spoken words (Indic words romanized, English kept)
    # so Telugu/code-mixed nouns survive instead of being force-translated and mangled
    # (e.g. "mamidi kaya" -> "Vermicelli"); the LLM still writes an English note. Other
    # options: 'translate' (everything→English), 'transcribe' (native script), 'translit',
    # 'verbatim'. Override via SCRIBE_SARVAM_MODE.
    sarvam_mode: str = "codemix"
    sarvam_language_code: str = "unknown"      # 'unknown' → auto-detect input language
    sarvam_diarize: bool = True                # use Batch API for doctor/patient labels
    sarvam_num_speakers: int | None = None     # None = auto-detect; set to an int to hint Sarvam
    sarvam_poll_interval_s: int = 1            # batch-job poll cadence; lower = less tail latency
    sarvam_batch_timeout_s: int = 600
    # Real-time streaming STT (WebSocket consult path). Streaming has no diarization, so
    # the WS handler streams live unlabeled partials, then runs the batch-diarized pass on
    # stop to recover speaker labels (hybrid). Set False to force batch-at-stop only.
    streaming_stt: bool = True
    sarvam_streaming_model: str = "saaras:v3"  # streaming model (saaras:v3 = state-of-the-art)
    # On stop, how long to wait for the batch-diarized pass before falling back to the
    # live (already-captured) streamed segments. Bounds the post-consult wait so a slow
    # diarization job never blocks the draft — speaker labels are an enhancement, not a gate.
    streaming_diarize_timeout_s: int = 45
    # Hybrid finalize: generate a fast draft from the live transcript first, then auto-refine
    # the note/extraction/transcript from the accurate diarized transcript when it's ready.
    hybrid_refine: bool = True
    # Overall cap on streaming the note's narrated prose, so one slow section never hangs it.
    note_stream_timeout_s: int = 30

    # ── Vertex AI / Gemini (Medical Understanding LLM) ───────────────────────
    vertex_api_key: str = ""                   # express-mode API key (genai api_key=...)
    vertex_project: str = ""                   # OR project+location (regional residency)
    vertex_location: str = "asia-south1"       # Mumbai — India PHI residency (DPDPA)
    gemini_model: str = "gemini-3.5-flash"     # newest Flash; ~3x faster than 2.5-flash here. Override via SCRIBE_GEMINI_MODEL.
    llm_temperature: float = 0.0               # deterministic structuring; we never "create"
    llm_max_output_tokens: int = 8192
    # Gemini "thinking" budget in tokens. 0 disables thinking entirely on Flash/
    # Flash-Lite (lowest latency for pure structuring); -1 = dynamic; Pro ignores 0
    # and clamps to its minimum (the client self-heals a 400 by retrying without it).
    # Default 0 for the fastest structuring path. Override via SCRIBE_LLM_THINKING_BUDGET.
    llm_thinking_budget: int = 0
    # Latency: when True, clean + extract + risk are produced in ONE Gemini call instead
    # of three (the dominant cost is per-call round-trip latency, not tokens). Falls back
    # to the staged path automatically on any error. Set False to force the staged path.
    single_pass_llm: bool = True

    # ── Conversation intelligence (Goals 1-5) ───────────────────────────────
    # Resolve speaker relationships + the referenced patient ("patient = son, not the
    # mother who is speaking"). Deterministic cue rules always run; an LLM sharpens them
    # when configured. Off => legacy behaviour (speaker order = roles).
    resolve_subjects: bool = True
    # Complexity score above which a consult is flagged Complex (Goal 2) and Auto mode
    # escalates to batch (Goal 3).
    complexity_threshold: float = 0.6
    # Auto mode: let complexity choose real-time vs batch instead of a fixed mode (Goal 3).
    auto_inference_mode: bool = False
    # Default mode when auto is off ('realtime' | 'batch').
    default_inference_mode: str = "realtime"
    # Confidence-band thresholds for the accuracy indicator (Goal 4).
    confidence_high_threshold: float = 0.9
    confidence_moderate_threshold: float = 0.75
    # AI consultation editor (Goal 11) — natural-language section edits, preview-then-apply.
    ai_edit_enabled: bool = True

    # ── Validation thresholds ────────────────────────────────────────────────
    stt_low_confidence_threshold: float = 0.6
    drop_ungrounded_fields: bool = True        # False => ungrounded items flagged, not dropped
    # When a Medical LLM is configured, rewrite each note section's grounded facts
    # into clinical prose (faithful rephrasing only — never adds content). With no
    # LLM the deterministic renderer's text stands. Set False to keep raw structure.
    narrative_notes: bool = True

    # ── Persistence ──────────────────────────────────────────────────────────
    # 'memory' (default, in-process), 'sqlite' (durable, PHI encrypted at rest via
    # FieldCipher), or 'supabase' (durable Postgres; PHI still encrypted at rest in
    # *_enc columns). Sessions survive restarts when 'sqlite'/'supabase'.
    store_backend: str = "memory"
    sqlite_path: str = "svaani.db"
    # Supabase (Postgres) backend. Prefer the POOLER connection string (the small demo
    # instance caps total connections). Server-side only — never expose to the browser.
    # Schema lives in supabase/schema.sql.
    supabase_db_url: str = ""                  # postgresql://...:6543/postgres (pooler)
    supabase_url: str = ""                     # https://<ref>.supabase.co (Auth + PostgREST origin)
    supabase_anon_key: str = ""                # anon/public key — SAFE for the browser (served to the SPA)
    supabase_service_key: str = ""             # service_role JWT (server-side only; bypasses RLS)
    supabase_pool_max: int = 5                 # max pooled connections held by the app
    # Supabase Storage: bucket for transcript + note .txt files. Create as a *private*
    # bucket in the Supabase dashboard. Uploads are skipped when URL/key are not set.
    supabase_storage_bucket: str = "consultation-files"

    # ── Auth ─────────────────────────────────────────────────────────────────
    # 'dev' keeps the header scaffold (X-User-Id / X-Role); 'jwt' requires a verified
    # bearer token. For Supabase Auth (Google + email/password) set auth_mode=jwt and
    # SCRIBE_JWT_SECRET to the project's JWT secret (Dashboard → Project Settings → API
    # → JWT Settings). Tokens are HS256-signed with that secret and carry aud="authenticated".
    # Projects migrated to asymmetric signing keys instead expose a JWKS endpoint — set
    # SCRIBE_JWT_JWKS_URL (or leave blank to auto-derive it from SCRIBE_SUPABASE_URL).
    auth_mode: str = "jwt"
    jwt_secret: str = ""                       # HS256 shared secret (Supabase JWT secret / dev)
    jwt_jwks_url: str = ""                      # RS256/ES256 JWKS endpoint (asymmetric keys)
    # Supabase access tokens carry aud="authenticated"; set SCRIBE_JWT_AUDIENCE=authenticated
    # in production to verify it. Left empty by default so tokens without an aud claim (and
    # the existing unit tests) still verify.
    jwt_audience: str = ""
    jwt_issuer: str = ""

    # ── Observability / logging ──────────────────────────────────────────────
    enable_metrics: bool = True                # expose Prometheus /metrics
    # Root log level: DEBUG | INFO | WARNING | ERROR. Default INFO so app logger.info()
    # lines actually appear (Python's implicit default is WARNING, which hid them).
    log_level: str = "INFO"
    # Emit logs as one JSON object per line (for log aggregators) instead of text.
    log_json: bool = False
    # Dev convenience: enables FastAPI debug and includes tracebacks in 500 responses.
    # MUST stay False in production (the startup guard does not force this, but a
    # production boot with debug=True is logged as a warning).
    debug: bool = False

    # ── Security ─────────────────────────────────────────────────────────────
    phi_encryption_key_b64: str = ""           # base64 32-byte key for AES-GCM; empty => dev no-op
    enable_phi_redaction: bool = True
    audit_log_path: str = "audit.log.jsonl"
    # Internal admin dashboard (/admin1) password. Override in every real deployment via
    # SCRIBE_ADMIN_PASSWORD; the dev fallback is world-readable in the public repo.
    admin_password: str = "kraionyx1"
    # Security response headers (X-Frame-Options, nosniff, Referrer-Policy, and HSTS when
    # not in development). Disable only if a reverse proxy already sets them.
    security_headers: bool = True
    # Per-IP rate limit on the admin auth endpoint: max attempts / window seconds.
    admin_auth_rate_limit: int = 10
    admin_auth_rate_window_s: int = 60

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def supabase_jwks_url(self) -> str:
        """JWKS endpoint for verifying Supabase tokens signed with asymmetric keys.
        Explicit SCRIBE_JWT_JWKS_URL wins; otherwise derive it from SCRIBE_SUPABASE_URL."""
        if self.jwt_jwks_url:
            return self.jwt_jwks_url
        base = self.supabase_url.rstrip("/")
        return f"{base}/auth/v1/.well-known/jwks.json" if base else ""

    @property
    def use_vertex(self) -> bool:
        return bool(self.vertex_api_key or self.vertex_project)

    @property
    def use_sarvam(self) -> bool:
        return bool(self.sarvam_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
