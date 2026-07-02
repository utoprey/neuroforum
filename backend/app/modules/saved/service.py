"""Saved-articles business logic: idempotent save/unsave + stats bump."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import Article
from app.modules.saved.exceptions import ArticleNotFound
from app.modules.saved.models import SavedArticle
from app.modules.saved.repository import SavedRepository
from app.modules.users.models import User, UserStats


class SavedService:
    """Orchestrates the saved-articles repository + user_stats counter."""

    def __init__(self, repo: SavedRepository, db: AsyncSession) -> None:
        self._repo = repo
        self._db = db

    async def save(self, user: User, article_id: UUID) -> None:
        """Idempotent save; only bumps ``user_stats.saved_articles_count`` on new row."""
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))
        inserted = await self._repo.add(user.id, article_id)
        if inserted:
            await self._adjust_counter(user.id, +1)
        await self._db.flush()

    async def unsave(self, user: User, article_id: UUID) -> None:
        """Idempotent unsave; decrements stats only when row actually existed."""
        # Don't 404 if the article is gone — the user is still entitled to clean
        # up a stale bookmark referring to a since-deleted article.
        removed = await self._repo.remove(user.id, article_id)
        if removed:
            await self._adjust_counter(user.id, -1)
        await self._db.flush()

    async def list_my_saved(
        self, user: User, *, limit: int = 20, offset: int = 0
    ) -> list[tuple[SavedArticle, Article, User]]:
        return await self._repo.list_for_user(
            user.id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )

    async def _adjust_counter(self, user_id: UUID, delta: int) -> None:
        """Atomic bump of ``user_stats.saved_articles_count``."""
        await self._db.execute(
            update(UserStats)
            .where(UserStats.user_id == user_id)
            .values(saved_articles_count=UserStats.saved_articles_count + delta)
        )


__all__ = ["SavedService"]
