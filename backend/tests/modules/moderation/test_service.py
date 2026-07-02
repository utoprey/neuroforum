"""Service-layer tests for the ``moderation`` module."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import ArticleStatus
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.moderation.exceptions import (
    ArticleNotFound,
    InsufficientRole,
    UserNotFound,
)
from app.modules.moderation.repository import ModerationRepository
from app.modules.moderation.service import ModerationService
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
def mod_svc(db_session: AsyncSession) -> ModerationService:
    return ModerationService(ModerationRepository(db_session), db_session)


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


def _doc() -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Hi"}]}
        ],
    }


async def _bootstrap_article(
    *,
    users_svc: UserService,
    forum_svc: ForumService,
    articles_svc: ArticleService,
    db_session: AsyncSession,
    slug: str,
) -> tuple[User, User, User, str]:
    """Return ``(admin, mod, author, published_article_id)``."""
    admin = await _make_user(
        users_svc, db_session, username=f"admin_{slug}", role=Role.ADMIN
    )
    mod = await _make_user(
        users_svc, db_session, username=f"mod_{slug}", role=Role.MODERATOR
    )
    author = await _make_user(users_svc, db_session, username=f"author_{slug}")
    await forum_svc.create_section(admin, SectionCreate(title="S", slug=slug))
    topic, _ = await forum_svc.create_topic(admin, slug, TopicCreate(title="T"))
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(title="A", content=DocSchema.model_validate(_doc())),
    )
    pub, _ = await articles_svc.publish_article(author, article.id)
    return admin, mod, author, str(pub.id)


async def test_hide_article_changes_status_and_logs(
    mod_svc: ModerationService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, mod, _author, article_id = await _bootstrap_article(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="mod1",
    )
    article = await mod_svc.hide_article(mod, UUID(article_id), "spam")
    assert article.status == ArticleStatus.HIDDEN

    # Check audit log row.
    rows = await mod_svc.list_audit(
        _admin, target_type="article", target_id=UUID(article_id)
    )
    assert any(r.action == "hide_article" for r in rows)


async def test_unhide_article_flips_back(
    mod_svc: ModerationService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, mod, _author, article_id = await _bootstrap_article(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="mod2",
    )
    await mod_svc.hide_article(mod, UUID(article_id), "spam")
    article = await mod_svc.unhide_article(mod, UUID(article_id), "false alarm")
    assert article.status == ArticleStatus.PUBLISHED


async def test_hide_requires_mod_or_admin(
    mod_svc: ModerationService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, _mod, author, article_id = await _bootstrap_article(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="mod3",
    )
    with pytest.raises(InsufficientRole):
        await mod_svc.hide_article(author, UUID(article_id), "x")


async def test_hide_missing_article(
    mod_svc: ModerationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="mod4_admin", role=Role.ADMIN
    )
    with pytest.raises(ArticleNotFound):
        await mod_svc.hide_article(admin, uuid4(), "x")


async def test_assign_role_admin_only(
    mod_svc: ModerationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="mod5_admin", role=Role.ADMIN
    )
    mod = await _make_user(
        users_svc, db_session, username="mod5_mod", role=Role.MODERATOR
    )
    target = await _make_user(users_svc, db_session, username="mod5_target")

    # Moderator cannot reassign roles.
    with pytest.raises(InsufficientRole):
        await mod_svc.assign_role(mod, target.id, Role.MODERATOR)

    # Admin can.
    updated = await mod_svc.assign_role(admin, target.id, Role.MODERATOR)
    assert updated.role == Role.MODERATOR


async def test_assign_role_missing_user(
    mod_svc: ModerationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="mod6_admin", role=Role.ADMIN
    )
    with pytest.raises(UserNotFound):
        await mod_svc.assign_role(admin, uuid4(), Role.MODERATOR)


async def test_audit_filter_by_action(
    mod_svc: ModerationService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    admin, mod, _author, article_id = await _bootstrap_article(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="mod7",
    )
    await mod_svc.hide_article(mod, UUID(article_id), "noise")
    await mod_svc.unhide_article(mod, UUID(article_id), "ok now")

    hide_rows = await mod_svc.list_audit(admin, action="hide_article")
    assert all(r.action == "hide_article" for r in hide_rows)
    assert any(r.target_id == UUID(article_id) for r in hide_rows)

    unhide_rows = await mod_svc.list_audit(admin, action="unhide_article")
    assert all(r.action == "unhide_article" for r in unhide_rows)


async def test_audit_read_requires_admin(
    mod_svc: ModerationService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    mod = await _make_user(
        users_svc, db_session, username="mod8_mod", role=Role.MODERATOR
    )
    with pytest.raises(InsufficientRole):
        await mod_svc.list_audit(mod)
