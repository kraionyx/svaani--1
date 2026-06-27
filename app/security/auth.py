"""Pluggable authentication: dev header scaffold ↔ verified JWT bearer.

``SCRIBE_AUTH_MODE=dev`` (default) keeps the ``X-User-Id`` / ``X-Role`` header scaffold
so local runs and tests need no token. ``=jwt`` requires a verified bearer token.

Designed for **Supabase Auth** (Google + email/password), but provider-agnostic. The
token's ``alg`` header selects the verification path automatically:

* ``HS256`` → symmetric, verified with ``SCRIBE_JWT_SECRET`` (the Supabase project's
  JWT secret; also used for dev/test tokens).
* ``RS256`` / ``ES256`` → asymmetric, verified against the JWKS endpoint
  (``SCRIBE_JWT_JWKS_URL``, or auto-derived from ``SCRIBE_SUPABASE_URL``).
* **No secret configured** → fall back to asking Supabase to validate the token
  (``GET /auth/v1/user``) using only the public ``SCRIBE_SUPABASE_URL`` +
  ``SCRIBE_SUPABASE_ANON_KEY``. Works out-of-the-box; results are cached briefly so it's
  one network call per token, not per request. Paste the JWT secret to upgrade to
  zero-network local verification.

The verified claims become the same ``Principal`` the RBAC layer already understands —
``sub`` → id (the auth.users UUID, used as ``practitioner_id``), email + app role from
the claims — so every existing permission check is unchanged. ``PyJWT`` is imported
lazily so the app still boots in dev mode without it.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from functools import lru_cache

from app.config import Settings
from app.security.rbac import Principal, Role

# Dedicated auth logger. Set SCRIBE_LOG_LEVEL=DEBUG to see per-request verification detail
# (chosen path, token alg, resolved user) on stdout; failures always log at WARNING.
logger = logging.getLogger("svaani.auth")

# Short-lived cache of remotely-verified tokens: token -> (claims, expiry_epoch). Supabase
# access tokens live ~1h; caching the validation for 60s collapses the per-request /auth/v1/user
# round-trips while still re-checking often enough to honour sign-outs/expiry promptly.
_REMOTE_TTL_S = 60
_remote_cache: dict[str, tuple[dict, float]] = {}

# Negative cache: tokens Supabase just rejected, so a flood of repeats doesn't re-hit the
# Auth API. token -> expiry_epoch. Short TTL so a genuinely-renewed token recovers quickly.
_REMOTE_NEG_TTL_S = 30
_remote_neg_cache: dict[str, float] = {}

# Circuit breaker on OUTBOUND remote-verify calls. Without a local JWT secret, every distinct
# unknown token would otherwise trigger one Supabase round-trip — an attacker spraying unique
# bogus tokens could turn our API into a traffic amplifier against Supabase. Cap the number of
# live verify calls per rolling window; over the cap we fail closed (401) without calling out.
_REMOTE_MAX_CALLS = 120
_REMOTE_CALL_WINDOW_S = 60
_remote_call_times: list[float] = []


class AuthError(Exception):
    """Raised when a required token is missing or invalid (mapped to HTTP 401).

    ``severity`` tags how the admin console should treat it: ``warning`` for client-side
    causes (missing/expired/forged token — routine) vs ``error`` for an operational problem
    (e.g. Supabase unreachable so we can't verify anyone). ``reason`` is a short stable code
    for grouping in the dashboard, separate from the human message.
    """

    def __init__(self, message: str, *, severity: str = "warning", reason: str = "invalid_token") -> None:
        super().__init__(message)
        self.severity = severity
        self.reason = reason


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing bearer token")
    return authorization.split(" ", 1)[1].strip()


@lru_cache(maxsize=8)
def _jwk_client(jwks_url: str):
    """Cache one PyJWKClient per URL — it memoizes the fetched signing keys, so we avoid
    re-downloading the JWKS on every request."""
    from jwt import PyJWKClient

    return PyJWKClient(jwks_url)


def _verify_remote(token: str, settings: Settings) -> dict:
    """Validate a token by asking Supabase (``GET /auth/v1/user``) and map the returned
    user to JWT-style claims. Used only when no local signing material is configured."""
    now = time.time()
    cached = _remote_cache.get(token)
    if cached and cached[1] > now:
        logger.debug("auth: remote verify cache-hit user=%s", cached[0].get("sub"))
        return cached[0]
    # Negative cache: a token Supabase rejected moments ago is still bad — don't re-ask.
    neg = _remote_neg_cache.get(token)
    if neg and neg > now:
        raise AuthError("invalid token", reason="token_rejected")
    base = settings.supabase_url.rstrip("/")
    if not base or not settings.supabase_anon_key:
        raise AuthError("jwt mode needs SCRIBE_JWT_SECRET, or SCRIBE_SUPABASE_URL + "
                        "SCRIBE_SUPABASE_ANON_KEY for remote verification",
                        severity="error", reason="auth_misconfigured")
    # Circuit breaker: bound how many live verify calls we make per window so unique-token
    # sprays can't turn us into an amplifier against Supabase. Over the cap → fail closed.
    _remote_call_times[:] = [t for t in _remote_call_times if t > now - _REMOTE_CALL_WINDOW_S]
    if len(_remote_call_times) >= _REMOTE_MAX_CALLS:
        logger.error("auth: remote-verify breaker OPEN (%d calls/%ds) — rejecting until it drains",
                     _REMOTE_MAX_CALLS, _REMOTE_CALL_WINDOW_S)
        raise AuthError("token verification temporarily unavailable",
                        severity="error", reason="verify_throttled")
    _remote_call_times.append(now)
    t0 = time.perf_counter()
    req = urllib.request.Request(
        f"{base}/auth/v1/user",
        headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            user = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # 401/403 → token rejected by Supabase (routine)
        logger.warning("auth: remote verify rejected token (HTTP %s)", exc.code)
        if len(_remote_neg_cache) > 4096:  # bound the negative cache
            for k in [k for k, v in list(_remote_neg_cache.items()) if v <= now][:512]:
                _remote_neg_cache.pop(k, None)
        _remote_neg_cache[token] = now + _REMOTE_NEG_TTL_S
        raise AuthError(f"invalid token: {exc.code}", reason="token_rejected") from exc
    except Exception as exc:  # network/timeout — an OPERATIONAL problem; fail closed + alert
        logger.error("auth: remote verify UNAVAILABLE (%s) — is Supabase reachable?", exc)
        raise AuthError(f"token verification unavailable: {exc}",
                        severity="error", reason="verify_unavailable") from exc
    if not user.get("id"):
        raise AuthError("invalid token: no user", reason="token_no_user")
    logger.debug("auth: remote verify ok user=%s (%.0fms)", user.get("id"), (time.perf_counter() - t0) * 1000)
    claims = {
        "sub": user["id"], "email": user.get("email"),
        "app_metadata": user.get("app_metadata") or {},
        "user_metadata": user.get("user_metadata") or {},
    }
    exp = user.get("exp") or (now + _REMOTE_TTL_S)
    ttl = min(now + _REMOTE_TTL_S, exp)
    if len(_remote_cache) > 1024:
        # crude cap so the cache can't grow unbounded: remove 128 oldest items
        for k in list(_remote_cache.keys())[:128]:
            _remote_cache.pop(k, None)
    _remote_cache[token] = (claims, ttl)
    return claims


def _verify_jwt(token: str, settings: Settings) -> dict:
    try:
        import jwt  # deferred — only needed in jwt mode
    except ImportError as exc:  # pragma: no cover
        raise AuthError("jwt mode requires PyJWT (pip install pyjwt)") from exc

    audience = settings.jwt_audience or None
    issuer = settings.jwt_issuer or None
    try:
        alg = (jwt.get_unverified_header(token) or {}).get("alg", "")
    except Exception as exc:  # malformed token
        logger.warning("auth: malformed token header (%s)", exc)
        raise AuthError(f"invalid token header: {exc}", reason="malformed_token") from exc

    try:
        if alg.startswith(("RS", "ES", "PS")):  # asymmetric (Supabase signing keys / Keycloak)
            jwks_url = settings.supabase_jwks_url
            if not jwks_url:
                raise AuthError("asymmetric token but no JWKS URL "
                                "(set SCRIBE_JWT_JWKS_URL or SCRIBE_SUPABASE_URL)",
                                severity="error", reason="auth_misconfigured")
            logger.debug("auth: verifying via JWKS (alg=%s)", alg)
            key = _jwk_client(jwks_url).get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=["RS256", "ES256", "PS256"],
                              audience=audience, issuer=issuer)
        # Symmetric (Supabase legacy JWT secret / dev/test tokens). With no secret set,
        # fall back to remote verification via the Supabase Auth API (anon key only).
        if not settings.jwt_secret:
            logger.debug("auth: verifying remotely (no local secret/JWKS)")
            return _verify_remote(token, settings)
        logger.debug("auth: verifying via local HS256 secret (alg=%s)", alg or "HS256")
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"],
                          audience=audience, issuer=issuer)
    except AuthError:
        raise
    except Exception as exc:  # invalid signature / expired / wrong aud — all 401
        logger.warning("auth: token verification failed (%s: %s)", type(exc).__name__, exc)
        raise AuthError(f"invalid token: {exc}", reason="verify_failed") from exc


def _role_of(claims: dict) -> Role:
    """Resolve the app role from the token. Supabase sets the top-level ``role`` claim to
    the Postgres role (``authenticated``), so the app role lives in a custom claim — set
    via an access-token hook or ``app_metadata``. Absent that, every signed-in user is a
    DOCTOR (the clinician workflow); ADMIN stays gated by the separate admin password."""
    meta = claims.get("app_metadata") or {}
    user_meta = claims.get("user_metadata") or {}
    raw = (claims.get("app_role") or meta.get("role")
           or user_meta.get("role") or claims.get("https://svaani/role"))
    if not raw or raw == "authenticated":
        return Role.DOCTOR
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
    sub = str(claims.get("sub") or claims.get("preferred_username") or "unknown")
    email = claims.get("email") or (claims.get("user_metadata") or {}).get("email")
    principal = Principal(id=sub, role=_role_of(claims), email=email)
    logger.debug("auth: resolved principal id=%s role=%s email=%s", sub, principal.role.value, email)
    return principal
