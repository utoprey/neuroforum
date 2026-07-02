"""Service-layer tests for the ``forum`` module."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forum.exceptions import (
    InsufficientRole,
    SectionNotFound,
    SlugConflict,
    TopicNotFound,
)
from app.modules.forum.models import TopicKind
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import (
    SectionCreate,
    SectionUpdate,
    TopicCreate,
    TopicUpdate,
)
from app.modules.forum.service import ForumService
from app.modules.forum.utils import make_slug
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def forum_svc(db_session: AsyncSession) -> ForumService:
    return ForumService(ForumRepository(db_session), db_session)


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


# ---------------------------------------------------------------------------
# Slug util
# ---------------------------------------------------------------------------


def test_make_slug_translit() -> None:
    assert make_slug("Привет, Мир!") == "privet-mir"


def test_make_slug_lowercase_ascii() -> None:
    assert make_slug("Hello World 1") == "hello-world-1"


def test_make_slug_fallback_uuid() -> None:
    out = make_slug("!!!")
    assert len(out) == 8 and out.isalnum()


def test_make_slug_truncates() -> None:
    assert len(make_slug("a" * 500, max_length=20)) <= 20


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


async def test_admin_creates_section(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm1", role=Role.ADMIN)
    section = await forum_svc.create_section(
        admin, SectionCreate(title="fMRI denoising", position=1)
    )
    assert section.slug == "fmri-denoising"
    assert section.position == 1


async def test_user_cannot_create_section(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    user = await _make_user(users_svc, db_session, username="user1")
    with pytest.raises(InsufficientRole):
        await forum_svc.create_section(user, SectionCreate(title="X"))


async def test_section_slug_collision_raises(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm2", role=Role.ADMIN)
    await forum_svc.create_section(admin, SectionCreate(title="EEG", slug="eeg"))
    with pytest.raises(SlugConflict):
        await forum_svc.create_section(admin, SectionCreate(title="EEG 2", slug="eeg"))


async def test_update_section(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm3", role=Role.ADMIN)
    section = await forum_svc.create_section(
        admin, SectionCreate(title="ECoG", slug="ecog")
    )
    updated = await forum_svc.update_section(
        admin, "ecog", SectionUpdate(title="ECoG (updated)", position=5)
    )
    assert updated.title == "ECoG (updated)"
    assert updated.position == 5
    assert updated.id == section.id


async def test_update_nonexistent_section_raises(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm4", role=Role.ADMIN)
    with pytest.raises(SectionNotFound):
        await forum_svc.update_section(admin, "nope", SectionUpdate(title="x"))


async def test_list_sections_ordered_by_position(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm5", role=Role.ADMIN)
    await forum_svc.create_section(admin, SectionCreate(title="B", slug="b", position=2))
    await forum_svc.create_section(admin, SectionCreate(title="A", slug="a", position=1))
    await forum_svc.create_section(admin, SectionCreate(title="C", slug="c", position=3))
    sections = await forum_svc.list_sections()
    assert [s.slug for s in sections] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


async def test_moderator_creates_topic(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm6", role=Role.ADMIN)
    mod = await _make_user(users_svc, db_session, username="mod1", role=Role.MODERATOR)
    section = await forum_svc.create_section(
        admin, SectionCreate(title="DTI", slug="dti")
    )
    topic, author = await forum_svc.create_topic(
        mod, section.slug, TopicCreate(title="White matter integrity")
    )
    assert topic.section_id == section.id
    assert topic.slug == "white-matter-integrity"
    assert author.id == mod.id


async def test_user_can_create_discussion_topic(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm7", role=Role.ADMIN)
    user = await _make_user(users_svc, db_session, username="user2")
    await forum_svc.create_section(admin, SectionCreate(title="MEG", slug="meg"))
    topic, author = await forum_svc.create_topic(
        user, "meg", TopicCreate(title="X", kind=TopicKind.DISCUSSION)
    )
    assert topic.kind == TopicKind.DISCUSSION
    assert author.id == user.id


async def test_user_cannot_create_news_topic(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="adm7_news", role=Role.ADMIN
    )
    user = await _make_user(users_svc, db_session, username="user2_news")
    await forum_svc.create_section(
        admin, SectionCreate(title="MEG2", slug="meg2")
    )
    with pytest.raises(InsufficientRole):
        await forum_svc.create_topic(
            user, "meg2", TopicCreate(title="News piece", kind=TopicKind.NEWS)
        )


async def test_mod_can_create_news_topic(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="adm7_news_mod", role=Role.ADMIN
    )
    mod = await _make_user(
        users_svc, db_session, username="mod7_news", role=Role.MODERATOR
    )
    await forum_svc.create_section(
        admin, SectionCreate(title="MEG3", slug="meg3")
    )
    topic, _ = await forum_svc.create_topic(
        mod, "meg3", TopicCreate(title="News mod", kind=TopicKind.NEWS)
    )
    assert topic.kind == TopicKind.NEWS


async def test_list_topics_filter_by_kind(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="adm_filter", role=Role.ADMIN
    )
    await forum_svc.create_section(
        admin, SectionCreate(title="Filt", slug="filt")
    )
    await forum_svc.create_topic(
        admin, "filt", TopicCreate(title="N1", kind=TopicKind.NEWS)
    )
    await forum_svc.create_topic(
        admin, "filt", TopicCreate(title="D1", kind=TopicKind.DISCUSSION)
    )
    await forum_svc.create_topic(
        admin, "filt", TopicCreate(title="H1", kind=TopicKind.HELP)
    )
    news = await forum_svc.list_topics_for_section("filt", kind=TopicKind.NEWS)
    disc = await forum_svc.list_topics_for_section(
        "filt", kind=TopicKind.DISCUSSION
    )
    helps = await forum_svc.list_topics_for_section("filt", kind=TopicKind.HELP)
    assert {t.title for t, _ in news} == {"N1"}
    assert {t.title for t, _ in disc} == {"D1"}
    assert {t.title for t, _ in helps} == {"H1"}
    all_topics = await forum_svc.list_topics_for_section("filt")
    assert len(all_topics) == 3


async def test_topic_slug_auto_collision_retry(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm8", role=Role.ADMIN)
    await forum_svc.create_section(admin, SectionCreate(title="X", slug="xsec"))
    t1, _ = await forum_svc.create_topic(admin, "xsec", TopicCreate(title="Same Title"))
    t2, _ = await forum_svc.create_topic(admin, "xsec", TopicCreate(title="Same Title"))
    t3, _ = await forum_svc.create_topic(admin, "xsec", TopicCreate(title="Same Title"))
    assert t1.slug == "same-title"
    assert t2.slug == "same-title-2"
    assert t3.slug == "same-title-3"


async def test_topic_explicit_slug_collision_retry(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm9", role=Role.ADMIN)
    await forum_svc.create_section(admin, SectionCreate(title="Z", slug="zsec"))
    a, _ = await forum_svc.create_topic(
        admin, "zsec", TopicCreate(title="A", slug="fixed")
    )
    b, _ = await forum_svc.create_topic(
        admin, "zsec", TopicCreate(title="B", slug="fixed")
    )
    assert a.slug == "fixed"
    assert b.slug == "fixed-2"


async def test_update_topic_lock_pin(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm10", role=Role.ADMIN)
    await forum_svc.create_section(admin, SectionCreate(title="Q", slug="qsec"))
    topic, _ = await forum_svc.create_topic(admin, "qsec", TopicCreate(title="Q1"))
    updated, _ = await forum_svc.update_topic(
        admin, topic.id, TopicUpdate(is_locked=True, is_pinned=True)
    )
    assert updated.is_locked is True
    assert updated.is_pinned is True


async def test_lock_topic_method(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm11", role=Role.ADMIN)
    await forum_svc.create_section(admin, SectionCreate(title="L", slug="lsec"))
    topic, _ = await forum_svc.create_topic(admin, "lsec", TopicCreate(title="L1"))
    locked, _ = await forum_svc.lock_topic(admin, topic.id, True)
    assert locked.is_locked is True
    unlocked, _ = await forum_svc.lock_topic(admin, topic.id, False)
    assert unlocked.is_locked is False


async def test_get_topic_missing_raises(
    forum_svc: ForumService,
) -> None:
    import uuid as _uuid

    with pytest.raises(TopicNotFound):
        await forum_svc.get_topic(_uuid.uuid4())


async def test_list_topics_pinned_first(
    forum_svc: ForumService, users_svc: UserService, db_session: AsyncSession
) -> None:
    admin = await _make_user(users_svc, db_session, username="adm12", role=Role.ADMIN)
    await forum_svc.create_section(admin, SectionCreate(title="P", slug="psec"))
    t_old, _ = await forum_svc.create_topic(admin, "psec", TopicCreate(title="Old"))
    t_new, _ = await forum_svc.create_topic(admin, "psec", TopicCreate(title="New"))
    # Pin the older one.
    await forum_svc.update_topic(admin, t_old.id, TopicUpdate(is_pinned=True))

    pairs = await forum_svc.list_topics_for_section("psec")
    topics = [t for t, _ in pairs]
    assert topics[0].id == t_old.id  # pinned first even though older
    assert topics[1].id == t_new.id
