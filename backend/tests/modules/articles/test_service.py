"""Service-layer tests for the ``articles`` module."""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.exceptions import (
    ArticleNotEditable,
    ArticleNotFound,
    MissingEditReason,
)
from app.modules.articles.models import ArticleStatus
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate, ArticleUpdate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.rbac.exceptions import InsufficientRole
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


@pytest.fixture
def articles_svc(db_session: AsyncSession) -> ArticleService:
    return ArticleService(
        ArticleRepository(db_session), ForumRepository(db_session), db_session
    )


@pytest.fixture
def articles_svc_with_notifs(
    db_session: AsyncSession,
) -> ArticleService:
    """Article service wired with mention + notification fan-out.

    Use this for tests that need to assert on notification payloads.
    """
    from app.modules.mentions.repository import MentionRepository
    from app.modules.mentions.service import MentionService
    from app.modules.notifications.repository import NotificationRepository
    from app.modules.notifications.service import NotificationService

    return ArticleService(
        ArticleRepository(db_session),
        ForumRepository(db_session),
        db_session,
        mention_service=MentionService(MentionRepository(db_session), db_session),
        notification_service=NotificationService(
            NotificationRepository(db_session), db_session
        ),
    )


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


async def _make_topic(
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
    *,
    section_slug: str = "fmri",
    section_title: str = "fMRI",
) -> tuple[User, User, str]:
    admin = await _make_user(
        users_svc, db_session, username=f"admin_{section_slug}", role=Role.ADMIN
    )
    user = await _make_user(
        users_svc, db_session, username=f"author_{section_slug}", role=Role.USER
    )
    await forum_svc.create_section(
        admin, SectionCreate(title=section_title, slug=section_slug)
    )
    topic, _ = await forum_svc.create_topic(
        admin, section_slug, TopicCreate(title="Topic")
    )
    return admin, user, str(topic.id)


def _make_doc(text_value: str = "Hello") -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text_value}],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_draft_default(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s1"
    )
    article, author = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="My Article", content=DocSchema.model_validate(_make_doc())),
    )
    assert article.status == ArticleStatus.DRAFT
    assert article.published_at is None
    assert author.id == user.id
    assert article.slug == "my-article"
    assert article.content_text == "Hello"
    assert article.mentioned_user_ids == []


async def test_create_invalid_content_rejected(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, _user, _topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s2"
    )
    # ``DocSchema`` rejects unknown block types at parse time.
    with pytest.raises(ValueError):
        ArticleCreate(
            title="X",
            content={  # type: ignore[arg-type]
                "type": "doc",
                "content": [{"type": "BOGUS"}],
            },
        )


async def test_create_extracts_mentions(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s3"
    )
    mentioned_id = uuid.uuid4()
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Hey "},
                    {"type": "mention", "attrs": {"user_id": str(mentioned_id)}},
                    {"type": "text", "text": " look at this"},
                ],
            }
        ],
    }
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="With mention", content=DocSchema.model_validate(doc)),
    )
    assert mentioned_id in article.mentioned_user_ids


async def test_create_slug_collision_retry(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s4"
    )
    a, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Same", content=DocSchema.model_validate(_make_doc())),
    )
    b, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Same", content=DocSchema.model_validate(_make_doc())),
    )
    c, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Same", content=DocSchema.model_validate(_make_doc())),
    )
    assert a.slug == "same"
    assert b.slug == "same-2"
    assert c.slug == "same-3"


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


async def test_draft_invisible_to_anonymous(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s5"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Draft", content=DocSchema.model_validate(_make_doc())),
    )
    with pytest.raises(ArticleNotFound):
        await articles_svc.get_for_viewer(article.id, None)


async def test_draft_visible_to_author(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s6"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Draft 2", content=DocSchema.model_validate(_make_doc())),
    )
    out, _ = await articles_svc.get_for_viewer(article.id, user)
    assert out.id == article.id


async def test_draft_visible_to_moderator(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s7"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Draft 3", content=DocSchema.model_validate(_make_doc())),
    )
    mod = await _make_user(users_svc, db_session, username="modviewer", role=Role.MODERATOR)
    out, _ = await articles_svc.get_for_viewer(article.id, mod)
    assert out.id == article.id


async def test_draft_invisible_to_other_user(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s8"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Draft 4", content=DocSchema.model_validate(_make_doc())),
    )
    other = await _make_user(users_svc, db_session, username="random_user")
    with pytest.raises(ArticleNotFound):
        await articles_svc.get_for_viewer(article.id, other)


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


async def test_publish_by_author(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s9"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Pub", content=DocSchema.model_validate(_make_doc())),
    )
    published, _ = await articles_svc.publish_article(user, article.id)
    assert published.status == ArticleStatus.PUBLISHED
    assert published.published_at is not None


async def test_publish_by_random_user_forbidden(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s10"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Pub2", content=DocSchema.model_validate(_make_doc())),
    )
    other = await _make_user(users_svc, db_session, username="other_pub")
    with pytest.raises(ArticleNotEditable):
        await articles_svc.publish_article(other, article.id)


async def test_publish_increments_author_articles_count(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Only the first publish bumps user_stats.articles_count for the author.

    Drafts do NOT count (only ``status = published``), and re-publishing an
    already published article must be a no-op against the counter.
    """
    from sqlalchemy import select

    from app.modules.users.models import UserStats

    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_pub_stat"
    )
    stats = (
        await db_session.execute(
            select(UserStats).where(UserStats.user_id == user.id)
        )
    ).scalar_one()
    assert stats.articles_count == 0

    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    await db_session.refresh(stats)
    # Draft alone must NOT bump the counter.
    assert stats.articles_count == 0

    await articles_svc.publish_article(user, article.id)
    await db_session.refresh(stats)
    assert stats.articles_count == 1

    # Re-publishing the same article is a no-op for the counter.
    await articles_svc.publish_article(user, article.id)
    await db_session.refresh(stats)
    assert stats.articles_count == 1


# ---------------------------------------------------------------------------
# Edit + revisions
# ---------------------------------------------------------------------------


async def test_author_edits_without_reason(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s11"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Old", content=DocSchema.model_validate(_make_doc("Old"))),
    )
    edited, _ = await articles_svc.edit_article(
        user,
        article.id,
        ArticleUpdate(
            title="New",
            content=DocSchema.model_validate(_make_doc("New")),
        ),
    )
    assert edited.title == "New"
    assert edited.content_text == "New"
    # One revision row captured the prior state.
    revs = await articles_svc.list_revisions(article.id, user)
    assert len(revs) == 1
    rev, editor = revs[0]
    assert rev.revision == 1
    assert rev.title == "Old"
    assert editor.id == user.id


async def test_moderator_must_provide_reason(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s12"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    mod = await _make_user(users_svc, db_session, username="mod_edit", role=Role.MODERATOR)
    with pytest.raises(MissingEditReason):
        await articles_svc.edit_article(
            mod, article.id, ArticleUpdate(title="modified")
        )
    # With a reason it succeeds.
    edited, _ = await articles_svc.edit_article(
        mod,
        article.id,
        ArticleUpdate(title="modified", edit_reason="typo fix"),
    )
    assert edited.title == "modified"
    revs = await articles_svc.list_revisions(article.id, mod)
    assert revs[0][0].editor_role_at_edit == Role.MODERATOR.value
    assert revs[0][0].edit_reason == "typo fix"


async def test_non_author_non_mod_cannot_edit(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s13"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    stranger = await _make_user(users_svc, db_session, username="stranger")
    with pytest.raises(ArticleNotEditable):
        await articles_svc.edit_article(stranger, article.id, ArticleUpdate(title="x"))


async def test_revision_counter_monotonic(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s14"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc("V0"))),
    )
    await articles_svc.edit_article(
        user, article.id, ArticleUpdate(title="B")
    )
    await articles_svc.edit_article(
        user, article.id, ArticleUpdate(title="C")
    )
    await articles_svc.edit_article(
        user, article.id, ArticleUpdate(title="D")
    )
    revs = await articles_svc.list_revisions(article.id, user)
    assert [r.revision for r, _ in revs] == [3, 2, 1]  # newest first


async def test_get_specific_revision(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s15"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Original", content=DocSchema.model_validate(_make_doc())),
    )
    await articles_svc.edit_article(user, article.id, ArticleUpdate(title="Edited"))
    rev, editor = await articles_svc.get_revision(article.id, 1, user)
    assert rev.title == "Original"
    assert editor.id == user.id


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------


async def test_list_for_topic_only_published(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s16"
    )
    a, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Draft", content=DocSchema.model_validate(_make_doc())),
    )
    b, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="Published", content=DocSchema.model_validate(_make_doc())),
    )
    await articles_svc.publish_article(user, b.id)
    pairs = await articles_svc.list_for_topic(uuid.UUID(topic_id))
    ids = {art.id for art, _ in pairs}
    assert b.id in ids
    assert a.id not in ids


async def test_list_drafts_for_user(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s17"
    )
    a, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="DraftA", content=DocSchema.model_validate(_make_doc())),
    )
    b, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="DraftB", content=DocSchema.model_validate(_make_doc())),
    )
    await articles_svc.publish_article(user, b.id)
    drafts = await articles_svc.list_drafts_for_user(user.id)
    ids = {art.id for art, _ in drafts}
    assert a.id in ids
    assert b.id not in ids


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_author_soft_delete_own_article(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_del1"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    await articles_svc.delete_article(user, article.id)
    await db_session.refresh(article)
    assert article.status == ArticleStatus.ARCHIVED


async def test_moderator_soft_delete_other_article(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_del2"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    mod = await _make_user(
        users_svc, db_session, username="mod_del", role=Role.MODERATOR
    )
    await articles_svc.delete_article(mod, article.id)
    await db_session.refresh(article)
    assert article.status == ArticleStatus.ARCHIVED


async def test_non_author_user_cannot_soft_delete(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_del3"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    stranger = await _make_user(users_svc, db_session, username="stranger_del")
    with pytest.raises(ArticleNotEditable):
        await articles_svc.delete_article(stranger, article.id)


async def test_user_cannot_hard_delete(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_del4"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    # Even the author isn't allowed to hard-delete — only admins.
    with pytest.raises(InsufficientRole):
        await articles_svc.delete_article(user, article.id, hard=True)


async def test_admin_hard_delete_removes_row(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from app.modules.articles.models import Article

    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_del5"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    admin = await _make_user(
        users_svc, db_session, username="admin_hard_del", role=Role.ADMIN
    )
    await articles_svc.delete_article(admin, article.id, hard=True)
    # Row is gone.
    from sqlalchemy import select as _select

    row = (
        await db_session.execute(
            _select(Article).where(Article.id == article.id)
        )
    ).scalar_one_or_none()
    assert row is None


async def test_soft_delete_published_decrements_articles_count(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from sqlalchemy import select as _select

    from app.modules.users.models import UserStats

    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_del6"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    await articles_svc.publish_article(user, article.id)
    stats = (
        await db_session.execute(
            _select(UserStats).where(UserStats.user_id == user.id)
        )
    ).scalar_one()
    await db_session.refresh(stats)
    assert stats.articles_count == 1

    await articles_svc.delete_article(user, article.id)
    await db_session.refresh(stats)
    assert stats.articles_count == 0


async def test_repeated_soft_delete_is_idempotent(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from sqlalchemy import select as _select

    from app.modules.users.models import UserStats

    _admin, user, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="s_del7"
    )
    article, _ = await articles_svc.create_article(
        user,
        uuid.UUID(topic_id),
        ArticleCreate(title="A", content=DocSchema.model_validate(_make_doc())),
    )
    await articles_svc.publish_article(user, article.id)
    stats = (
        await db_session.execute(
            _select(UserStats).where(UserStats.user_id == user.id)
        )
    ).scalar_one()
    await db_session.refresh(stats)
    assert stats.articles_count == 1

    await articles_svc.delete_article(user, article.id)
    await db_session.refresh(stats)
    assert stats.articles_count == 0
    # Second call must NOT bump the counter again or change the status.
    await articles_svc.delete_article(user, article.id)
    await db_session.refresh(stats)
    assert stats.articles_count == 0
    await db_session.refresh(article)
    assert article.status == ArticleStatus.ARCHIVED


# ---------------------------------------------------------------------------
# Notification payload fan-out
# ---------------------------------------------------------------------------


async def test_article_mention_notification_payload_rich(
    articles_svc_with_notifs: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """``create_article`` with a mention emits a notification with
    article_title / author_username / snippet — enough for human-readable UI."""
    from app.modules.notifications.repository import NotificationRepository
    from app.modules.notifications.service import NotificationService
    from app.modules.users.schemas import ProfileUpdate

    admin = await _make_user(
        users_svc, db_session, username="author_notif_payload", role=Role.ADMIN
    )
    await users_svc.update_profile(
        admin.id, ProfileUpdate(display_name="Alice the Author")
    )
    admin = await users_svc.get_by_id(admin.id)

    mentioned = await _make_user(
        users_svc, db_session, username="mentioned_notif_payload"
    )
    await forum_svc.create_section(
        admin, SectionCreate(title="N", slug="notif_payload")
    )
    topic, _ = await forum_svc.create_topic(
        admin, "notif_payload", TopicCreate(title="T")
    )
    doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Привет! "},
                    {
                        "type": "mention",
                        "attrs": {"user_id": str(mentioned.id)},
                    },
                    {"type": "text", "text": " глянь это."},
                ],
            }
        ],
    }
    article, _ = await articles_svc_with_notifs.create_article(
        admin,
        topic.id,
        ArticleCreate(
            title="Predictive coding обзор",
            content=DocSchema.model_validate(doc),
        ),
    )

    notif_svc = NotificationService(NotificationRepository(db_session), db_session)
    notifs = await notif_svc.list_for_user(mentioned)
    assert len(notifs) == 1
    n = notifs[0]
    assert n.type == "mention"
    payload = n.payload
    assert payload["kind"] == "article_mention"
    assert payload["article_id"] == str(article.id)
    assert payload["article_title"] == "Predictive coding обзор"
    assert payload["article_slug"] == article.slug
    assert payload["author_id"] == str(admin.id)
    assert payload["author_username"] == "author_notif_payload"
    assert payload["author_display_name"] == "Alice the Author"
    # Snippet from extracted plain text — includes the surrounding text.
    assert "глянь" in payload["snippet"]
