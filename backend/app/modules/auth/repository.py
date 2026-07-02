"""Data access for refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.modules.auth.models import RefreshToken


def _hash_token(raw: str) -> str:
    """SHA-256 hex digest. Refresh tokens are random uuids — no need for argon2."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AuthRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_refresh(
        self,
        *,
        user_id: uuid.UUID,
        raw_token: str,
        ttl_days: int,
        user_agent: str | None,
        ip: str | None,
    ) -> tuple[uuid.UUID, str]:
        """Persist a hashed refresh token, return ``(id, raw_token)``.

        Caller is responsible for committing.
        """
        token = RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=ttl_days),
            user_agent=user_agent,
            ip=ip,
        )
        self._db.add(token)
        await self._db.flush()
        return token.id, raw_token

    async def find_by_hash(self, raw_token: str) -> RefreshToken | None:
        h = _hash_token(raw_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == h)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def revoke(self, token_id: uuid.UUID) -> None:
        await self._db.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token_id)
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_for_user(self, user_id: uuid.UUID) -> None:
        await self._db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
            )
            .values(revoked_at=datetime.now(UTC))
        )


def generate_raw_refresh_token() -> str:
    """Cryptographically random opaque string used as the refresh token."""
    # 32 bytes -> 256 bits of entropy. URL-safe so it survives any transport.
    return secrets.token_urlsafe(32)


__all__ = ["AuthRepository", "generate_raw_refresh_token"]
