"""Domain exceptions for ``auth``."""

from __future__ import annotations

# Names intentionally don't carry the ``Error`` suffix — the task spec
# fixes them as part of the public service-layer contract.
# ruff: noqa: N818


class AuthError(Exception):
    """Base class for auth-domain errors."""


class InvalidCredentials(AuthError):
    """Wrong username/email or password (intentionally indistinct error)."""


class TokenExpired(AuthError):
    """Refresh token's ``expires_at`` is in the past."""


class TokenRevoked(AuthError):
    """Refresh token has been explicitly revoked."""


class RefreshTokenNotFound(AuthError):
    """No row matches the supplied refresh token hash."""
