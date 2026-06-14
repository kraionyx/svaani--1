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
    environment: str = "development"
    # Comma-separated browser origins allowed to call the API. The frontend is now a
    # standalone static app served on its own port (default :5173), so the API must
    # opt that origin into CORS. Same-origin (:8000) is kept for the bundled UI.
    cors_allow_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    # ── Sarvam V3 STT ────────────────────────────────────────────────────────
    # Real-time/stream → immediate transcript (no speaker labels).
    # Batch API (with_diarization) → accurate, speaker-labeled transcript.
    sarvam_api_key: str = ""
    sarvam_stt_model: str = "saaras:v3"        # saaras:v3 = speech→English
    sarvam_mode: str = "translate"             # translate → English output
    sarvam_language_code: str = "unknown"      # 'unknown' → auto-detect input language
    sarvam_diarize: bool = True                # use Batch API for doctor/patient labels
    sarvam_num_speakers: int = 2               # doctor + patient
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
    # and clamps to its minimum. Override per-deployment via SCRIBE_LLM_THINKING_BUDGET.
    llm_thinking_budget: int = 0
    # Latency: when True, clean + extract + risk are produced in ONE Gemini call instead
    # of three (the dominant cost is per-call round-trip latency, not tokens). Falls back
    # to the staged path automatically on any error. Set False to force the staged path.
    single_pass_llm: bool = True

    # ── Validation thresholds ────────────────────────────────────────────────
    stt_low_confidence_threshold: float = 0.6
    drop_ungrounded_fields: bool = True        # False => ungrounded items flagged, not dropped
    # When a Medical LLM is configured, rewrite each note section's grounded facts
    # into clinical prose (faithful rephrasing only — never adds content). With no
    # LLM the deterministic renderer's text stands. Set False to keep raw structure.
    narrative_notes: bool = True

    # ── Persistence ──────────────────────────────────────────────────────────
    # 'memory' (default, in-process) or 'sqlite' (durable, PHI encrypted at rest via
    # FieldCipher). Sessions survive restarts when 'sqlite'.
    store_backend: str = "memory"
    sqlite_path: str = "svaani.db"

    # ── Auth ─────────────────────────────────────────────────────────────────
    # 'dev' keeps the header scaffold (X-User-Id / X-Role); 'jwt' requires a verified
    # bearer token. HS256 dev secret, or RS256 via a Keycloak/OIDC JWKS URL.
    auth_mode: str = "dev"
    jwt_secret: str = ""                       # HS256 shared secret (dev/test)
    jwt_jwks_url: str = ""                      # RS256 JWKS endpoint (e.g. Keycloak)
    jwt_audience: str = ""
    jwt_issuer: str = ""

    # ── Observability ────────────────────────────────────────────────────────
    enable_metrics: bool = True                # expose Prometheus /metrics

    # ── Security ─────────────────────────────────────────────────────────────
    phi_encryption_key_b64: str = ""           # base64 32-byte key for AES-GCM; empty => dev no-op
    enable_phi_redaction: bool = True
    audit_log_path: str = "audit.log.jsonl"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def use_vertex(self) -> bool:
        return bool(self.vertex_api_key or self.vertex_project)

    @property
    def use_sarvam(self) -> bool:
        return bool(self.sarvam_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
