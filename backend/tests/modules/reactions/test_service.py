"""Service-layer tests for the ``reactions`` module."""

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
from app.modules.messages.repository import MessageRepository
from app.modules.messages.schemas import MessageCreate
from app.modules.messages.service import MessageService
from app.modules.reactions.exceptions import ArticleNotFound, MessageNotFound
from app.modules.reactions.models import ReactionKind
from app.modules.reactions.service import ReactionService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def messages_svc(db_session: AsyncSession) -> MessageService:
    return MessageService(MessageRepository(db_session), db_session)


@pytest.fixture
def reactions_svc(db_session: AsyncSession) -> ReactionService:
    return ReactionService(db_session)


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


def _doc(text_value: str = "Hello") -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text_value}],
            }
        ],
    }


async def _bootstrap(
    *,
    users_svc: UserService,
    forum_svc: ForumService,
    articles_svc: ArticleService,
    db_session: AsyncSession,
    slug: str,
) -> tuple[User, User, str]:
    """Returns ``(admin, author, published_article_id)``."""
    admin = await _make_user(
        users_svc, db_session, username=f"admin_{slug}", role=Role.ADMIN
    )
    author = await _make_user(users_svc, db_session, username=f"author_{slug}")
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
    return admin, author, str(pub.id)


# ---------------------------------------------------------------------------
# Article reactions
# ---------------------------------------------------------------------------


async def test_react_to_article_increments_counter(
    reactions_svc: ReactionService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs1",
    )
    from uuid import UUID

    await reactions_svc.react_to_article(author, UUID(article_id), ReactionKind.BRAIN)
    summary = await reactions_svc.get_article_reactions(UUID(article_id))
    assert summary == [
        type(summary[0])(kind=ReactionKind.BRAIN, count=1)
    ]


async def test_react_idempotent(
    reactions_svc: ReactionService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs2",
    )
    aid = UUID(article_id)
    await reactions_svc.react_to_article(author, aid, ReactionKind.DNA)
    # Double react with same kind: the row already exists, no error, no count
    # change.
    await reactions_svc.react_to_article(author, aid, ReactionKind.DNA)
    summary = await reactions_svc.get_article_reactions(aid)
    assert any(s.kind == ReactionKind.DNA and s.count == 1 for s in summary)


async def test_unreact_idempotent(
    reactions_svc: ReactionService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs3",
    )
    aid = UUID(article_id)
    # Unreact when nothing was reacted: no-op, no exception.
    await reactions_svc.unreact_article(author, aid, ReactionKind.NEURON)
    summary = await reactions_svc.get_article_reactions(aid)
    assert summary == []


async def test_unreact_decrements_and_removes(
    reactions_svc: ReactionService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs4",
    )
    aid = UUID(article_id)
    await reactions_svc.react_to_article(author, aid, ReactionKind.SYNAPSE)
    summary = await reactions_svc.get_article_reactions(aid)
    assert any(s.kind == ReactionKind.SYNAPSE and s.count == 1 for s in summary)
    await reactions_svc.unreact_article(author, aid, ReactionKind.SYNAPSE)
    summary = await reactions_svc.get_article_reactions(aid)
    # When count hits 0 we drop the key entirely.
    assert all(s.kind != ReactionKind.SYNAPSE for s in summary)


async def test_react_missing_article_raises(
    reactions_svc: ReactionService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import uuid4

    user = await _make_user(users_svc, db_session, username="rs5")
    with pytest.raises(ArticleNotFound):
        await reactions_svc.react_to_article(user, uuid4(), ReactionKind.BRAIN)


# ---------------------------------------------------------------------------
# Message reactions
# ---------------------------------------------------------------------------


async def test_react_to_message_counter(
    reactions_svc: ReactionService,
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs6",
    )
    aid = UUID(article_id)
    message, _ = await messages_svc.post_message(
        author,
        aid,
        MessageCreate(content=DocSchema.model_validate(_doc("hi"))),
    )
    await reactions_svc.react_to_message(author, message.id, ReactionKind.MINDBLOWN)
    await reactions_svc.react_to_message(author, message.id, ReactionKind.PETRI)
    summary = await reactions_svc.get_message_reactions(message.id)
    kinds = {s.kind for s in summary}
    assert ReactionKind.MINDBLOWN in kinds
    assert ReactionKind.PETRI in kinds


async def test_react_missing_message_raises(
    reactions_svc: ReactionService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import uuid4

    user = await _make_user(users_svc, db_session, username="rs7")
    with pytest.raises(MessageNotFound):
        await reactions_svc.react_to_message(user, uuid4(), ReactionKind.BRAIN)


async def test_two_users_independent_reactions(
    reactions_svc: ReactionService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    from uuid import UUID

    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs8",
    )
    aid = UUID(article_id)
    other = await _make_user(users_svc, db_session, username="other_rs8")
    await reactions_svc.react_to_article(author, aid, ReactionKind.LIGHTBULB)
    await reactions_svc.react_to_article(other, aid, ReactionKind.LIGHTBULB)
    summary = await reactions_svc.get_article_reactions(aid)
    bulb = [s for s in summary if s.kind == ReactionKind.LIGHTBULB]
    assert len(bulb) == 1
    assert bulb[0].count == 2


async def test_article_reaction_bumps_author_received_reactions(
    reactions_svc: ReactionService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """React/unreact on an article maintains author's received_reactions_count."""
    from uuid import UUID

    from sqlalchemy import select

    from app.modules.users.models import UserStats

    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs_rr1",
    )
    aid = UUID(article_id)
    other = await _make_user(users_svc, db_session, username="other_rr1")
    stats = (
        await db_session.execute(
            select(UserStats).where(UserStats.user_id == author.id)
        )
    ).scalar_one()
    assert stats.received_reactions_count == 0

    await reactions_svc.react_to_article(other, aid, ReactionKind.BRAIN)
    await db_session.refresh(stats)
    assert stats.received_reactions_count == 1

    # Double-react with same kind is idempotent — no extra bump.
    await reactions_svc.react_to_article(other, aid, ReactionKind.BRAIN)
    await db_session.refresh(stats)
    assert stats.received_reactions_count == 1

    # Unreact rolls the counter back.
    await reactions_svc.unreact_article(other, aid, ReactionKind.BRAIN)
    await db_session.refresh(stats)
    assert stats.received_reactions_count == 0


async def test_message_reaction_bumps_author_received_reactions(
    reactions_svc: ReactionService,
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """React on a message bumps received_reactions_count for message author."""
    from uuid import UUID

    from sqlalchemy import select

    from app.modules.users.models import UserStats

    _admin, author, article_id = await _bootstrap(
        users_svc=users_svc,
        forum_svc=forum_svc,
        articles_svc=articles_svc,
        db_session=db_session,
        slug="rs_rr2",
    )
    # The article author also writes the message we'll react to.
    msg, _ = await messages_svc.post_message(
        author,
        UUID(article_id),
        MessageCreate(content=DocSchema.model_validate(_doc("ping"))),
    )
    reactor = await _make_user(users_svc, db_session, username="reactor_rr2")

    stats = (
        await db_session.execute(
            select(UserStats).where(UserStats.user_id == author.id)
        )
    ).scalar_one()
    base = stats.received_reactions_count

    await reactions_svc.react_to_message(reactor, msg.id, ReactionKind.NEURON)
    await db_session.refresh(stats)
    assert stats.received_reactions_count == base + 1

    await reactions_svc.unreact_message(reactor, msg.id, ReactionKind.NEURON)
    await db_session.refresh(stats)
    assert stats.received_reactions_count == base
