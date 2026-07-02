"""Service layer for the ``dm`` module: conversation + message orchestration."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.modules.content.utils import extract_plain_text
from app.modules.dm.exceptions import (
    CannotDmYourself,
    ConversationNotFound,
    DirectMessageNotFound,
    NotEditable,
    NotParticipant,
)
from app.modules.dm.models import (
    Conversation,
    ConversationKind,
    ConversationParticipant,
    DirectMessage,
    DirectMessageStatus,
    make_dm_key,
)
from app.modules.dm.repository import DMRepository
from app.modules.dm.schemas import DirectMessageCreate, DirectMessageUpdate
from app.modules.users.exceptions import UserNotFound
from app.modules.users.models import User
from app.modules.users.repository import UserRepository

_DELETED_PLACEHOLDER = "Сообщение удалено"

# Empty ProseMirror doc — used as the soft-delete sentinel.
_EMPTY_DOC: dict[str, object] = {"type": "doc", "content": []}


class DMService:
    """Direct-message orchestration: conversations, posting, read receipts."""

    def __init__(
        self,
        repo: DMRepository,
        user_repo: UserRepository,
        db: AsyncSession,
    ) -> None:
        self._repo = repo
        self._users = user_repo
        self._db = db

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def start_dm(
        self, actor: User, target_user_id: UUID
    ) -> Conversation:
        """Open (or fetch existing) DM between ``actor`` and ``target_user_id``.

        Enforces:
        - target must exist
        - target must differ from actor
        - only one DM thread per unordered pair (UNIQUE on ``dm_key``)
        """
        if target_user_id == actor.id:
            raise CannotDmYourself(str(actor.id))

        target = await self._users.get(target_user_id)
        if target is None:
            raise UserNotFound(str(target_user_id))

        dm_key = make_dm_key(actor.id, target_user_id)
        existing = await self._repo.get_conversation_by_dm_key(dm_key)
        if existing is not None:
            return existing

        conversation = Conversation(
            kind=ConversationKind.DM,
            title=None,
            dm_key=dm_key,
        )
        await self._repo.add_conversation(conversation)

        # Two participant rows — one per side.
        await self._repo.add_participant(
            ConversationParticipant(
                conversation_id=conversation.id, user_id=actor.id
            )
        )
        await self._repo.add_participant(
            ConversationParticipant(
                conversation_id=conversation.id, user_id=target_user_id
            )
        )
        return conversation

    async def list_my_conversations(
        self, user: User, *, limit: int = 20, offset: int = 0
    ) -> list[tuple[Conversation, list[tuple[ConversationParticipant, User]], int]]:
        """Return ``(conversation, participants, unread_count)`` triples."""
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        conversations = await self._repo.list_user_conversations(
            user.id, limit=limit, offset=offset
        )
        result: list[
            tuple[Conversation, list[tuple[ConversationParticipant, User]], int]
        ] = []
        for conversation in conversations:
            participants = await self._repo.list_participants(conversation.id)
            participant = await self._repo.get_participant(
                conversation.id, user.id
            )
            last_read_at = participant.last_read_at if participant else None
            unread = await self._repo.count_unread_for_participant(
                conversation.id, user.id, last_read_at
            )
            result.append((conversation, participants, unread))
        return result

    async def _require_participant(
        self, conversation_id: UUID, user_id: UUID
    ) -> ConversationParticipant:
        conversation = await self._repo.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound(str(conversation_id))
        participant = await self._repo.get_participant(
            conversation_id, user_id
        )
        if participant is None or participant.left_at is not None:
            raise NotParticipant(str(user_id))
        return participant

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_message(
        self,
        actor: User,
        conversation_id: UUID,
        payload: DirectMessageCreate,
    ) -> tuple[DirectMessage, User]:
        await self._require_participant(conversation_id, actor.id)

        doc = payload.content
        content_text = extract_plain_text(doc)

        message = DirectMessage(
            conversation_id=conversation_id,
            author_id=actor.id,
            content=doc.model_dump(mode="json"),
            content_text=content_text,
            reply_to_id=payload.reply_to_id,
            status=DirectMessageStatus.VISIBLE,
            attachments=list(payload.attachments or []),
        )
        await self._repo.add_message(message)
        await self._db.flush()
        await self._db.refresh(
            message, attribute_names=("created_at", "updated_at")
        )

        # Bump conversation activity stamp.
        await self._repo.touch_last_message(
            conversation_id, message.created_at
        )

        return (message, actor)

    async def edit_message(
        self,
        actor: User,
        message_id: UUID,
        payload: DirectMessageUpdate,
    ) -> tuple[DirectMessage, User]:
        row = await self._repo.get_message_with_author(message_id)
        if row is None:
            raise DirectMessageNotFound(str(message_id))
        message, author = row

        if actor.id != message.author_id:
            raise NotEditable("Only the author may edit this message")
        if message.status == DirectMessageStatus.DELETED_BY_AUTHOR:
            raise NotEditable("Message has been deleted and cannot be edited")

        await self._require_participant(message.conversation_id, actor.id)

        new_doc = payload.content
        message.content = new_doc.model_dump(mode="json")
        message.content_text = extract_plain_text(new_doc)
        message.status = DirectMessageStatus.EDITED

        await self._db.flush()
        await self._db.refresh(message, attribute_names=("updated_at",))
        return (message, author)

    async def delete_message(
        self, actor: User, message_id: UUID
    ) -> tuple[DirectMessage, User]:
        row = await self._repo.get_message_with_author(message_id)
        if row is None:
            raise DirectMessageNotFound(str(message_id))
        message, author = row

        if actor.id != message.author_id:
            raise NotEditable("Only the author may delete this message")

        if message.status == DirectMessageStatus.DELETED_BY_AUTHOR:
            return (message, author)

        message.content = dict(_EMPTY_DOC)
        message.content_text = ""
        message.attachments = []
        message.status = DirectMessageStatus.DELETED_BY_AUTHOR
        await self._db.flush()
        await self._db.refresh(message, attribute_names=("updated_at",))
        return (message, author)

    async def list_messages(
        self,
        actor: User,
        conversation_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[tuple[DirectMessage, User]]:
        await self._require_participant(conversation_id, actor.id)
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        return await self._repo.list_messages_for_conversation(
            conversation_id, limit=limit, offset=offset
        )

    async def mark_read(self, actor: User, conversation_id: UUID) -> None:
        participant = await self._require_participant(
            conversation_id, actor.id
        )
        # Use the server's clock_timestamp(), not Python's, so the
        # ``last_read_at > messages.created_at`` comparison stays consistent
        # with the timestamp written by ``send_message`` (which uses
        # ``server_default=func.now()``). ``clock_timestamp()`` returns the
        # current wall-clock, unlike ``now()`` which is the transaction
        # start time.
        now_value = (
            await self._db.execute(select(func.clock_timestamp()))
        ).scalar_one()
        participant.last_read_at = now_value
        await self._db.flush()

    # ------------------------------------------------------------------
    # View-time helpers
    # ------------------------------------------------------------------

    @staticmethod
    def placeholder_for(message: DirectMessage) -> str | None:
        if message.status == DirectMessageStatus.DELETED_BY_AUTHOR:
            return _DELETED_PLACEHOLDER
        return None

    @staticmethod
    def is_redacted(message: DirectMessage) -> bool:
        return message.status == DirectMessageStatus.DELETED_BY_AUTHOR


__all__ = ["DMService"]
