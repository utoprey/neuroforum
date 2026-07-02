"""Postgres-backed implementation of :class:`SearchEngine`.

Uses Postgres FTS (``ts_rank_cd``, ``plainto_tsquery``, ``ts_headline``) over
the ``content_tsv`` columns the ``articles`` / ``messages`` modules expose,
and ``pg_trgm`` similarity over ``users.username`` + ``user_profiles.display_name``.

The ``content_tsv`` columns are ``GENERATED ALWAYS AS … STORED`` in
production migrations but plain TSVECTOR with empty default in tests (see
``articles/models.py`` module docstring). Test suites for article/message
search are marked ``xfail`` because of this — see ``search/tests``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Select, select

from app.modules.articles.models import Article, ArticleStatus
from app.modules.articles.schemas import ArticlePublic
from app.modules.messages.models import Message, MessageStatus
from app.modules.search.schemas import ArticleSearchHit, MessageSearchHit
from app.modules.users.models import User, UserProfile
from app.modules.users.schemas import UserPublic

_RUSSIAN = "russian"
_HEADLINE_OPTS = "MaxFragments=2,MinWords=5,MaxWords=15"


def _author_public(author: User) -> UserPublic:
    return UserPublic(
        id=author.id,
        username=author.username,
        display_name=(author.profile.display_name if author.profile else None),
        avatar_url=(author.profile.avatar_url if author.profile else None),
        role=author.role,
    )


def _article_public(article: Article, author: User) -> ArticlePublic:
    return ArticlePublic(
        id=article.id,
        slug=article.slug,
        topic_id=article.topic_id,
        title=article.title,
        summary=article.summary,
        author=_author_public(author),
        status=article.status,
        published_at=article.published_at,
        view_count=article.view_count,
        comment_count=article.comment_count,
        reaction_counts=dict(article.reaction_counts or {}),
    )


class PostgresSearchEngine:
    """``SearchEngine`` implementation that goes directly to Postgres FTS / pg_trgm."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Articles — content_tsv FTS
    # ------------------------------------------------------------------

    async def search_articles(
        self, q: str, limit: int
    ) -> list[ArticleSearchHit]:
        q = (q or "").strip()
        if not q:
            return []
        limit = max(1, min(limit, 50))
        # ``content_tsv`` is deferred on the ORM (production: GENERATED
        # column; tests: empty TSVECTOR). We bypass the ORM-level default
        # selectable and instead select Article + computed rank/snippet
        # directly so the ``Article`` returned from selectinload still works.
        tsq = func.plainto_tsquery(_RUSSIAN, q)
        rank = func.ts_rank_cd(text("articles.content_tsv"), tsq).label("rank")
        snippet = func.ts_headline(
            _RUSSIAN,
            Article.content_text,
            tsq,
            _HEADLINE_OPTS,
        ).label("snippet")
        stmt: Select[tuple[Article, User, float, str]] = (
            select(Article, User, rank, snippet)
            .join(User, User.id == Article.author_id)
            .where(
                text("articles.content_tsv @@ plainto_tsquery(:lang, :q)"),
                Article.status == ArticleStatus.PUBLISHED,
            )
            .options(selectinload(User.profile))
            .order_by(desc("rank"))
            .limit(limit)
            .params(lang=_RUSSIAN, q=q)
        )
        result = await self._db.execute(stmt)
        return [
            ArticleSearchHit(
                article=_article_public(row[0], row[1]),
                rank=float(row[2] or 0.0),
                snippet=str(row[3] or ""),
            )
            for row in result.all()
        ]

    # ------------------------------------------------------------------
    # Messages — content_tsv FTS
    # ------------------------------------------------------------------

    async def search_messages(
        self, q: str, limit: int
    ) -> list[MessageSearchHit]:
        q = (q or "").strip()
        if not q:
            return []
        limit = max(1, min(limit, 50))
        tsq = func.plainto_tsquery(_RUSSIAN, q)
        rank = func.ts_rank_cd(text("messages.content_tsv"), tsq).label("rank")
        snippet = func.ts_headline(
            _RUSSIAN,
            Message.content_text,
            tsq,
            _HEADLINE_OPTS,
        ).label("snippet")
        stmt: Select[tuple[UUID, UUID, float, str]] = (
            select(
                Message.id,
                Message.article_id,
                rank,
                snippet,
            )
            .where(
                text("messages.content_tsv @@ plainto_tsquery(:lang, :q)"),
                Message.status == MessageStatus.VISIBLE,
            )
            .order_by(desc("rank"))
            .limit(limit)
            .params(lang=_RUSSIAN, q=q)
        )
        result = await self._db.execute(stmt)
        return [
            MessageSearchHit(
                message_id=row[0],
                article_id=row[1],
                rank=float(row[2] or 0.0),
                snippet=str(row[3] or ""),
            )
            for row in result.all()
        ]

    # ------------------------------------------------------------------
    # Users — pg_trgm over username + display_name
    # ------------------------------------------------------------------

    async def search_users(
        self, q: str, limit: int
    ) -> list[UserPublic]:
        q = (q or "").strip()
        if not q:
            return []
        limit = max(1, min(limit, 50))
        sim_username = func.similarity(User.username, q)
        sim_display = func.similarity(
            func.coalesce(UserProfile.display_name, ""), q
        )
        score = func.greatest(sim_username, sim_display).label("score")
        stmt = (
            select(User, score)
            .join(UserProfile, UserProfile.user_id == User.id, isouter=True)
            .where(
                or_(
                    User.username.ilike(f"%{q}%"),
                    UserProfile.display_name.ilike(f"%{q}%"),
                )
            )
            .options(selectinload(User.profile))
            .order_by(desc("score"), User.username)
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [_author_public(row[0]) for row in result.all()]


__all__ = ["PostgresSearchEngine"]
