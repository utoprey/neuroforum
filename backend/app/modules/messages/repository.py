"""Data access for ``messages`` / ``message_revisions``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import asc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.messages.models import Message, MessageRevision
from app.modules.users.models import User


class MessageRepository:
    """Thin DAL over ``messages`` + ``message_revisions``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ----- Messages -------------------------------------------------------

    async def get(self, message_id: UUID) -> Message | None:
        stmt = select(Message).where(Message.id == message_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_with_author(
        self, message_id: UUID
    ) -> tuple[Message, User] | None:
        stmt = (
            select(Message, User)
            .join(User, User.id == Message.author_id)
            .where(Message.id == message_id)
            .options(selectinload(User.profile))
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])

    async def add(self, message: Message) -> Message:
        self._db.add(message)
        await self._db.flush()
        return message

    async def list_top_level_for_article(
        self,
        article_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[Message, User]]:
        stmt = (
            select(Message, User)
            .join(User, User.id == Message.author_id)
            .where(
                Message.article_id == article_id,
                Message.parent_id.is_(None),
            )
            .options(selectinload(User.profile))
            .order_by(asc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def list_direct_children(
        self, parent_ids: list[UUID]
    ) -> list[tuple[Message, User]]:
        """Fetch all immediate children for the given parent ids in one query."""
        if not parent_ids:
            return []
        stmt = (
            select(Message, User)
            .join(User, User.id == Message.author_id)
            .where(Message.parent_id.in_(parent_ids))
            .options(selectinload(User.profile))
            .order_by(asc(Message.created_at))
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def list_descendants_by_path(
        self, root_path: str
    ) -> list[tuple[Message, User]]:
        """Return every descendant under ``root_path`` via LTREE ``<@`` operator.

        Includes the root itself. Ordered lexicographically by ``path`` so the
        UI can render the subtree in a single pass.
        """
        stmt = (
            select(Message, User)
            .join(User, User.id == Message.author_id)
            .where(text("messages.path <@ CAST(:root_path AS ltree)"))
            .options(selectinload(User.profile))
            .order_by(text("messages.path ASC"))
            .params(root_path=root_path)
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    # ----- Revisions ------------------------------------------------------

    async def max_revision_for_message(self, message_id: UUID) -> int:
        stmt = select(
            func.coalesce(func.max(MessageRevision.revision), 0)
        ).where(MessageRevision.message_id == message_id)
        result = await self._db.execute(stmt)
        return int(result.scalar_one())

    async def add_revision(self, revision: MessageRevision) -> MessageRevision:
        self._db.add(revision)
        await self._db.flush()
        return revision


__all__ = ["MessageRepository"]
