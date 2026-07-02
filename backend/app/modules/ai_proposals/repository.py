"""Data access for the ``ai_proposals`` module."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.ai_proposals.models import (
    AIProposalStatus,
    ArticleAIProposal,
)
from app.modules.users.models import User


class AIProposalRepository:
    """DAL for ``article_ai_proposals``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, proposal: ArticleAIProposal) -> ArticleAIProposal:
        self._db.add(proposal)
        await self._db.flush()
        return proposal

    async def get(self, proposal_id: UUID) -> ArticleAIProposal | None:
        stmt = select(ArticleAIProposal).where(
            ArticleAIProposal.id == proposal_id
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_with_users(
        self, proposal_id: UUID
    ) -> tuple[ArticleAIProposal, User] | None:
        stmt = (
            select(ArticleAIProposal, User)
            .join(User, User.id == ArticleAIProposal.requested_by)
            .where(ArticleAIProposal.id == proposal_id)
            .options(selectinload(User.profile))
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])

    async def list_for_article(
        self,
        article_id: UUID,
        *,
        status_filter: AIProposalStatus | None = None,
    ) -> list[tuple[ArticleAIProposal, User]]:
        stmt = (
            select(ArticleAIProposal, User)
            .join(User, User.id == ArticleAIProposal.requested_by)
            .where(ArticleAIProposal.article_id == article_id)
            .options(selectinload(User.profile))
            .order_by(desc(ArticleAIProposal.created_at))
        )
        if status_filter is not None:
            stmt = stmt.where(ArticleAIProposal.status == status_filter)
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def expire_pending(self) -> int:
        """Mark every pending proposal past its TTL as ``expired``. Returns count."""
        now = datetime.now(UTC)
        stmt = (
            update(ArticleAIProposal)
            .where(
                ArticleAIProposal.status == AIProposalStatus.PENDING,
                ArticleAIProposal.expires_at < now,
            )
            .values(status=AIProposalStatus.EXPIRED)
            .returning(ArticleAIProposal.id)
        )
        result = await self._db.execute(stmt)
        ids = list(result.scalars().all())
        await self._db.flush()
        return len(ids)


__all__ = ["AIProposalRepository"]
