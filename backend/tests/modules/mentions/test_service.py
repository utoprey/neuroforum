"""Service-layer tests for the ``mentions`` module."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mentions.models import MentionSourceType
from app.modules.mentions.repository import MentionRepository
from app.modules.mentions.service import MentionService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def mention_svc(db_session: AsyncSession) -> MentionService:
    return MentionService(MentionRepository(db_session), db_session)


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


async def test_record_mentions_dedupes(
    mention_svc: MentionService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author = await _make_user(users_svc, db_session, username="mauthor")
    a = await _make_user(users_svc, db_session, username="alice_m")
    b = await _make_user(users_svc, db_session, username="bob_m")
    source_id = uuid4()

    first = await mention_svc.record_mentions(
        MentionSourceType.ARTICLE, source_id, author.id, {a.id, b.id}
    )
    assert len(first) == 2

    # Re-record with overlapping IDs — only the new one should land.
    c = await _make_user(users_svc, db_session, username="carol_m")
    second = await mention_svc.record_mentions(
        MentionSourceType.ARTICLE, source_id, author.id, {a.id, b.id, c.id}
    )
    assert len(second) == 1
    assert second[0].mentioned_user_id == c.id


async def test_record_mentions_skips_self_mention(
    mention_svc: MentionService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author = await _make_user(users_svc, db_session, username="selfmention")
    rows = await mention_svc.record_mentions(
        MentionSourceType.MESSAGE, uuid4(), author.id, {author.id}
    )
    assert rows == []


async def test_list_my_mentions_returns_user_rows(
    mention_svc: MentionService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author = await _make_user(users_svc, db_session, username="lauthor")
    target = await _make_user(users_svc, db_session, username="ltarget")
    other = await _make_user(users_svc, db_session, username="lother")

    await mention_svc.record_mentions(
        MentionSourceType.ARTICLE, uuid4(), author.id, {target.id, other.id}
    )

    listed = await mention_svc.list_my_mentions(target)
    assert len(listed) == 1
    mention, mentioned_user, author_user = listed[0]
    assert mention.mentioned_user_id == target.id
    assert mentioned_user.id == target.id
    assert author_user.id == author.id


async def test_unread_only_filter(
    mention_svc: MentionService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    author = await _make_user(users_svc, db_session, username="uauthor")
    target = await _make_user(users_svc, db_session, username="utarget")

    rows = await mention_svc.record_mentions(
        MentionSourceType.MESSAGE, uuid4(), author.id, {target.id}
    )
    # Mark notified — should drop out of unread feed.
    await db_session.execute(
        text("UPDATE mentions SET notified_at = now() WHERE id = :id"),
        {"id": rows[0].id},
    )
    await db_session.flush()

    unread = await mention_svc.list_my_mentions(target, unread_only=True)
    assert unread == []
    everything = await mention_svc.list_my_mentions(target, unread_only=False)
    assert len(everything) == 1
