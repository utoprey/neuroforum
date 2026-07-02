"""Mentions business logic: bulk recording + paginated read for the inbox."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mentions.models import Mention, MentionSourceType
from app.modules.mentions.repository import MentionRepository
from app.modules.users.models import User


class MentionService:
    """Records mentions for content-bearing rows and lists the user's inbox."""

    def __init__(self, repo: MentionRepository, db: AsyncSession) -> None:
        self._repo = repo
        self._db = db

    async def record_mentions(
        self,
        source_type: MentionSourceType,
        source_id: UUID,
        author_id: UUID,
        mentioned_user_ids: Iterable[UUID],
    ) -> list[Mention]:
        """Persist (source_type, source_id, mentioned_user_id) — deduplicated.

        Re-edits that re-mention the same user produce no new rows. Returns
        only the newly inserted rows so the caller can fan out notifications.
        """
        # Filter out self-mentions — no point notifying yourself.
        targets = {uid for uid in mentioned_user_ids if uid != author_id}
        if not targets:
            return []
        return await self._repo.bulk_create(
            source_type, source_id, author_id, targets
        )

    async def list_my_mentions(
        self,
        user: User,
        *,
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
    ) -> list[tuple[Mention, User, User]]:
        return await self._repo.list_for_user(
            user.id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
            unread_only=unread_only,
        )


__all__ = ["MentionService"]
