"""Service-layer tests for the ``auth`` module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth.exceptions import (
    InvalidCredentials,
    RefreshTokenNotFound,
    TokenExpired,
    TokenRevoked,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


@pytest.fixture
def user_service(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def auth_service(db_session: AsyncSession) -> AuthService:
    return AuthService(
        AuthRepository(db_session),
        UserRepository(db_session),
        settings,
        db_session,
    )


async def _make_user(
    user_service: UserService, *, username: str = "loginer", password: str = "hunter22!"
) -> tuple[str, str]:
    user = await user_service.create_user(
        UserCreate(
            username=username,
            email=f"{username}@x.io",
            password=SecretStr(password),
        )
    )
    return str(user.id), password


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------


async def test_authenticate_happy_path(
    auth_service: AuthService, user_service: UserService
) -> None:
    _, pw = await _make_user(user_service, username="happy")
    user = await auth_service.authenticate("happy", pw)
    assert user.username == "happy"


async def test_authenticate_by_email(
    auth_service: AuthService, user_service: UserService
) -> None:
    _, pw = await _make_user(user_service, username="emailog")
    user = await auth_service.authenticate("emailog@x.io", pw)
    assert user.username == "emailog"


async def test_authenticate_wrong_password(
    auth_service: AuthService, user_service: UserService
) -> None:
    await _make_user(user_service, username="wpx")
    with pytest.raises(InvalidCredentials):
        await auth_service.authenticate("wpx", "not-the-password")


async def test_authenticate_missing_user(auth_service: AuthService) -> None:
    with pytest.raises(InvalidCredentials):
        await auth_service.authenticate("nobody", "anything")


async def test_authenticate_inactive_user(
    auth_service: AuthService,
    user_service: UserService,
    db_session: AsyncSession,
) -> None:
    _uid, pw = await _make_user(user_service, username="dead2")
    # Mark inactive via raw UPDATE so we don't depend on a service helper.
    from sqlalchemy import text

    await db_session.execute(
        text("UPDATE users SET is_active = false WHERE username = 'dead2'")
    )
    await db_session.flush()
    with pytest.raises(InvalidCredentials):
        await auth_service.authenticate("dead2", pw)


# ---------------------------------------------------------------------------
# issue / rotate / revoke
# ---------------------------------------------------------------------------


async def test_issue_token_pair_returns_access_and_refresh(
    auth_service: AuthService, user_service: UserService
) -> None:
    await _make_user(user_service, username="issuer")
    user = await auth_service.authenticate("issuer", "hunter22!")
    pair = await auth_service.issue_token_pair(
        user, {"user_agent": "test/1.0", "ip": "127.0.0.1"}
    )
    assert pair.access_token
    assert pair.refresh_token
    assert pair.token_type == "bearer"
    assert pair.expires_in > 0


async def test_rotate_refresh_revokes_old(
    auth_service: AuthService, user_service: UserService
) -> None:
    await _make_user(user_service, username="rotater")
    user = await auth_service.authenticate("rotater", "hunter22!")
    first = await auth_service.issue_token_pair(user)
    second = await auth_service.rotate_refresh(first.refresh_token)
    assert second.refresh_token != first.refresh_token
    # First is now revoked.
    with pytest.raises(TokenRevoked):
        await auth_service.rotate_refresh(first.refresh_token)


async def test_rotate_unknown_refresh_raises(auth_service: AuthService) -> None:
    with pytest.raises(RefreshTokenNotFound):
        await auth_service.rotate_refresh("not-a-real-token")


async def test_rotate_expired_refresh_raises(
    auth_service: AuthService,
    user_service: UserService,
    db_session: AsyncSession,
) -> None:
    await _make_user(user_service, username="expirer")
    user = await auth_service.authenticate("expirer", "hunter22!")
    pair = await auth_service.issue_token_pair(user)
    # Backdate the row so it's expired.
    await db_session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id)
        .values(expires_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db_session.flush()
    with pytest.raises(TokenExpired):
        await auth_service.rotate_refresh(pair.refresh_token)


async def test_revoke_refresh_is_idempotent(
    auth_service: AuthService, user_service: UserService
) -> None:
    await _make_user(user_service, username="revoker")
    user = await auth_service.authenticate("revoker", "hunter22!")
    pair = await auth_service.issue_token_pair(user)
    await auth_service.revoke_refresh(pair.refresh_token)
    # Second call is a no-op, not an error.
    await auth_service.revoke_refresh(pair.refresh_token)
    # And a totally bogus token is also a no-op.
    await auth_service.revoke_refresh("garbage")
