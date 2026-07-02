"""Data access for the ``dm`` module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.dm.models import (
    Conversation,
    ConversationParticipant,
    DirectMessage,
)
from app.modules.users.models import User


class DMRepository:
    """Thin DAL over conversations + direct messages."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ----- Conversations --------------------------------------------------

    async def get_conversation(
        self, conversation_id: UUID
    ) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_conversation_by_dm_key(
        self, dm_key: str
    ) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.dm_key == dm_key)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def add_conversation(self, conversation: Conversation) -> Conversation:
        self._db.add(conversation)
        await self._db.flush()
        return conversation

    async def touch_last_message(
        self, conversation_id: UUID, ts: datetime
    ) -> None:
        conversation = await self.get_conversation(conversation_id)
        if conversation is not None:
            conversation.last_message_at = ts
            await self._db.flush()

    # ----- Participants ---------------------------------------------------

    async def add_participant(
        self, participant: ConversationParticipant
    ) -> ConversationParticipant:
        self._db.add(participant)
        await self._db.flush()
        return participant

    async def get_participant(
        self, conversation_id: UUID, user_id: UUID
    ) -> ConversationParticipant | None:
        stmt = select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_participants(
        self, conversation_id: UUID
    ) -> list[tuple[ConversationParticipant, User]]:
        stmt = (
            select(ConversationParticipant, User)
            .join(User, User.id == ConversationParticipant.user_id)
            .where(ConversationParticipant.conversation_id == conversation_id)
            .options(selectinload(User.profile))
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def list_user_conversations(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> list[Conversation]:
        """Conversations the user participates in, newest activity first."""
        stmt = (
            select(Conversation)
            .join(
                ConversationParticipant,
                ConversationParticipant.conversation_id == Conversation.id,
            )
            .where(ConversationParticipant.user_id == user_id)
            .order_by(
                # NULLS LAST for never-used conversations.
                desc(Conversation.last_message_at).nulls_last(),
                desc(Conversation.created_at),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    # ----- Messages -------------------------------------------------------

    async def add_message(self, message: DirectMessage) -> DirectMessage:
        self._db.add(message)
        await self._db.flush()
        return message

    async def get_message(self, message_id: UUID) -> DirectMessage | None:
        stmt = select(DirectMessage).where(DirectMessage.id == message_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_message_with_author(
        self, message_id: UUID
    ) -> tuple[DirectMessage, User] | None:
        stmt = (
            select(DirectMessage, User)
            .join(User, User.id == DirectMessage.author_id)
            .where(DirectMessage.id == message_id)
            .options(selectinload(User.profile))
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])

    async def list_messages_for_conversation(
        self,
        conversation_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[DirectMessage, User]]:
        stmt = (
            select(DirectMessage, User)
            .join(User, User.id == DirectMessage.author_id)
            .where(DirectMessage.conversation_id == conversation_id)
            .options(selectinload(User.profile))
            .order_by(desc(DirectMessage.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def count_unread_for_participant(
        self,
        conversation_id: UUID,
        user_id: UUID,
        last_read_at: datetime | None,
    ) -> int:
        """How many messages in this conversation are newer than ``last_read_at``.

        Messages authored by the participant themselves don't count as
        unread (you've trivially read what you wrote).
        """
        stmt = select(func.count(DirectMessage.id)).where(
            DirectMessage.conversation_id == conversation_id,
            DirectMessage.author_id != user_id,
        )
        if last_read_at is not None:
            stmt = stmt.where(DirectMessage.created_at > last_read_at)
        result = await self._db.execute(stmt)
        return int(result.scalar_one() or 0)


__all__ = ["DMRepository"]
