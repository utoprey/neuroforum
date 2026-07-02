"""Data access for ``mentions``."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.modules.mentions.models import Mention, MentionSourceType
from app.modules.users.models import User


class MentionRepository:
    """Thin DAL over ``mentions``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def bulk_create(
        self,
        source_type: MentionSourceType,
        source_id: UUID,
        author_id: UUID,
        mentioned_user_ids: Iterable[UUID],
    ) -> list[Mention]:
        """Insert one row per unique mentioned user, skipping duplicates.

        Returns only the rows that were actually newly inserted (so callers
        can fan out notifications without sending dupes for re-edits that
        re-mention the same person).
        """
        unique_ids = list({uid for uid in mentioned_user_ids})
        if not unique_ids:
            return []
        rows = [
            {
                "source_type": source_type,
                "source_id": source_id,
                "mentioned_user_id": uid,
                "author_id": author_id,
            }
            for uid in unique_ids
        ]
        stmt = (
            insert(Mention)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=[
                    "source_type",
                    "source_id",
                    "mentioned_user_id",
                ]
            )
            .returning(Mention)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        offset: int,
        unread_only: bool = False,
    ) -> list[tuple[Mention, User, User]]:
        """Return ``(Mention, mentioned_user, author)`` triples newest-first."""
        mentioned = aliased(User)
        author = aliased(User)
        stmt = (
            select(Mention, mentioned, author)
            .join(mentioned, mentioned.id == Mention.mentioned_user_id)
            .join(author, author.id == Mention.author_id)
            .where(Mention.mentioned_user_id == user_id)
            .options(
                selectinload(mentioned.profile),
                selectinload(author.profile),
            )
            .order_by(desc(Mention.created_at))
            .limit(limit)
            .offset(offset)
        )
        if unread_only:
            stmt = stmt.where(Mention.notified_at.is_(None))
        result = await self._db.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]


__all__ = ["MentionRepository"]
