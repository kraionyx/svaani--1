"""Pluggable authentication: dev header scaffold ↔ verified JWT bearer.

``SCRIBE_AUTH_MODE=dev`` (default) keeps the ``X-User-Id`` / ``X-Role`` header scaffold
so local runs and tests need no token. ``=jwt`` requires a verified bearer token:
HS256 with ``SCRIBE_JWT_SECRET`` (dev/test), or RS256 verified against a Keycloak/OIDC
``SCRIBE_JWT_JWKS_URL``. ``PyJWT`` is imported lazily so the app boots without it.

The verified claims become the same ``Principal`` the RBAC layer already understands —
``sub`` → id, ``role`` claim → ``Role`` — so every existing permission check is unchanged.
"""
from __future__ import annotations

from app.config import Settings
from app.security.rbac import Principal, Role


class AuthError(Exception):
    """Raised when a required token is missing or invalid (mapped to HTTP 401)."""


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def _verify_jwt(token: str, settings: Settings) -> dict:
    try:
        import jwt  # deferred — only needed in jwt mode
    except ImportError as exc:  # pragma: no cover
        raise AuthError("jwt mode requires PyJWT (pip install pyjwt)") from exc

    audience = settings.jwt_audience or None
    issuer = settings.jwt_issuer or None
    try:
        if settings.jwt_jwks_url:
            from jwt import PyJWKClient

            key = PyJWKClient(settings.jwt_jwks_url).get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=issuer)
        if not settings.jwt_secret:
            raise AuthError("jwt mode needs SCRIBE_JWT_SECRET or SCRIBE_JWT_JWKS_URL")
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], audience=audience, issuer=issuer)
    except AuthError:
        raise
    except Exception as exc:  # invalid signature / expired / wrong aud — all 401
        raise AuthError(f"invalid token: {exc}") from exc


def _role_of(claims: dict) -> Role:
    raw = claims.get("role") or claims.get("https://svaani/role") or "doctor"
    try:
        return Role(raw)
    except ValueError:
        return Role.DOCTOR


def principal_from(
    settings: Settings, *, authorization: str | None, x_user_id: str, x_role: str
) -> Principal:
    """Resolve the request Principal per the configured auth mode."""
    if settings.auth_mode != "jwt":
        return Principal(id=x_user_id, role=Role(x_role))  # dev scaffold
    claims = _verify_jwt(_bearer(authorization), settings)
    return Principal(id=str(claims.get("sub") or claims.get("preferred_username") or "unknown"),
                     role=_role_of(claims))
