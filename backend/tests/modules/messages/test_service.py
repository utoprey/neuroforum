"""Service-layer tests for the ``messages`` module."""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import Article
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.messages.exceptions import (
    ArticleNotPostable,
    MaxDepthExceeded,
    MissingEditReason,
    ParentNotInSameArticle,
    ReplyTargetNotFound,
)
from app.modules.messages.models import MessageStatus
from app.modules.messages.repository import MessageRepository
from app.modules.messages.schemas import (
    MessageCreate,
    MessageUpdate,
    ReplyTargetSchema,
    ReplyToSelectionSchema,
)
from app.modules.messages.service import MessageService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

# ---------------------------------------------------------------------------
# Fixtures + helpers
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
def messages_svc_with_notifs(db_session: AsyncSession) -> MessageService:
    """Message service wired with mention + notification fan-out."""
    from app.modules.mentions.repository import MentionRepository
    from app.modules.mentions.service import MentionService
    from app.modules.notifications.repository import NotificationRepository
    from app.modules.notifications.service import NotificationService

    return MessageService(
        MessageRepository(db_session),
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


async def _published_article(
    *,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
    section_slug: str,
) -> tuple[User, User, Article]:
    """Return ``(admin, author, article)`` with ``article.status='published'``."""
    admin = await _make_user(
        users_svc, db_session, username=f"admin_{section_slug}", role=Role.ADMIN
    )
    author = await _make_user(
        users_svc, db_session, username=f"author_{section_slug}", role=Role.USER
    )
    await forum_svc.create_section(
        admin, SectionCreate(title=section_slug.upper(), slug=section_slug)
    )
    topic, _ = await forum_svc.create_topic(
        admin, section_slug, TopicCreate(title="Topic")
    )
    article, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(title="Article", content=DocSchema.model_validate(_doc())),
    )
    published, _ = await articles_svc.publish_article(author, article.id)
    return admin, author, published


# ---------------------------------------------------------------------------
# Post: top-level + reply
# ---------------------------------------------------------------------------


async def test_post_top_level_message(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms1",
    )
    message, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("Hi"))),
    )
    assert message.depth == 0
    assert message.parent_id is None
    assert message.thread_root_id is None
    # Path is the message's own UUID (with dashes -> underscores).
    assert message.path == str(message.id).replace("-", "_")
    assert message.status == MessageStatus.VISIBLE
    assert message.content_text == "Hi"


async def test_post_reply_depth_1(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms2",
    )
    root, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("root"))),
    )
    reply, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(_doc("reply")),
            parent_id=root.id,
        ),
    )
    assert reply.depth == 1
    assert reply.parent_id == root.id
    assert reply.thread_root_id == root.id
    assert reply.path.startswith(root.path + ".")


async def test_post_deeper_reply_chain(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms3",
    )
    parent = None
    last_depth = -1
    for i in range(4):
        msg, _ = await messages_svc.post_message(
            author,
            article.id,
            MessageCreate(
                content=DocSchema.model_validate(_doc(f"d{i}")),
                parent_id=parent.id if parent is not None else None,
            ),
        )
        assert msg.depth == last_depth + 1
        last_depth = msg.depth
        parent = msg
    assert parent is not None
    assert parent.depth == 3


async def test_post_depth_limit_exceeded(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms4",
    )
    parent = None
    # depth 0..8 inclusive == 9 levels, which is the cap.
    for _ in range(9):
        msg, _ = await messages_svc.post_message(
            author,
            article.id,
            MessageCreate(
                content=DocSchema.model_validate(_doc("x")),
                parent_id=parent.id if parent is not None else None,
            ),
        )
        parent = msg
    assert parent is not None
    assert parent.depth == 8
    with pytest.raises(MaxDepthExceeded):
        await messages_svc.post_message(
            author,
            article.id,
            MessageCreate(
                content=DocSchema.model_validate(_doc("too deep")),
                parent_id=parent.id,
            ),
        )


async def test_post_on_unpublished_article_rejected(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="admin_ms5", role=Role.ADMIN
    )
    author = await _make_user(users_svc, db_session, username="author_ms5")
    await forum_svc.create_section(
        admin, SectionCreate(title="S", slug="ms5")
    )
    topic, _ = await forum_svc.create_topic(
        admin, "ms5", TopicCreate(title="T")
    )
    draft, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(title="Draft", content=DocSchema.model_validate(_doc())),
    )
    # Draft, not published.
    with pytest.raises(ArticleNotPostable):
        await messages_svc.post_message(
            author,
            draft.id,
            MessageCreate(content=DocSchema.model_validate(_doc())),
        )


async def test_post_reply_parent_in_different_article(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    admin = await _make_user(
        users_svc, db_session, username="admin_ms6", role=Role.ADMIN
    )
    author = await _make_user(users_svc, db_session, username="author_ms6")
    await forum_svc.create_section(admin, SectionCreate(title="S", slug="ms6"))
    topic, _ = await forum_svc.create_topic(
        admin, "ms6", TopicCreate(title="T")
    )
    a1, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(title="A1", content=DocSchema.model_validate(_doc())),
    )
    a2, _ = await articles_svc.create_article(
        author,
        topic.id,
        ArticleCreate(title="A2", content=DocSchema.model_validate(_doc())),
    )
    a1, _ = await articles_svc.publish_article(author, a1.id)
    a2, _ = await articles_svc.publish_article(author, a2.id)
    root_in_a1, _ = await messages_svc.post_message(
        author,
        a1.id,
        MessageCreate(content=DocSchema.model_validate(_doc())),
    )
    with pytest.raises(ParentNotInSameArticle):
        await messages_svc.post_message(
            author,
            a2.id,
            MessageCreate(
                content=DocSchema.model_validate(_doc()),
                parent_id=root_in_a1.id,
            ),
        )


# ---------------------------------------------------------------------------
# Reply-on-selection target validation
# ---------------------------------------------------------------------------


async def test_reply_to_selection_valid_article_target(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms7",
    )
    selection = ReplyToSelectionSchema.model_validate(
        {
            "target": {"type": "article", "id": str(article.id)},
            "block_path": [0],
            "from": 0,
            "to": 5,
            "quote_text": "Hello",
        }
    )
    message, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(_doc("Quote!")),
            reply_to_selection=selection,
        ),
    )
    assert message.reply_to_selection is not None
    assert message.reply_to_selection["target"]["type"] == "article"


async def test_reply_to_selection_target_not_found(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms8",
    )
    selection = ReplyToSelectionSchema(
        target=ReplyTargetSchema(type="message", id=uuid.uuid4()),
        block_path=[0],
        from_=0,
        to=1,
        quote_text="x",
    )
    with pytest.raises(ReplyTargetNotFound):
        await messages_svc.post_message(
            author,
            article.id,
            MessageCreate(
                content=DocSchema.model_validate(_doc()),
                reply_to_selection=selection,
            ),
        )


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


async def test_author_edits_without_reason(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms9",
    )
    message, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("v0"))),
    )
    edited, _ = await messages_svc.edit_message(
        author,
        message.id,
        MessageUpdate(content=DocSchema.model_validate(_doc("v1"))),
    )
    assert edited.status == MessageStatus.EDITED
    assert edited.content_text == "v1"


async def test_moderator_must_provide_reason(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms10",
    )
    message, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("v0"))),
    )
    mod = await _make_user(
        users_svc, db_session, username="mod_ms10", role=Role.MODERATOR
    )
    with pytest.raises(MissingEditReason):
        await messages_svc.edit_message(
            mod,
            message.id,
            MessageUpdate(content=DocSchema.model_validate(_doc("v1"))),
        )
    # With a reason it goes through.
    edited, _ = await messages_svc.edit_message(
        mod,
        message.id,
        MessageUpdate(
            content=DocSchema.model_validate(_doc("v1")),
            edit_reason="moderation",
        ),
    )
    assert edited.status == MessageStatus.EDITED


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------


async def test_soft_delete_by_author(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms11",
    )
    message, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("bye"))),
    )
    deleted, _ = await messages_svc.soft_delete_message(author, message.id)
    assert deleted.status == MessageStatus.DELETED_BY_AUTHOR
    assert deleted.content == {"type": "doc", "content": []}
    assert deleted.content_text == ""
    assert MessageService.placeholder_for(deleted) == "Сообщение удалено автором"


async def test_soft_delete_by_moderator(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms12",
    )
    message, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("naughty"))),
    )
    mod = await _make_user(
        users_svc, db_session, username="mod_ms12", role=Role.MODERATOR
    )
    hidden, _ = await messages_svc.soft_delete_message(mod, message.id)
    assert hidden.status == MessageStatus.HIDDEN_BY_MOD
    assert MessageService.placeholder_for(hidden) == "Скрыто модератором"


# ---------------------------------------------------------------------------
# Thread listing
# ---------------------------------------------------------------------------


async def test_get_thread_returns_descendants_in_order(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms13",
    )
    root, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("root"))),
    )
    child1, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(_doc("c1")),
            parent_id=root.id,
        ),
    )
    grandchild, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(_doc("gc")),
            parent_id=child1.id,
        ),
    )
    # Unrelated top-level message that should NOT appear in the subtree.
    unrelated, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("other"))),
    )

    rows = await messages_svc.get_thread(root.id)
    ids = [m.id for m, _ in rows]
    assert ids == [root.id, child1.id, grandchild.id]
    assert unrelated.id not in ids


async def test_list_for_article_includes_immediate_children(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms14",
    )
    root, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("root"))),
    )
    child, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(_doc("child")),
            parent_id=root.id,
        ),
    )
    rows = await messages_svc.list_for_article(article.id)
    ids = [m.id for m, _ in rows]
    assert root.id in ids
    assert child.id in ids


# ---------------------------------------------------------------------------
# Comment count
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Notification payloads
# ---------------------------------------------------------------------------


async def test_message_reply_notification_payload(
    messages_svc_with_notifs: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Posting a reply to someone else's message fires a ``type='reply'``
    notification with rich payload (article_title, message_id, snippet)."""
    from app.modules.notifications.repository import NotificationRepository
    from app.modules.notifications.service import NotificationService

    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms_reply_payload",
    )
    # Post the root message as the article author …
    root, _ = await messages_svc_with_notifs.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("root"))),
    )
    # … then have another user reply to it.
    replier = await _make_user(
        users_svc, db_session, username="replier_payload"
    )
    reply, _ = await messages_svc_with_notifs.post_message(
        replier,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(_doc("nice point!")),
            parent_id=root.id,
        ),
    )
    notif_svc = NotificationService(NotificationRepository(db_session), db_session)
    notifs = await notif_svc.list_for_user(author)
    reply_notifs = [n for n in notifs if n.type == "reply"]
    assert len(reply_notifs) == 1
    payload = reply_notifs[0].payload
    assert payload["kind"] == "reply"
    assert payload["article_id"] == str(article.id)
    assert payload["article_title"] == article.title
    assert payload["message_id"] == str(reply.id)
    assert payload["parent_message_id"] == str(root.id)
    assert payload["author_id"] == str(replier.id)
    assert payload["author_username"] == "replier_payload"
    assert payload["snippet"].startswith("nice point")


async def test_message_reply_to_own_post_no_notification(
    messages_svc_with_notifs: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Replying to your own message should NOT generate a self-notification."""
    from app.modules.notifications.repository import NotificationRepository
    from app.modules.notifications.service import NotificationService

    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms_reply_self",
    )
    root, _ = await messages_svc_with_notifs.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("root"))),
    )
    await messages_svc_with_notifs.post_message(
        author,
        article.id,
        MessageCreate(
            content=DocSchema.model_validate(_doc("self reply")),
            parent_id=root.id,
        ),
    )
    notif_svc = NotificationService(NotificationRepository(db_session), db_session)
    notifs = await notif_svc.list_for_user(author)
    assert not [n for n in notifs if n.type == "reply"]


async def test_message_mention_notification_payload(
    messages_svc_with_notifs: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Mentioning a user in a message emits ``type='mention'`` with
    article_title and message_id so the UI can deep-link the message."""
    from app.modules.notifications.repository import NotificationRepository
    from app.modules.notifications.service import NotificationService

    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms_mention_payload",
    )
    mentioned = await _make_user(
        users_svc, db_session, username="mentioned_msg_payload"
    )
    doc_with_mention = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Hey "},
                    {
                        "type": "mention",
                        "attrs": {"user_id": str(mentioned.id)},
                    },
                    {"type": "text", "text": " check this out"},
                ],
            }
        ],
    }
    msg, _ = await messages_svc_with_notifs.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(doc_with_mention)),
    )
    notif_svc = NotificationService(NotificationRepository(db_session), db_session)
    notifs = await notif_svc.list_for_user(mentioned)
    mention_notifs = [n for n in notifs if n.type == "mention"]
    assert len(mention_notifs) == 1
    payload = mention_notifs[0].payload
    assert payload["kind"] == "message_mention"
    assert payload["article_id"] == str(article.id)
    assert payload["article_title"] == article.title
    assert payload["message_id"] == str(msg.id)
    assert payload["author_id"] == str(author.id)
    assert payload["author_username"] == author.username


async def test_article_comment_count_increments(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms15",
    )
    assert article.comment_count == 0
    await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("first"))),
    )
    await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("second"))),
    )
    refreshed = (
        await db_session.execute(
            select(Article).where(Article.id == article.id)
        )
    ).scalar_one()
    assert refreshed.comment_count == 2


async def test_article_comment_count_decrements_on_soft_delete(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Soft-deleting a message rolls the article.comment_count back by one.

    Idempotency: repeated deletes (already-deleted) do NOT double-decrement.
    """
    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms_cc_dec",
    )
    msg, _ = await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("hi"))),
    )
    refreshed = (
        await db_session.execute(select(Article).where(Article.id == article.id))
    ).scalar_one()
    assert refreshed.comment_count == 1

    await messages_svc.soft_delete_message(author, msg.id)
    refreshed = (
        await db_session.execute(select(Article).where(Article.id == article.id))
    ).scalar_one()
    assert refreshed.comment_count == 0

    # Idempotent second delete must NOT push the counter into negatives.
    await messages_svc.soft_delete_message(author, msg.id)
    refreshed = (
        await db_session.execute(select(Article).where(Article.id == article.id))
    ).scalar_one()
    assert refreshed.comment_count == 0


async def test_user_stats_messages_count_increments(
    messages_svc: MessageService,
    articles_svc: ArticleService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    """Posting a message bumps user_stats.messages_count for the author."""
    from app.modules.users.models import UserStats

    _admin, author, article = await _published_article(
        articles_svc=articles_svc,
        forum_svc=forum_svc,
        users_svc=users_svc,
        db_session=db_session,
        section_slug="ms_msgs_cnt",
    )
    stats = (
        await db_session.execute(
            select(UserStats).where(UserStats.user_id == author.id)
        )
    ).scalar_one()
    assert stats.messages_count == 0

    await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("one"))),
    )
    await messages_svc.post_message(
        author,
        article.id,
        MessageCreate(content=DocSchema.model_validate(_doc("two"))),
    )
    await db_session.refresh(stats)
    assert stats.messages_count == 2

    # Soft delete is intentionally NOT decrementing — the placeholder still
    # appears in the author's history.
    msg_id = (
        await db_session.execute(
            text("SELECT id FROM messages WHERE author_id = :a LIMIT 1"),
            {"a": author.id},
        )
    ).scalar_one()
    await messages_svc.soft_delete_message(author, uuid.UUID(str(msg_id)))
    await db_session.refresh(stats)
    assert stats.messages_count == 2
