"""Tests for the ``search`` module: Postgres backend + OpenSearch stub.

``search_articles`` / ``search_messages`` are marked ``xfail`` because
``content_tsv`` is ``GENERATED ALWAYS AS`` in production but a plain empty
TSVECTOR in tests (see ``articles/models.py`` module docstring). The
trigram-based user search runs against ``pg_trgm`` which IS present in test
containers, so that one is a normal test.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.search.opensearch import OpenSearchSearchEngine
from app.modules.search.postgres import PostgresSearchEngine
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import ProfileUpdate, UserCreate
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
def engine(db_session: AsyncSession) -> PostgresSearchEngine:
    return PostgresSearchEngine(db_session)


async def _make_user(
    users_svc: UserService,
    db_session: AsyncSession,
    *,
    username: str,
    display_name: str | None = None,
    role: Role = Role.USER,
) -> User:
    user = await users_svc.create_user(
        UserCreate(
            username=username,
            email=f"{username}@x.io",
            password=SecretStr("hunter22!"),
        )
    )
    if display_name is not None:
        await users_svc.update_profile(
            user.id, ProfileUpdate(display_name=display_name)
        )
    if role is not Role.USER:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role.value, "id": user.id},
        )
        await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Users — pg_trgm similarity
# ---------------------------------------------------------------------------


async def test_search_users_by_username(
    engine: PostgresSearchEngine,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    await _make_user(users_svc, db_session, username="searchable_user_one")
    await _make_user(users_svc, db_session, username="searchable_user_two")
    await _make_user(users_svc, db_session, username="totally_other")

    hits = await engine.search_users("searchable", limit=10)
    usernames = {h.username for h in hits}
    assert "searchable_user_one" in usernames
    assert "searchable_user_two" in usernames
    assert "totally_other" not in usernames


async def test_search_users_by_display_name(
    engine: PostgresSearchEngine,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    await _make_user(
        users_svc,
        db_session,
        username="user_dn1",
        display_name="Ivan Petrov",
    )
    await _make_user(
        users_svc,
        db_session,
        username="user_dn2",
        display_name="Maria Smirnova",
    )
    hits = await engine.search_users("Ivan", limit=10)
    assert any(h.username == "user_dn1" for h in hits)


async def test_search_users_empty_query(
    engine: PostgresSearchEngine,
) -> None:
    assert await engine.search_users("", limit=10) == []
    assert await engine.search_users("   ", limit=10) == []


# ---------------------------------------------------------------------------
# Articles / Messages — content_tsv is empty in tests, xfail
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="content_tsv is GENERATED only after Alembic; in tests it stays empty",
    strict=False,
)
async def test_search_articles(
    engine: PostgresSearchEngine,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="search_admin", role=Role.ADMIN
    )
    author = await _make_user(users_svc, db_session, username="search_author")
    await forum_svc.create_section(admin, SectionCreate(title="S", slug="srcha"))
    topic, _ = await forum_svc.create_topic(
        admin, "srcha", TopicCreate(title="T")
    )
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(
            title="Brain imaging review",
            content=DocSchema.model_validate(
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "fMRI denoising methods"}
                            ],
                        }
                    ],
                }
            ),
        ),
    )
    await articles_svc.publish_article(author, article.id)

    hits = await engine.search_articles("denoising", limit=10)
    assert any(h.article.id == article.id for h in hits)


@pytest.mark.xfail(
    reason="content_tsv is GENERATED only after Alembic; in tests it stays empty",
    strict=False,
)
async def test_search_messages(
    engine: PostgresSearchEngine,
) -> None:
    # Even without inserting messages, the @@ operator against an empty
    # tsvector returns zero rows — but the xfail marker covers the case
    # where someone wires the GENERATED column in for tests.
    hits = await engine.search_messages("anything", limit=10)
    assert hits != []  # expected to fail


# ---------------------------------------------------------------------------
# OpenSearch stub
# ---------------------------------------------------------------------------


async def test_opensearch_stub_raises_not_implemented() -> None:
    stub = OpenSearchSearchEngine()
    with pytest.raises(NotImplementedError):
        await stub.search_articles("anything", limit=10)
    with pytest.raises(NotImplementedError):
        await stub.search_messages("anything", limit=10)
    with pytest.raises(NotImplementedError):
        await stub.search_users("anything", limit=10)
