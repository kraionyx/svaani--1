"""Production safety guard — fail fast on unsafe configuration.

The app is designed to boot with no credentials (mocks everywhere) for dev and tests.
That convenience is dangerous in production: it would happily write real PHI as
``PLAINTEXT:`` or trust ``X-Role`` headers. ``validate_production`` collects every such
problem and raises a single clear error so an unsafe production boot is impossible.

Only enforced when ``SCRIBE_ENVIRONMENT=production``; development boots are never blocked
(problems are surfaced as warnings by the caller instead).
"""
from __future__ import annotations

import logging

from app.config import Settings
from app.security.crypto import get_cipher

logger = logging.getLogger("svaani.startup")

_DEFAULT_ADMIN_PASSWORD = "admin@kraionyx"
_DURABLE_BACKENDS = {"sqlite", "supabase"}


class UnsafeProductionConfig(RuntimeError):
    """Raised at startup when production config is unsafe (blocks the boot)."""


def collect_problems(settings: Settings) -> list[str]:
    """Return a list of production-safety problems (empty == safe). No raising."""
    problems: list[str] = []

    # 1. PHI must be encrypted at rest when a durable store is used.
    if settings.store_backend in _DURABLE_BACKENDS and not get_cipher(settings).enabled:
        problems.append(
            f"store_backend={settings.store_backend!r} persists PHI but "
            "SCRIBE_PHI_ENCRYPTION_KEY_B64 is missing/invalid — clinical content would be "
            "written as PLAINTEXT. Set a base64 32-byte key."
        )

    if settings.auth_mode != "jwt":
        problems.append(
            f"auth_mode={settings.auth_mode!r} trusts X-User-Id/X-Role headers without "
            "verification. Set SCRIBE_AUTH_MODE=jwt."
        )
    elif not (settings.jwt_secret or settings.jwt_jwks_url):
        problems.append(
            "auth_mode='jwt' but no local signing material configured. "
            "Set SCRIBE_JWT_SECRET or SCRIBE_JWT_JWKS_URL to verify tokens securely."
        )

    # 3. Default admin password is world-readable in the public repo.
    if settings.admin_password == _DEFAULT_ADMIN_PASSWORD:
        problems.append(
            "admin_password is still the default — set SCRIBE_ADMIN_PASSWORD to a secret."
        )

    # 4. CORS still pointing only at localhost means the real frontend can't call the API
    #    (and signals the config was never adjusted for prod).
    if all("localhost" in o or "127.0.0.1" in o for o in settings.cors_origins):
        problems.append(
            "cors_allow_origins only contains localhost — set SCRIBE_CORS_ALLOW_ORIGINS "
            "to your real frontend origin(s)."
        )

    # 4b. Wildcard CORS with credentials enabled lets ANY website make authenticated calls
    #     (the app always sends allow_credentials=True). Never allow '*' in production.
    if any(o == "*" for o in settings.cors_origins):
        problems.append(
            "cors_allow_origins contains '*' while credentials are allowed — any origin "
            "could make authenticated requests. List explicit frontend origin(s)."
        )

    if settings.debug:
        problems.append(
            "debug is True — this exposes full tracebacks to clients. Set SCRIBE_DEBUG=False."
        )

    return problems


def collect_recommendations(settings: Settings) -> list[str]:
    """Return hardening recommendations that are WARN-only (never block the boot).

    These are safe-but-suboptimal settings — flagged so an operator notices, but not
    enforced because making them mandatory could lock out a valid setup.
    """
    recs: list[str] = []
    if settings.auth_mode == "jwt":
        # Without a verified audience, a token minted for a different project/audience that
        # happens to share the signing material would still validate. Supabase access tokens
        # carry aud="authenticated".
        if not settings.jwt_audience:
            recs.append(
                "auth_mode='jwt' but SCRIBE_JWT_AUDIENCE is unset — the 'aud' claim is not "
                "verified. Set SCRIBE_JWT_AUDIENCE=authenticated for Supabase."
            )
        # No local secret/JWKS forces a remote Supabase round-trip per uncached token.
        if not (settings.jwt_secret or settings.jwt_jwks_url):
            recs.append(
                "auth_mode='jwt' verifies tokens by calling Supabase per uncached token "
                "(slower, and an availability dependency). Set SCRIBE_JWT_SECRET to verify locally."
            )
    return recs


def validate_production(settings: Settings) -> None:
    """Block an unsafe production boot; warn (don't block) in development."""
    for rec in collect_recommendations(settings):
        logger.warning("Hardening recommendation: %s", rec)

    problems = collect_problems(settings)
    if not problems:
        return

    bullet = "\n  - ".join(problems)
    if settings.is_production:
        raise UnsafeProductionConfig(
            "Refusing to start in production with unsafe configuration:\n  - " + bullet
        )
    logger.warning(
        "Config would be unsafe in production (allowed in development):\n  - %s", bullet
    )
