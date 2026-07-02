"""Data access for ``articles`` / ``article_revisions``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.articles.models import Article, ArticleRevision, ArticleStatus
from app.modules.users.models import User


class ArticleRepository:
    """Reads + writes for ``articles`` + ``article_revisions``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ----- Articles -------------------------------------------------------

    async def get(self, article_id: UUID) -> Article | None:
        stmt = select(Article).where(Article.id == article_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_with_author(
        self, article_id: UUID
    ) -> tuple[Article, User] | None:
        stmt = (
            select(Article, User)
            .join(User, User.id == Article.author_id)
            .where(Article.id == article_id)
            .options(selectinload(User.profile))
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])

    async def get_by_topic_and_slug(
        self, topic_id: UUID, slug: str
    ) -> Article | None:
        stmt = select(Article).where(
            Article.topic_id == topic_id, Article.slug == slug
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def add(self, article: Article) -> Article:
        self._db.add(article)
        await self._db.flush()
        return article

    async def delete(self, article_id: UUID) -> None:
        """Hard delete article (cascade on messages, reactions, saved_articles, revisions)."""
        await self._db.execute(delete(Article).where(Article.id == article_id))
        await self._db.flush()

    async def list_for_topic(
        self,
        topic_id: UUID,
        *,
        status: ArticleStatus | None,
        limit: int,
        offset: int,
    ) -> list[tuple[Article, User]]:
        stmt = (
            select(Article, User)
            .join(User, User.id == Article.author_id)
            .where(Article.topic_id == topic_id)
            .options(selectinload(User.profile))
            .order_by(desc(Article.published_at), desc(Article.created_at))
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(Article.status == status)
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def list_drafts_for_user(
        self, user_id: UUID, *, limit: int, offset: int
    ) -> list[tuple[Article, User]]:
        stmt = (
            select(Article, User)
            .join(User, User.id == Article.author_id)
            .where(
                Article.author_id == user_id,
                Article.status == ArticleStatus.DRAFT,
            )
            .options(selectinload(User.profile))
            .order_by(desc(Article.updated_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    # ----- Revisions ------------------------------------------------------

    async def max_revision_for_article(self, article_id: UUID) -> int:
        stmt = select(func.coalesce(func.max(ArticleRevision.revision), 0)).where(
            ArticleRevision.article_id == article_id
        )
        result = await self._db.execute(stmt)
        return int(result.scalar_one())

    async def add_revision(self, revision: ArticleRevision) -> ArticleRevision:
        self._db.add(revision)
        await self._db.flush()
        return revision

    async def list_revisions(
        self, article_id: UUID
    ) -> list[tuple[ArticleRevision, User]]:
        stmt = (
            select(ArticleRevision, User)
            .join(User, User.id == ArticleRevision.editor_id)
            .where(ArticleRevision.article_id == article_id)
            .options(selectinload(User.profile))
            .order_by(desc(ArticleRevision.revision))
        )
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def get_revision(
        self, article_id: UUID, revision: int
    ) -> tuple[ArticleRevision, User] | None:
        stmt = (
            select(ArticleRevision, User)
            .join(User, User.id == ArticleRevision.editor_id)
            .where(
                ArticleRevision.article_id == article_id,
                ArticleRevision.revision == revision,
            )
            .options(selectinload(User.profile))
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])


__all__ = ["ArticleRepository"]
