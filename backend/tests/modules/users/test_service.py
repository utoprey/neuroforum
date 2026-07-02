"""Service-layer tests for the ``users`` module."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.exceptions import (
    EmailTaken,
    UsernameTaken,
    UserNotFound,
)
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import ProfileUpdate, UserCreate
from app.modules.users.service import UserService


@pytest.fixture
def svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_create_user_happy_path(svc: UserService) -> None:
    user = await svc.create_user(
        UserCreate(username="alice", email="alice@x.io", password=SecretStr("hunter22!"))
    )
    assert user.id is not None
    assert user.username == "alice"
    assert user.email == "alice@x.io"
    assert user.password_hash is not None and user.password_hash != "hunter22!"
    assert user.profile is not None
    assert user.stats is not None
    assert user.stats.articles_count == 0


async def test_create_user_duplicate_username_raises(svc: UserService) -> None:
    await svc.create_user(
        UserCreate(username="bob", email="bob@x.io", password=SecretStr("hunter22!"))
    )
    with pytest.raises(UsernameTaken):
        await svc.create_user(
            UserCreate(
                username="bob",
                email="bob2@x.io",
                password=SecretStr("hunter22!"),
            )
        )


async def test_create_user_duplicate_email_raises(svc: UserService) -> None:
    await svc.create_user(
        UserCreate(username="carol", email="carol@x.io", password=SecretStr("hunter22!"))
    )
    with pytest.raises(EmailTaken):
        await svc.create_user(
            UserCreate(
                username="carol2",
                email="carol@x.io",
                password=SecretStr("hunter22!"),
            )
        )


# ---------------------------------------------------------------------------
# Profile updates
# ---------------------------------------------------------------------------


async def test_update_profile_sets_fields(svc: UserService) -> None:
    user = await svc.create_user(
        UserCreate(
            username="dave",
            email="dave@x.io",
            password=SecretStr("hunter22!"),
        )
    )
    profile = await svc.update_profile(
        user.id,
        ProfileUpdate(display_name="Dave Q.", bio="Bio here"),
    )
    assert profile.display_name == "Dave Q."
    assert profile.bio == "Bio here"


async def test_update_profile_bad_orcid_raises_validation_error() -> None:
    # Pydantic validates eagerly — we don't even hit the service.
    with pytest.raises(ValueError):
        ProfileUpdate(orcid="not-an-orcid")


async def test_update_profile_accepts_canonical_orcid(svc: UserService) -> None:
    user = await svc.create_user(
        UserCreate(
            username="eve",
            email="eve@x.io",
            password=SecretStr("hunter22!"),
        )
    )
    profile = await svc.update_profile(
        user.id,
        ProfileUpdate(orcid="0000-0002-1825-0097"),
    )
    assert profile.orcid == "0000-0002-1825-0097"


async def test_update_profile_user_not_found(svc: UserService) -> None:
    import uuid

    with pytest.raises(UserNotFound):
        await svc.update_profile(uuid.uuid4(), ProfileUpdate(bio="x"))


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def test_search_users_prefix(svc: UserService) -> None:
    await svc.create_user(
        UserCreate(username="alpha", email="a@x.io", password=SecretStr("pw_secret"))
    )
    await svc.create_user(
        UserCreate(
            username="alphabet",
            email="b@x.io",
            password=SecretStr("pw_secret"),
        )
    )
    await svc.create_user(
        UserCreate(username="beta", email="c@x.io", password=SecretStr("pw_secret"))
    )
    results = await svc.search_users("@alp")
    names = {u.username for u in results}
    assert names == {"alpha", "alphabet"}


async def test_search_users_fuzzy_matches_username(svc: UserService) -> None:
    await svc.create_user(
        UserCreate(
            username="gregor", email="g@x.io", password=SecretStr("pw_secret")
        )
    )
    await svc.create_user(
        UserCreate(
            username="zelda", email="z@x.io", password=SecretStr("pw_secret")
        )
    )
    results = await svc.search_users("greg")
    assert any(u.username == "gregor" for u in results)


async def test_search_users_empty_input_returns_empty(svc: UserService) -> None:
    assert await svc.search_users("") == []
    assert await svc.search_users("   ") == []
    assert await svc.search_users("@") == []


# ---------------------------------------------------------------------------
# Recent topics / recent messages — exercises the cross-module SQL
# ---------------------------------------------------------------------------


async def _seed_topic_article_message(
    db_session: AsyncSession, svc: UserService, *, username: str, text_value: str
) -> tuple[UserService, "User", "Article"]:
    """Helper: build a published article + a message authored by ``username``.

    Kept inline (rather than as a fixture) so the test file stays
    self-contained and the cross-module imports are local.
    """
    # Local imports — the users module deliberately avoids these at top level.
    from sqlalchemy import text as sa_text

    from app.modules.articles.repository import ArticleRepository
    from app.modules.articles.schemas import ArticleCreate
    from app.modules.articles.service import ArticleService
    from app.modules.content.schemas import DocSchema
    from app.modules.forum.repository import ForumRepository
    from app.modules.forum.schemas import SectionCreate, TopicCreate
    from app.modules.forum.service import ForumService
    from app.modules.messages.repository import MessageRepository
    from app.modules.messages.schemas import MessageCreate
    from app.modules.messages.service import MessageService
    from app.modules.users.models import Role

    forum = ForumService(ForumRepository(db_session), db_session)
    articles = ArticleService(
        ArticleRepository(db_session), ForumRepository(db_session), db_session
    )
    messages = MessageService(MessageRepository(db_session), db_session)

    admin = await svc.create_user(
        UserCreate(
            username=f"adm_{username}",
            email=f"adm_{username}@x.io",
            password=SecretStr("hunter22!"),
        )
    )
    await db_session.execute(
        sa_text("UPDATE users SET role = :r WHERE id = :id"),
        {"r": Role.ADMIN.value, "id": admin.id},
    )
    await db_session.flush()
    await db_session.refresh(admin)

    author = await svc.create_user(
        UserCreate(
            username=username,
            email=f"{username}@x.io",
            password=SecretStr("hunter22!"),
        )
    )

    section_slug = f"sec-{username}"[:90]
    await forum.create_section(
        admin, SectionCreate(title=section_slug.upper(), slug=section_slug)
    )
    topic, _ = await forum.create_topic(
        admin, section_slug, TopicCreate(title=f"Topic {username}")
    )
    doc = DocSchema.model_validate(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "seed body"}],
                }
            ],
        }
    )
    article, _ = await articles.create_article(
        author, topic.id, ArticleCreate(title=f"Article {username}", content=doc)
    )
    published, _ = await articles.publish_article(author, article.id)

    message_doc = DocSchema.model_validate(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text_value}],
                }
            ],
        }
    )
    await messages.post_message(
        author, published.id, MessageCreate(content=message_doc)
    )
    return svc, author, published


async def test_recent_topics_returns_topic_after_post(
    svc: UserService, db_session: AsyncSession
) -> None:
    _, author, _published = await _seed_topic_article_message(
        db_session, svc, username="topicfan", text_value="my reply"
    )
    rows = await svc.recent_topics(author.id, limit=10)
    assert len(rows) == 1
    assert rows[0].slug == "sec-topicfan"[:90] or rows[0].slug.startswith("topic")
    assert rows[0].last_message_at is not None


async def test_recent_topics_empty_for_user_without_messages(svc: UserService) -> None:
    lonely = await svc.create_user(
        UserCreate(
            username="lonely",
            email="lonely@x.io",
            password=SecretStr("hunter22!"),
        )
    )
    assert await svc.recent_topics(lonely.id, limit=5) == []


async def test_recent_messages_returns_message_with_context(
    svc: UserService, db_session: AsyncSession
) -> None:
    _, author, published = await _seed_topic_article_message(
        db_session, svc, username="msgfan", text_value="hello world"
    )
    rows = await svc.recent_messages(author.id, limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row.article_id == published.id
    assert row.article_title == published.title
    assert row.article_slug == published.slug
    assert row.snippet == "hello world"


async def test_recent_messages_user_not_found(svc: UserService) -> None:
    import uuid as _uuid

    with pytest.raises(UserNotFound):
        await svc.recent_messages(_uuid.uuid4(), limit=5)
