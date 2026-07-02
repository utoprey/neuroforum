"""Auth orchestration: login, refresh-rotation, logout."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    create_access_token,
    verify_password,
)
from app.modules.auth.exceptions import (
    InvalidCredentials,
    RefreshTokenNotFound,
    TokenExpired,
    TokenRevoked,
)
from app.modules.auth.repository import (
    AuthRepository,
    generate_raw_refresh_token,
)
from app.modules.auth.schemas import TokenPair
from app.modules.users.models import User
from app.modules.users.repository import UserRepository


class RequestMeta(TypedDict, total=False):
    """Per-request signal we persist with each refresh token."""

    user_agent: str | None
    ip: str | None


class AuthService:
    """Pure orchestration — no HTTP concerns leak in."""

    def __init__(
        self,
        repo: AuthRepository,
        users: UserRepository,
        settings: Settings,
        db: AsyncSession,
    ) -> None:
        self._repo = repo
        self._users = users
        self._settings = settings
        self._db = db

    # --- Authentication ---------------------------------------------------

    async def authenticate(self, username_or_email: str, password: str) -> User:
        """Look up by username OR email, verify password. Raises ``InvalidCredentials``.

        Indistinct on purpose: don't tell attackers whether the account exists.
        """
        user = await self._users.get_by_username(username_or_email)
        if user is None and "@" in username_or_email:
            user = await self._users.get_by_email(username_or_email)
        if user is None or user.password_hash is None:
            raise InvalidCredentials()
        if not verify_password(password, user.password_hash):
            raise InvalidCredentials()
        if not user.is_active:
            raise InvalidCredentials()
        return user

    # --- Token issuance ---------------------------------------------------

    async def issue_token_pair(
        self, user: User, request_meta: RequestMeta | None = None
    ) -> TokenPair:
        meta = request_meta or {}
        access = create_access_token(sub=str(user.id), extra={"role": user.role.value})
        raw_refresh = generate_raw_refresh_token()
        await self._repo.create_refresh(
            user_id=user.id,
            raw_token=raw_refresh,
            ttl_days=self._settings.REFRESH_TOKEN_EXPIRE_DAYS,
            user_agent=meta.get("user_agent"),
            ip=meta.get("ip"),
        )
        return TokenPair(
            access_token=access,
            refresh_token=raw_refresh,
            token_type="bearer",
            expires_in=self._settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def rotate_refresh(
        self, raw_refresh: str, request_meta: RequestMeta | None = None
    ) -> TokenPair:
        """Single-use refresh token semantics: validate, revoke, mint new pair."""
        row = await self._repo.find_by_hash(raw_refresh)
        if row is None:
            raise RefreshTokenNotFound()
        if row.revoked_at is not None:
            raise TokenRevoked()
        if row.expires_at < datetime.now(UTC):
            raise TokenExpired()

        user = await self._users.get(row.user_id)
        if user is None or not user.is_active:
            raise InvalidCredentials()

        await self._repo.revoke(row.id)
        return await self.issue_token_pair(user, request_meta)

    async def revoke_refresh(self, raw_refresh: str) -> None:
        """Best-effort revoke. Idempotent — missing token is a no-op."""
        row = await self._repo.find_by_hash(raw_refresh)
        if row is None or row.revoked_at is not None:
            return
        await self._repo.revoke(row.id)


__all__ = ["AuthService", "RequestMeta"]
