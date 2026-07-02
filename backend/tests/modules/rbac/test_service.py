"""Service-layer tests for ``rbac``."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.exceptions import (
    AlreadyBanned,
    BanNotFound,
    CannotBanAdmin,
    InsufficientRole,
)
from app.modules.rbac.models import BanScope, UserBan
from app.modules.rbac.repository import RbacRepository
from app.modules.rbac.service import RbacService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def rbac_svc(db_session: AsyncSession) -> RbacService:
    return RbacService(
        RbacRepository(db_session), UserRepository(db_session), db_session
    )


async def _make_user_with_role(
    users_svc: UserService,
    db_session: AsyncSession,
    *,
    username: str,
    role: Role = Role.USER,
) -> User:
    user = await users_svc.create_user(
        UserCreate(
            username=username,
            email=f"{username}@x.io",
            password=SecretStr("hunter22!"),
        )
    )
    if role is not Role.USER:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role.value, "id": user.id},
        )
        await db_session.flush()
        await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Ban / lift / role checks
# ---------------------------------------------------------------------------


async def test_moderator_can_ban_user(
    rbac_svc: RbacService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod1", role=Role.MODERATOR)
    target = await _make_user_with_role(users_svc, db_session, username="victim1")
    from app.modules.rbac.schemas import BanCreate

    ban = await rbac_svc.ban_user(
        mod,
        BanCreate(
            user_id=target.id,
            reason="spam",
            scope=BanScope.GLOBAL,
        ),
    )
    assert isinstance(ban, UserBan)
    assert ban.user_id == target.id
    assert ban.banned_by == mod.id


async def test_regular_user_cannot_ban(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    actor = await _make_user_with_role(users_svc, db_session, username="user1")
    target = await _make_user_with_role(users_svc, db_session, username="victim2")
    from app.modules.rbac.schemas import BanCreate

    with pytest.raises(InsufficientRole):
        await rbac_svc.ban_user(
            actor,
            BanCreate(user_id=target.id, reason="x", scope=BanScope.GLOBAL),
        )


async def test_moderator_cannot_ban_admin(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod2", role=Role.MODERATOR)
    adm = await _make_user_with_role(users_svc, db_session, username="adm1", role=Role.ADMIN)
    from app.modules.rbac.schemas import BanCreate

    with pytest.raises(CannotBanAdmin):
        await rbac_svc.ban_user(
            mod,
            BanCreate(user_id=adm.id, reason="x", scope=BanScope.GLOBAL),
        )


async def test_moderator_cannot_ban_moderator(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    a = await _make_user_with_role(users_svc, db_session, username="modA", role=Role.MODERATOR)
    b = await _make_user_with_role(users_svc, db_session, username="modB", role=Role.MODERATOR)
    from app.modules.rbac.schemas import BanCreate

    with pytest.raises(CannotBanAdmin):
        await rbac_svc.ban_user(
            a,
            BanCreate(user_id=b.id, reason="x", scope=BanScope.GLOBAL),
        )


async def test_admin_cannot_ban_admin(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    a = await _make_user_with_role(users_svc, db_session, username="admA", role=Role.ADMIN)
    b = await _make_user_with_role(users_svc, db_session, username="admB", role=Role.ADMIN)
    from app.modules.rbac.schemas import BanCreate

    with pytest.raises(CannotBanAdmin):
        await rbac_svc.ban_user(
            a,
            BanCreate(user_id=b.id, reason="x", scope=BanScope.GLOBAL),
        )


async def test_ban_idempotency_same_scope(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod3", role=Role.MODERATOR)
    target = await _make_user_with_role(users_svc, db_session, username="victim3")
    from app.modules.rbac.schemas import BanCreate

    await rbac_svc.ban_user(
        mod, BanCreate(user_id=target.id, reason="x", scope=BanScope.GLOBAL)
    )
    with pytest.raises(AlreadyBanned):
        await rbac_svc.ban_user(
            mod, BanCreate(user_id=target.id, reason="x", scope=BanScope.GLOBAL)
        )


async def test_lift_ban(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod4", role=Role.MODERATOR)
    target = await _make_user_with_role(users_svc, db_session, username="victim4")
    from app.modules.rbac.schemas import BanCreate

    ban = await rbac_svc.ban_user(
        mod, BanCreate(user_id=target.id, reason="x", scope=BanScope.GLOBAL)
    )
    lifted = await rbac_svc.lift_ban(mod, ban.id, "reformed")
    assert lifted.lifted_at is not None
    assert lifted.lifted_by == mod.id
    assert lifted.lift_reason == "reformed"


async def test_lift_unknown_ban_raises(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod5", role=Role.MODERATOR)
    with pytest.raises(BanNotFound):
        await rbac_svc.lift_ban(mod, uuid.uuid4(), "no reason")


async def test_is_banned_active_global(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod6", role=Role.MODERATOR)
    target = await _make_user_with_role(users_svc, db_session, username="victim6")
    from app.modules.rbac.schemas import BanCreate

    assert not await rbac_svc.is_banned(target.id, scope=BanScope.GLOBAL)
    await rbac_svc.ban_user(
        mod, BanCreate(user_id=target.id, reason="x", scope=BanScope.GLOBAL)
    )
    assert await rbac_svc.is_banned(target.id, scope=BanScope.GLOBAL)


async def test_is_banned_expired_returns_false(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod7", role=Role.MODERATOR)
    target = await _make_user_with_role(users_svc, db_session, username="victim7")
    from app.modules.rbac.schemas import BanCreate

    ban = await rbac_svc.ban_user(
        mod,
        BanCreate(
            user_id=target.id,
            reason="x",
            scope=BanScope.GLOBAL,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    assert await rbac_svc.is_banned(target.id, scope=BanScope.GLOBAL)
    # Push expiration into the past.
    await db_session.execute(
        update(UserBan)
        .where(UserBan.id == ban.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.flush()
    assert not await rbac_svc.is_banned(target.id, scope=BanScope.GLOBAL)


async def test_is_banned_lifted_returns_false(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod8", role=Role.MODERATOR)
    target = await _make_user_with_role(users_svc, db_session, username="victim8")
    from app.modules.rbac.schemas import BanCreate

    ban = await rbac_svc.ban_user(
        mod, BanCreate(user_id=target.id, reason="x", scope=BanScope.GLOBAL)
    )
    await rbac_svc.lift_ban(mod, ban.id, "all good")
    assert not await rbac_svc.is_banned(target.id, scope=BanScope.GLOBAL)


async def test_list_my_active_bans(
    rbac_svc: RbacService, users_svc: UserService, db_session: AsyncSession
) -> None:
    mod = await _make_user_with_role(users_svc, db_session, username="mod9", role=Role.MODERATOR)
    target = await _make_user_with_role(users_svc, db_session, username="victim9")
    from app.modules.rbac.schemas import BanCreate

    assert await rbac_svc.list_my_active_bans(target.id) == []
    await rbac_svc.ban_user(
        mod, BanCreate(user_id=target.id, reason="x", scope=BanScope.GLOBAL)
    )
    bans = await rbac_svc.list_my_active_bans(target.id)
    assert len(bans) == 1
