"""Field-level PHI encryption (AES-256-GCM).

Encrypts individual PHI fields at rest. The key is a base64 32-byte value supplied
via ``SCRIBE_PHI_ENCRYPTION_KEY_B64`` (load from Vault/KMS in production). When no
key (or no ``cryptography`` package) is present, the cipher is a clearly-marked
dev no-op so the scaffold still runs — it must never be used with real PHI.
"""
from __future__ import annotations

import base64
import os

from app.config import Settings, get_settings

_DEV_PREFIX = "PLAINTEXT:"  # marks unencrypted dev values; never appears in prod


class FieldCipher:
    def __init__(self, settings: Settings) -> None:
        self.key: bytes | None = None
        self._aesgcm_cls = None
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # deferred

            raw = base64.b64decode(settings.phi_encryption_key_b64) if settings.phi_encryption_key_b64 else b""
            if len(raw) == 32:
                self.key = raw
                self._aesgcm_cls = AESGCM
        except Exception:
            self.key = None

    @property
    def enabled(self) -> bool:
        return self.key is not None

    def encrypt(self, plaintext: str) -> str:
        if not self.enabled:
            return _DEV_PREFIX + plaintext
        nonce = os.urandom(12)
        ct = self._aesgcm_cls(self.key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        if token.startswith(_DEV_PREFIX):
            return token[len(_DEV_PREFIX):]
        raw = base64.b64decode(token)
        nonce, ct = raw[:12], raw[12:]
        return self._aesgcm_cls(self.key).decrypt(nonce, ct, None).decode("utf-8")


def generate_key_b64() -> str:
    """Helper to mint a key for ``SCRIBE_PHI_ENCRYPTION_KEY_B64`` (see README)."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


_cipher: FieldCipher | None = None


def get_cipher(settings: Settings | None = None) -> FieldCipher:
    global _cipher
    if _cipher is None:
        _cipher = FieldCipher(settings or get_settings())
    return _cipher
