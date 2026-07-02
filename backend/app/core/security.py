"""Password hashing (argon2) and JWT helpers (HS256 access + refresh)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger(__name__)

ALGORITHM: Final[str] = "HS256"
TOKEN_TYPE_ACCESS: Final[str] = "access"
TOKEN_TYPE_REFRESH: Final[str] = "refresh"

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class InvalidTokenError(Exception):
    """Raised when a JWT fails signature/expiry/claims validation."""


# --- Passwords ---------------------------------------------------------------


def hash_password(password: str) -> str:
    """Hash a plaintext password using argon2."""
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time verification of a plaintext password against an argon2 hash."""
    return pwd_context.verify(password, hashed)


# --- JWT ---------------------------------------------------------------------


def _build_payload(
    *,
    sub: str,
    token_type: str,
    expires_delta: timedelta,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": sub,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        # Don't let callers silently overwrite reserved claims.
        reserved = {"sub", "type", "iat", "exp", "jti"}
        for key in reserved & extra.keys():
            logger.warning("Dropping reserved JWT claim '%s' from `extra`.", key)
        payload.update({k: v for k, v in extra.items() if k not in reserved})
    return payload


def create_access_token(sub: str, extra: dict[str, Any] | None = None) -> str:
    """Mint a short-lived access token. ``sub`` is the user/agent identifier."""
    payload = _build_payload(
        sub=sub,
        token_type=TOKEN_TYPE_ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra=extra,
    )
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(sub: str) -> str:
    """Mint a long-lived refresh token. Refresh tokens carry no custom claims."""
    payload = _build_payload(
        sub=sub,
        token_type=TOKEN_TYPE_REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises :class:`InvalidTokenError` on any failure."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[ALGORITHM],
        )
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    return payload
