"""Service-layer tests for the ``notifications`` module."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def notif_svc(db_session: AsyncSession) -> NotificationService:
    return NotificationService(NotificationRepository(db_session), db_session)


async def _make_user(
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


async def test_create_and_list(
    notif_svc: NotificationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="nu1")
    n = await notif_svc.create_notification(
        user.id, type="mention", payload={"hello": "world"}
    )
    assert n.is_read is False
    listed = await notif_svc.list_for_user(user)
    assert len(listed) == 1
    assert listed[0].id == n.id
    assert listed[0].payload == {"hello": "world"}


async def test_mark_read_flips_flag(
    notif_svc: NotificationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="nu2")
    n1 = await notif_svc.create_notification(user.id, type="mention")
    n2 = await notif_svc.create_notification(user.id, type="reply")

    affected = await notif_svc.mark_read(user, [n1.id])
    assert affected == 1

    unread = await notif_svc.list_for_user(user, unread_only=True)
    assert len(unread) == 1
    assert unread[0].id == n2.id


async def test_mark_read_only_own_rows(
    notif_svc: NotificationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    a = await _make_user(users_svc, db_session, username="nu3a")
    b = await _make_user(users_svc, db_session, username="nu3b")
    b_notif = await notif_svc.create_notification(b.id, type="mention")
    # User A tries to mark B's row — should affect 0 rows.
    affected = await notif_svc.mark_read(a, [b_notif.id])
    assert affected == 0
    # B's row stays unread.
    unread = await notif_svc.list_for_user(b, unread_only=True)
    assert len(unread) == 1


async def test_unread_count(
    notif_svc: NotificationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="nu4")
    assert await notif_svc.unread_count(user) == 0

    n1 = await notif_svc.create_notification(user.id, type="mention")
    await notif_svc.create_notification(user.id, type="reply")
    assert await notif_svc.unread_count(user) == 2

    await notif_svc.mark_read(user, [n1.id])
    assert await notif_svc.unread_count(user) == 1
