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
    app_name: str = "Karaionyx AI Medical Scribe"
    environment: str = "development"

    # ── Sarvam V3 STT ────────────────────────────────────────────────────────
    # Real-time/stream → immediate transcript (no speaker labels).
    # Batch API (with_diarization) → accurate, speaker-labeled transcript.
    sarvam_api_key: str = ""
    sarvam_stt_model: str = "saaras:v3"        # saaras:v3 = speech→English
    sarvam_mode: str = "translate"             # translate → English output
    sarvam_language_code: str = "unknown"      # 'unknown' → auto-detect input language
    sarvam_diarize: bool = True                # use Batch API for doctor/patient labels
    sarvam_num_speakers: int = 2               # doctor + patient
    sarvam_batch_timeout_s: int = 600

    # ── Vertex AI / Gemini (Medical Understanding LLM) ───────────────────────
    vertex_api_key: str = ""                   # express-mode API key (genai api_key=...)
    vertex_project: str = ""                   # OR project+location (regional residency)
    vertex_location: str = "asia-south1"       # Mumbai — India PHI residency (DPDPA)
    gemini_model: str = "gemini-2.5-pro"
    llm_temperature: float = 0.0               # deterministic structuring; we never "create"
    llm_max_output_tokens: int = 8192

    # ── Validation thresholds ────────────────────────────────────────────────
    stt_low_confidence_threshold: float = 0.6
    drop_ungrounded_fields: bool = True        # False => ungrounded items flagged, not dropped

    # ── Security ─────────────────────────────────────────────────────────────
    phi_encryption_key_b64: str = ""           # base64 32-byte key for AES-GCM; empty => dev no-op
    enable_phi_redaction: bool = True
    audit_log_path: str = "audit.log.jsonl"

    @property
    def use_vertex(self) -> bool:
        return bool(self.vertex_api_key or self.vertex_project)

    @property
    def use_sarvam(self) -> bool:
        return bool(self.sarvam_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
