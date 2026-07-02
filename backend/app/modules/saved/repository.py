"""Data access for ``saved_articles``."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.articles.models import Article
from app.modules.saved.models import SavedArticle
from app.modules.users.models import User


class SavedRepository:
    """Thin DAL over ``saved_articles``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def add(self, user_id: UUID, article_id: UUID) -> bool:
        """Insert a save row. Returns True if the row was actually inserted.

        Uses ``INSERT … ON CONFLICT DO NOTHING`` so double-save is a no-op.
        """
        stmt = (
            insert(SavedArticle)
            .values(user_id=user_id, article_id=article_id)
            .on_conflict_do_nothing(index_elements=["user_id", "article_id"])
        )
        result = await self._db.execute(stmt)
        rc = _rowcount(result)
        return rc > 0

    async def remove(self, user_id: UUID, article_id: UUID) -> bool:
        """Delete the row if it exists. Returns True if the row existed."""
        stmt = delete(SavedArticle).where(
            SavedArticle.user_id == user_id,
            SavedArticle.article_id == article_id,
        )
        result = await self._db.execute(stmt)
        return _rowcount(result) > 0

    async def exists(self, user_id: UUID, article_id: UUID) -> bool:
        stmt = select(SavedArticle.user_id).where(
            SavedArticle.user_id == user_id,
            SavedArticle.article_id == article_id,
        )
        return (await self._db.execute(stmt)).scalar_one_or_none() is not None

    async def list_for_user(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> list[tuple[SavedArticle, Article, User]]:
        """Return ``(SavedArticle, Article, author)`` triples newest-first."""
        stmt = (
            select(SavedArticle, Article, User)
            .join(Article, Article.id == SavedArticle.article_id)
            .join(User, User.id == Article.author_id)
            .where(SavedArticle.user_id == user_id)
            .options(selectinload(User.profile))
            .order_by(desc(SavedArticle.saved_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]


def _rowcount(result: Any) -> int:
    """Read ``rowcount`` off a CursorResult without tripping mypy."""
    rc = getattr(result, "rowcount", 0)
    return int(rc) if rc is not None else 0


__all__ = ["SavedRepository"]
