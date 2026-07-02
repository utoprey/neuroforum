"""Integration test: article/message creation wires mentions + notifications.

Uses the production DI layout (``ArticleService(mention_service=…, notification_service=…)``)
to verify the cross-module hooks fire end-to-end.
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
from app.modules.mentions.repository import MentionRepository
from app.modules.mentions.service import MentionService
from app.modules.messages.repository import MessageRepository
from app.modules.messages.schemas import MessageCreate
from app.modules.messages.service import MessageService
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
def forum_svc(db_session: AsyncSession) -> ForumService:
    return ForumService(ForumRepository(db_session), db_session)


@pytest.fixture
def mention_svc(db_session: AsyncSession) -> MentionService:
    return MentionService(MentionRepository(db_session), db_session)


@pytest.fixture
def notif_svc(db_session: AsyncSession) -> NotificationService:
    return NotificationService(NotificationRepository(db_session), db_session)


@pytest.fixture
def articles_svc(
    db_session: AsyncSession,
    mention_svc: MentionService,
    notif_svc: NotificationService,
) -> ArticleService:
    return ArticleService(
        ArticleRepository(db_session),
        ForumRepository(db_session),
        db_session,
        mention_service=mention_svc,
        notification_service=notif_svc,
    )


@pytest.fixture
def messages_svc(
    db_session: AsyncSession,
    mention_svc: MentionService,
    notif_svc: NotificationService,
) -> MessageService:
    return MessageService(
        MessageRepository(db_session),
        db_session,
        mention_service=mention_svc,
        notification_service=notif_svc,
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


def _doc_with_mention(text_value: str, user_id: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": text_value},
                    {"type": "mention", "attrs": {"user_id": user_id}},
                ],
            }
        ],
    }


async def test_create_article_with_mention_records_and_notifies(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    mention_svc: MentionService,
    notif_svc: NotificationService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="iadmin", role=Role.ADMIN
    )
    author = await _make_user(users_svc, db_session, username="iauthor")
    target = await _make_user(users_svc, db_session, username="itarget")

    await forum_svc.create_section(admin, SectionCreate(title="S", slug="isec"))
    topic, _ = await forum_svc.create_topic(
        admin, "isec", TopicCreate(title="T")
    )
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(
            title="Hello target",
            content=DocSchema.model_validate(
                _doc_with_mention("hi ", str(target.id))
            ),
        ),
    )

    mentions = await mention_svc.list_my_mentions(target)
    assert len(mentions) == 1
    assert mentions[0][0].source_id == article.id

    notifs = await notif_svc.list_for_user(target)
    assert len(notifs) == 1
    assert notifs[0].type == "mention"
    assert notifs[0].payload.get("kind") == "article_mention"
    assert notifs[0].payload.get("article_id") == str(article.id)
    assert notifs[0].payload.get("article_title") == "Hello target"


async def test_edit_article_only_fans_out_new_mentions(
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    mention_svc: MentionService,
    notif_svc: NotificationService,
    db_session: AsyncSession,
) -> None:
    from app.modules.articles.schemas import ArticleUpdate

    admin = await _make_user(
        users_svc, db_session, username="iadmin2", role=Role.ADMIN
    )
    author = await _make_user(users_svc, db_session, username="iauthor2")
    target1 = await _make_user(users_svc, db_session, username="itarget1")
    target2 = await _make_user(users_svc, db_session, username="itarget2")

    await forum_svc.create_section(admin, SectionCreate(title="S", slug="isec2"))
    topic, _ = await forum_svc.create_topic(
        admin, "isec2", TopicCreate(title="T")
    )
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(
            title="hi",
            content=DocSchema.model_validate(
                _doc_with_mention("hi ", str(target1.id))
            ),
        ),
    )
    # Edit adding target2 (target1 still mentioned).
    new_doc = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "mention", "attrs": {"user_id": str(target1.id)}},
                    {"type": "mention", "attrs": {"user_id": str(target2.id)}},
                ],
            }
        ],
    }
    await articles_svc.edit_article(
        author,
        article.id,
        ArticleUpdate(content=DocSchema.model_validate(new_doc)),
    )

    # target1 still has exactly one mention (dedup), target2 has one new one.
    t1_mentions = await mention_svc.list_my_mentions(target1)
    assert len(t1_mentions) == 1
    t2_mentions = await mention_svc.list_my_mentions(target2)
    assert len(t2_mentions) == 1

    t1_notifs = await notif_svc.list_for_user(target1)
    assert len(t1_notifs) == 1
    t2_notifs = await notif_svc.list_for_user(target2)
    assert len(t2_notifs) == 1


async def test_post_message_with_mention_records_and_notifies(
    articles_svc: ArticleService,
    messages_svc: MessageService,
    forum_svc: ForumService,
    users_svc: UserService,
    mention_svc: MentionService,
    notif_svc: NotificationService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="iadminm", role=Role.ADMIN
    )
    author = await _make_user(users_svc, db_session, username="iauthorm")
    target = await _make_user(users_svc, db_session, username="itargetm")

    await forum_svc.create_section(admin, SectionCreate(title="S", slug="isecm"))
    topic, _ = await forum_svc.create_topic(
        admin, "isecm", TopicCreate(title="T")
    )
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(
            title="A",
            content=DocSchema.model_validate(
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "ok"}],
                        }
                    ],
                }
            ),
        ),
    )
    await articles_svc.publish_article(author, article.id)

    message, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(
                _doc_with_mention("ping ", str(target.id))
            )
        ),
    )

    mentions = await mention_svc.list_my_mentions(target)
    assert len(mentions) == 1
    assert mentions[0][0].source_id == message.id

    notifs = await notif_svc.list_for_user(target)
    assert len(notifs) == 1
    assert notifs[0].payload.get("kind") == "message_mention"
    assert notifs[0].payload.get("message_id") == str(message.id)
    assert notifs[0].payload.get("article_id") == str(article.id)
