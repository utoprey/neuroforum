"""Message business logic: posting, editing, soft-delete, thread listing.

Threading model
---------------
Each message stores a materialised LTREE ``path`` whose segments are the
ancestor message UUIDs (with ``-`` replaced by ``_`` since LTREE labels
only accept ``[A-Za-z0-9_]+``). Top-level messages have a single-segment
``path`` of their own UUID; replies extend the parent's ``path`` with their
own segment. Subtree queries use the ``<@`` LTREE operator.

The service also enforces the ``depth <= 8`` rule (data-model.md) in code
rather than at the DB level — easier to relax later — and bumps the
denormalised ``articles.comment_count`` on insert.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import Article, ArticleStatus
from app.modules.content.utils import (
    extract_mentioned_user_ids,
    extract_plain_text,
)
from app.modules.mentions.models import MentionSourceType
from app.modules.mentions.service import MentionService
from app.modules.messages.exceptions import (
    ArticleNotPostable,
    MaxDepthExceeded,
    MessageNotFound,
    MissingEditReason,
    NotEditable,
    ParentNotInSameArticle,
    ReplyTargetNotFound,
)
from app.modules.messages.models import Message, MessageRevision, MessageStatus
from app.modules.messages.repository import MessageRepository
from app.modules.messages.schemas import (
    MessageCreate,
    MessageUpdate,
    ReplyToSelectionSchema,
)
from app.modules.notifications.service import NotificationService
from app.modules.users.models import Role, User
from app.modules.users.service import UserService

_MOD_OR_ADMIN: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})

# Max allowed thread depth — root level is 0, so 8 lets us go 9 levels deep
# (0..8 inclusive). Enforced in service per data-model.md.
_MAX_DEPTH = 8

_DELETED_PLACEHOLDER = "Сообщение удалено автором"
_HIDDEN_PLACEHOLDER = "Скрыто модератором"

# Empty ProseMirror doc — used as the soft-delete sentinel.
_EMPTY_DOC: dict[str, object] = {"type": "doc", "content": []}


def _uuid_to_ltree_label(value: UUID) -> str:
    """Convert a UUID to a valid LTREE label (``[A-Za-z0-9_]+``)."""
    return str(value).replace("-", "_")


class MessageService:
    """Orchestrates message CRUD with content validation + RBAC + soft delete."""

    def __init__(
        self,
        repo: MessageRepository,
        db: AsyncSession,
        mention_service: MentionService | None = None,
        notification_service: NotificationService | None = None,
        user_service: UserService | None = None,
    ) -> None:
        self._repo = repo
        self._db = db
        # Optional cross-module hooks. Existing tests instantiate this
        # service without them — both fan-out steps then silently no-op.
        self._mentions = mention_service
        self._notifications = notification_service
        # Optional user lookup for enriching notification payloads.
        self._users = user_service

    # ------------------------------------------------------------------
    # Post
    # ------------------------------------------------------------------

    async def post_message(
        self,
        actor: User,
        article_id: UUID,
        payload: MessageCreate,
    ) -> tuple[Message, User]:
        """Create a top-level or reply message under a published article."""
        article = await self._db.get(Article, article_id)
        if article is None or article.status != ArticleStatus.PUBLISHED:
            raise ArticleNotPostable(str(article_id))

        parent: Message | None = None
        if payload.parent_id is not None:
            parent = await self._repo.get(payload.parent_id)
            if parent is None:
                raise MessageNotFound(str(payload.parent_id))
            if parent.article_id != article_id:
                raise ParentNotInSameArticle(str(payload.parent_id))

        depth = (parent.depth + 1) if parent is not None else 0
        if depth > _MAX_DEPTH:
            raise MaxDepthExceeded(
                f"depth {depth} exceeds maximum thread depth {_MAX_DEPTH}"
            )

        # Validate ``reply_to_selection.target`` actually exists.
        await self._verify_reply_target(payload.reply_to_selection)

        new_id = uuid4()
        own_label = _uuid_to_ltree_label(new_id)
        if parent is not None:
            path = f"{parent.path}.{own_label}"
            thread_root_id = parent.thread_root_id or parent.id
        else:
            path = own_label
            thread_root_id = None

        doc = payload.content
        content_text = extract_plain_text(doc)
        mentioned = sorted(extract_mentioned_user_ids(doc))

        message = Message(
            id=new_id,
            article_id=article_id,
            parent_id=parent.id if parent is not None else None,
            thread_root_id=thread_root_id,
            depth=depth,
            path=path,
            author_id=actor.id,
            content=doc.model_dump(mode="json"),
            content_text=content_text,
            reply_to_selection=(
                payload.reply_to_selection.model_dump(mode="json", by_alias=True)
                if payload.reply_to_selection is not None
                else None
            ),
            status=MessageStatus.VISIBLE,
            mentioned_user_ids=mentioned,
        )
        await self._repo.add(message)

        # Bump article.comment_count atomically.
        await self._db.execute(
            update(Article)
            .where(Article.id == article_id)
            .values(comment_count=Article.comment_count + 1)
        )
        # Bump messages_count on the author's user_stats.
        await self._bump_user_messages_count(actor.id, +1)
        await self._db.flush()
        await self._db.refresh(message, attribute_names=("created_at", "updated_at"))

        # Cross-module fan-out: persist mention rows + emit notifications.
        if mentioned:
            await self._fan_out_mentions(
                message, actor, article, set(mentioned)
            )
        # Reply notification — fire when this message has a parent and the
        # parent author isn't the actor themselves.
        if parent is not None and parent.author_id != actor.id:
            await self._notify_reply(message, parent, actor, article)
        return (message, actor)

    async def _fan_out_mentions(
        self,
        message: Message,
        actor: User,
        article: Article,
        new_mention_ids: set[UUID],
    ) -> None:
        """Record new mention rows and emit ``type='mention'`` notifications.

        Payload carries enough context to render
        "@bob mentioned you in discussion *Article title*" on the frontend
        and link to ``/articles/{article_id}#message-{message_id}``.
        """
        if not new_mention_ids or self._mentions is None:
            return
        new_rows = await self._mentions.record_mentions(
            MentionSourceType.MESSAGE,
            message.id,
            actor.id,
            new_mention_ids,
        )
        if not new_rows or self._notifications is None:
            return
        author_username = actor.username
        author_display_name = (
            actor.profile.display_name if actor.profile else None
        )
        snippet = (message.content_text or "")[:140]
        article_title = article.title if article is not None else ""
        for mention in new_rows:
            payload = {
                "kind": "message_mention",
                "article_id": str(message.article_id),
                "article_title": article_title,
                "message_id": str(message.id),
                "author_id": str(actor.id),
                "author_username": author_username,
                "author_display_name": author_display_name,
                "snippet": snippet,
            }
            await self._notifications.create_notification(
                user_id=mention.mentioned_user_id,
                type="mention",
                payload=payload,
            )

    async def _notify_reply(
        self,
        message: Message,
        parent: Message,
        actor: User,
        article: Article,
    ) -> None:
        """Send a ``type='reply'`` notification to the parent message's author."""
        if self._notifications is None:
            return
        author_username = actor.username
        author_display_name = (
            actor.profile.display_name if actor.profile else None
        )
        snippet = (message.content_text or "")[:140]
        article_title = article.title if article is not None else ""
        payload = {
            "kind": "reply",
            "article_id": str(message.article_id),
            "article_title": article_title,
            "message_id": str(message.id),
            "parent_message_id": str(parent.id),
            "author_id": str(actor.id),
            "author_username": author_username,
            "author_display_name": author_display_name,
            "snippet": snippet,
        }
        await self._notifications.create_notification(
            user_id=parent.author_id,
            type="reply",
            payload=payload,
        )

    async def _verify_reply_target(
        self, selection: ReplyToSelectionSchema | None
    ) -> None:
        """Confirm ``selection.target`` points at a real article/message of the right type."""
        if selection is None:
            return
        target = selection.target
        if target.type == "article":
            row = await self._db.execute(
                select(Article.id).where(Article.id == target.id)
            )
            if row.scalar_one_or_none() is None:
                raise ReplyTargetNotFound(f"article {target.id}")
        else:  # "message"
            row = await self._db.execute(
                select(Message.id).where(Message.id == target.id)
            )
            if row.scalar_one_or_none() is None:
                raise ReplyTargetNotFound(f"message {target.id}")

    # ------------------------------------------------------------------
    # Edit (with revision snapshot)
    # ------------------------------------------------------------------

    async def edit_message(
        self, actor: User, message_id: UUID, payload: MessageUpdate
    ) -> tuple[Message, User]:
        row = await self._repo.get_with_author(message_id)
        if row is None:
            raise MessageNotFound(str(message_id))
        message, author = row

        if message.status in (
            MessageStatus.HIDDEN_BY_MOD,
            MessageStatus.DELETED_BY_AUTHOR,
        ):
            raise NotEditable("Message is hidden or deleted")

        is_author = actor.id == message.author_id
        is_mod = actor.role in _MOD_OR_ADMIN
        if not is_author and not is_mod:
            raise NotEditable(
                "Only the author or a moderator/admin may edit this message"
            )
        edit_reason = payload.edit_reason
        # Mod/admin acting on someone else's message must supply a reason.
        if not is_author and not (edit_reason and edit_reason.strip()):
            raise MissingEditReason(
                "edit_reason is required when a moderator edits another user's message"
            )

        # --- Snapshot prior state -----------------------------------------
        next_rev = await self._repo.max_revision_for_message(message.id) + 1
        snapshot = MessageRevision(
            message_id=message.id,
            revision=next_rev,
            editor_id=actor.id,
            editor_role_at_edit=actor.role.value,
            content=message.content,
            edit_reason=edit_reason,
        )
        await self._repo.add_revision(snapshot)

        # --- Apply patch ---------------------------------------------------
        previous_mentions: set[UUID] = set(message.mentioned_user_ids or [])
        new_doc = payload.content
        message.content = new_doc.model_dump(mode="json")
        message.content_text = extract_plain_text(new_doc)
        message.mentioned_user_ids = sorted(extract_mentioned_user_ids(new_doc))
        message.status = MessageStatus.EDITED

        await self._db.flush()
        await self._db.refresh(message, attribute_names=("updated_at",))

        # Fan out only NEW mentions (not in the prior revision).
        current_mentions: set[UUID] = set(message.mentioned_user_ids or [])
        newly_mentioned = current_mentions - previous_mentions
        if newly_mentioned:
            article = await self._db.get(Article, message.article_id)
            if article is not None:
                await self._fan_out_mentions(
                    message, actor, article, newly_mentioned
                )
        return (message, author)

    # ------------------------------------------------------------------
    # Soft delete
    # ------------------------------------------------------------------

    async def soft_delete_message(
        self, actor: User, message_id: UUID
    ) -> tuple[Message, User]:
        row = await self._repo.get_with_author(message_id)
        if row is None:
            raise MessageNotFound(str(message_id))
        message, author = row

        is_author = actor.id == message.author_id
        is_mod = actor.role in _MOD_OR_ADMIN
        if not is_author and not is_mod:
            raise NotEditable(
                "Only the author or a moderator/admin may delete this message"
            )

        # Already-soft-deleted messages are idempotent no-ops at this layer.
        if message.status in (
            MessageStatus.HIDDEN_BY_MOD,
            MessageStatus.DELETED_BY_AUTHOR,
        ):
            return (message, author)

        # --- Snapshot prior state -----------------------------------------
        next_rev = await self._repo.max_revision_for_message(message.id) + 1
        snapshot = MessageRevision(
            message_id=message.id,
            revision=next_rev,
            editor_id=actor.id,
            editor_role_at_edit=actor.role.value,
            content=message.content,
            edit_reason=None,
        )
        await self._repo.add_revision(snapshot)

        # --- Null content + flip status ------------------------------------
        message.content = dict(_EMPTY_DOC)
        message.content_text = ""
        message.mentioned_user_ids = []
        # Author delete vs moderator hide are distinguishable in the UI.
        message.status = (
            MessageStatus.DELETED_BY_AUTHOR
            if is_author
            else MessageStatus.HIDDEN_BY_MOD
        )

        # Decrement article.comment_count — the message no longer renders as
        # a visible comment. Guarded by the earlier idempotency check so we
        # never double-decrement on repeated calls.
        await self._db.execute(
            update(Article)
            .where(Article.id == message.article_id)
            .values(comment_count=Article.comment_count - 1)
        )
        # ``messages_count`` is deliberately *not* decremented — soft-deleted
        # messages still appear in the author's history as placeholders.

        await self._db.flush()
        await self._db.refresh(message, attribute_names=("updated_at",))
        return (message, author)

    async def _bump_user_messages_count(self, user_id: UUID, delta: int) -> None:
        """Atomic bump of ``user_stats.messages_count`` via UserRepository."""
        from app.modules.users.repository import UserRepository

        await UserRepository(self._db).increment_stat(
            user_id, "messages_count", delta
        )

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    async def list_for_article(
        self,
        article_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[tuple[Message, User]]:
        """Return top-level messages plus their immediate (depth-1) children.

        For a deeper subtree, callers use :meth:`get_thread`.
        """
        top = await self._repo.list_top_level_for_article(
            article_id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )
        if not top:
            return []
        children = await self._repo.list_direct_children(
            [m.id for m, _ in top]
        )
        # Stable order: top-level rows first (in creation order), then each
        # row's children in creation order behind it.
        children_by_parent: dict[UUID, list[tuple[Message, User]]] = {}
        for msg, author in children:
            assert msg.parent_id is not None  # narrowed by the SQL filter
            children_by_parent.setdefault(msg.parent_id, []).append((msg, author))

        out: list[tuple[Message, User]] = []
        for msg, author in top:
            out.append((msg, author))
            out.extend(children_by_parent.get(msg.id, []))
        return out

    async def get_thread(
        self, message_root_id: UUID
    ) -> list[tuple[Message, User]]:
        """Return every descendant of ``message_root_id`` (root included), in path order."""
        root = await self._repo.get(message_root_id)
        if root is None:
            raise MessageNotFound(str(message_root_id))
        return await self._repo.list_descendants_by_path(root.path)

    # ------------------------------------------------------------------
    # View-time serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def placeholder_for(message: Message) -> str | None:
        if message.status == MessageStatus.DELETED_BY_AUTHOR:
            return _DELETED_PLACEHOLDER
        if message.status == MessageStatus.HIDDEN_BY_MOD:
            return _HIDDEN_PLACEHOLDER
        return None

    @staticmethod
    def is_redacted(message: Message) -> bool:
        return message.status in (
            MessageStatus.DELETED_BY_AUTHOR,
            MessageStatus.HIDDEN_BY_MOD,
        )

__all__ = ["MessageService"]
