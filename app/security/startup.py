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

    if settings.debug:
        problems.append(
            "debug is True — this exposes full tracebacks to clients. Set SCRIBE_DEBUG=False."
        )

    return problems


def validate_production(settings: Settings) -> None:
    """Block an unsafe production boot; warn (don't block) in development."""
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
