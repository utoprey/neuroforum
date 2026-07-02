"""Fernet symmetric encryption helpers for agent credentials.

The Fernet key is derived from ``settings.ENCRYPTION_KEY`` via SHA-256 so any
arbitrary 32+-char secret works (Fernet requires exactly 32 raw bytes
url-safe-base64-encoded).
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet

from app.core.config import settings


def _derive_key(secret: str) -> bytes:
    """Derive a Fernet-compatible 32-byte URL-safe base64 key from a secret."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    """Return a Fernet instance keyed by ``settings.ENCRYPTION_KEY``."""
    return Fernet(_derive_key(settings.ENCRYPTION_KEY))


def encrypt(plaintext: str) -> bytes:
    """Encrypt ``plaintext`` and return the Fernet ciphertext bytes."""
    return get_fernet().encrypt(plaintext.encode())


def decrypt(ciphertext: bytes) -> str:
    """Decrypt ``ciphertext`` and return the original plaintext string."""
    return get_fernet().decrypt(ciphertext).decode()


def fingerprint(api_key: str) -> str:
    """Build a display-safe fingerprint of an API key.

    Format: ``"***-<last4>-<sha256[:4]>"`` — last 4 raw chars plus a 4-char
    hex prefix of the sha256 so two keys that share their suffix still
    render distinctly in the UI.
    """
    if not api_key:
        return "***----"
    last4 = api_key[-4:].rjust(4, "*")
    # sha256 hex digest, truncated; this is non-secret because the key
    # itself never leaves the backend in plaintext.
    sha_prefix = hashlib.sha256(api_key.encode()).hexdigest()[:4]
    return f"***-{last4}-{sha_prefix}"


def secure_equals(a: str, b: str) -> bool:
    """Constant-time string equality — used for credential probes in tests."""
    return hmac.compare_digest(a.encode(), b.encode())


__all__ = [
    "decrypt",
    "encrypt",
    "fingerprint",
    "get_fernet",
    "secure_equals",
]
