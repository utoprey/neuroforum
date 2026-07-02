"""Service-layer tests for the ``saved`` module."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.saved.exceptions import ArticleNotFound
from app.modules.saved.repository import SavedRepository
from app.modules.saved.service import SavedService
from app.modules.users.models import Role, User, UserStats
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
def saved_svc(db_session: AsyncSession) -> SavedService:
    return SavedService(SavedRepository(db_session), db_session)


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


def _doc(value: str = "Hello") -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": value}],
            }
        ],
    }


async def _bootstrap_article(
    *,
    users_svc: UserService,
    forum_svc: ForumService,
    articles_svc: ArticleService,
    db_session: AsyncSession,
    slug: str,
) -> tuple[User, UUID]:
    admin = await _make_user(
        users_svc, db_session, username=f"admin_{slug}", role=Role.ADMIN
    )
    author = await _make_user(
        users_svc, db_session, username=f"author_{slug}", role=Role.USER
    )
    await forum_svc.create_section(admin, SectionCreate(title="S", slug=slug))
    topic, _ = await forum_svc.create_topic(
        admin, slug, TopicCreate(title="T")
    )
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(title="A", content=DocSchema.model_validate(_doc())),
    )
    pub, _ = await articles_svc.publish_article(author, article.id)
    return author, pub.id


async def _stats(db_session: AsyncSession, user_id: UUID) -> int:
    stmt = select(UserStats.saved_articles_count).where(UserStats.user_id == user_id)
    return int((await db_session.execute(stmt)).scalar_one())


async def test_save_then_list(
    saved_svc: SavedService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user, article_id = await _bootstrap_article(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="sv1",
    )
    await saved_svc.save(user, article_id)
    assert await _stats(db_session, user.id) == 1

    listed = await saved_svc.list_my_saved(user)
    assert len(listed) == 1
    saved_row, article, author = listed[0]
    assert saved_row.article_id == article_id
    assert article.id == article_id
    assert author.id == user.id


async def test_save_idempotent(
    saved_svc: SavedService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user, article_id = await _bootstrap_article(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="sv2",
    )
    await saved_svc.save(user, article_id)
    await saved_svc.save(user, article_id)
    # Counter only bumped once.
    assert await _stats(db_session, user.id) == 1


async def test_unsave_decrements_counter(
    saved_svc: SavedService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user, article_id = await _bootstrap_article(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="sv3",
    )
    await saved_svc.save(user, article_id)
    await saved_svc.unsave(user, article_id)
    assert await _stats(db_session, user.id) == 0
    listed = await saved_svc.list_my_saved(user)
    assert listed == []


async def test_unsave_idempotent_on_missing(
    saved_svc: SavedService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="sv4")
    # No prior save — unsave is a no-op (no exception, no negative counter).
    await saved_svc.unsave(user, uuid4())
    assert await _stats(db_session, user.id) == 0


async def test_save_missing_article_raises(
    saved_svc: SavedService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    user = await _make_user(users_svc, db_session, username="sv5")
    with pytest.raises(ArticleNotFound):
        await saved_svc.save(user, uuid4())
