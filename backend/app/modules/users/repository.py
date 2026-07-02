"""Data access for the ``users`` module — async SQLAlchemy."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.users.models import User, UserProfile, UserStats


class UserRepository:
    """Thin DAL over Users / UserProfile / UserStats.

    No business logic here — that lives in :class:`UserService`.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # --- Read ------------------------------------------------------------

    async def get(self, user_id: UUID) -> User | None:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.profile), selectinload(User.stats))
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = (
            select(User)
            .where(User.username == username)
            .options(selectinload(User.profile), selectinload(User.stats))
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        stmt = (
            select(User)
            # CITEXT handles case-insensitive equality automatically.
            .where(User.email == email)
            .options(selectinload(User.profile), selectinload(User.stats))
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_search_prefix(self, prefix: str, limit: int) -> list[User]:
        """``/users/search?q=@foo`` — prefix LIKE on username, B-tree friendly."""
        like = f"{prefix}%"
        stmt = (
            select(User)
            .where(User.username.ilike(like))
            .options(selectinload(User.profile))
            .order_by(User.username)
            .limit(limit)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def list_search_fuzzy(self, q: str, limit: int) -> list[User]:
        """``/users/search?q=foo`` — pg_trgm similarity over username + display_name.

        Falls back to ``ILIKE %q%`` (still indexed by ``gin_trgm_ops``)
        because ``similarity()`` requires the ``pg_trgm`` extension which
        the integration test container has (created in the first
        migration). We avoid raw SQL by going through ``func``.
        """
        sim_username = func.similarity(User.username, q)
        sim_display = func.similarity(
            func.coalesce(UserProfile.display_name, ""), q
        )
        score = func.greatest(sim_username, sim_display)
        stmt = (
            select(User, score.label("score"))
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
        return [row[0] for row in result.all()]

    # --- Write -----------------------------------------------------------

    async def create(
        self,
        user: User,
        profile: UserProfile,
        stats: UserStats,
    ) -> User:
        """Insert all three rows in the current transaction.

        Caller is responsible for committing (the service wraps this in a
        try/except around ``IntegrityError`` translation).
        """
        self._db.add(user)
        # Flush so ``user.id`` is materialized before the children pick it up.
        await self._db.flush()
        profile.user_id = user.id
        stats.user_id = user.id
        self._db.add(profile)
        self._db.add(stats)
        await self._db.flush()
        return user

    async def increment_stat(
        self,
        user_id: UUID,
        field: str,
        delta: int = 1,
    ) -> None:
        """Atomic increment of a ``user_stats`` integer field.

        Used by sibling modules (articles, messages, reactions) to keep the
        denormalised counters fresh without each having to re-implement the
        same UPDATE. ``field`` must be a real ``UserStats`` column name —
        we validate it via ``getattr`` so a typo fails loudly here rather
        than silently producing bad SQL.
        """
        column = getattr(UserStats, field)
        await self._db.execute(
            update(UserStats)
            .where(UserStats.user_id == user_id)
            .values({field: column + delta, "updated_at": func.now()})
        )

    async def update_profile(
        self,
        user_id: UUID,
        data: dict[str, Any],
    ) -> UserProfile | None:
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        result = await self._db.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile is None:
            return None
        for key, value in data.items():
            setattr(profile, key, value)
        await self._db.flush()
        return profile

    # --- Recent topics / messages (cross-module SQL) --------------------

    async def recent_topics(
        self, user_id: UUID, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Topics where ``user_id`` left ≥ 1 message, ordered by latest message.

        Cross-module SQL — imports stay inside the method to avoid the
        ``users -> messages/articles/forum`` import cycle at module load.
        """
        # Local imports avoid the cross-module circular import.
        from app.modules.articles.models import Article
        from app.modules.forum.models import Topic
        from app.modules.messages.models import Message

        last_msg_at = func.max(Message.created_at).label("last_message_at")
        stmt = (
            select(
                Topic.id.label("topic_id"),
                Topic.slug,
                Topic.title,
                last_msg_at,
            )
            .join(Article, Article.topic_id == Topic.id)
            .join(Message, Message.article_id == Article.id)
            .where(Message.author_id == user_id)
            .group_by(Topic.id, Topic.slug, Topic.title)
            .order_by(desc(last_msg_at))
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return [
            {
                "id": row.topic_id,
                "slug": row.slug,
                "title": row.title,
                "last_message_at": row.last_message_at,
            }
            for row in result.all()
        ]

    async def recent_messages(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Latest messages authored by ``user_id`` with topic + article context.

        ``offset`` was added for the ``/users/{username}/messages`` paginated
        endpoint; existing ``recent_messages`` callers pass only ``limit`` so
        the default keeps them working.
        """
        from app.modules.articles.models import Article
        from app.modules.forum.models import Topic
        from app.modules.messages.models import Message

        stmt = (
            select(
                Message.id,
                Message.article_id,
                Message.content_text,
                Message.created_at,
                Article.title.label("article_title"),
                Article.slug.label("article_slug"),
                Topic.id.label("topic_id"),
                Topic.slug.label("topic_slug"),
            )
            .join(Article, Article.id == Message.article_id)
            .join(Topic, Topic.id == Article.topic_id)
            .where(Message.author_id == user_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._db.execute(stmt)).all()
        return [
            {
                "id": row.id,
                "article_id": row.article_id,
                "article_title": row.article_title,
                "article_slug": row.article_slug,
                "topic_id": row.topic_id,
                "topic_slug": row.topic_slug,
                "snippet": (row.content_text or "")[:200],
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def user_articles(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[Any]:
        """Published articles authored by ``user_id``, newest first.

        ORDER BY ``published_at DESC NULLS LAST`` — newly-published articles
        bubble to the top; ``NULLS LAST`` is defensive against rows where
        the column hasn't been populated yet (shouldn't happen for
        ``status=PUBLISHED`` but we don't want a stray NULL to leapfrog
        legitimate rows).
        """
        # Local imports keep the cross-module dependency at call-time, not
        # at ``users`` package import — same pattern as ``recent_messages``.
        from app.modules.articles.models import Article, ArticleStatus

        stmt = (
            select(Article)
            .where(
                Article.author_id == user_id,
                Article.status == ArticleStatus.PUBLISHED,
            )
            .order_by(Article.published_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._db.scalars(stmt)).all())

    async def user_reactions(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Reactions left by ``user_id`` across articles + messages.

        Implemented as a raw ``UNION ALL`` because the two source tables
        (``article_reactions`` / ``message_reactions``) have different
        target columns — expressing it via SQLAlchemy ORM would require
        two parallel selects + a Python merge, which loses the
        single-LIMIT-OFFSET optimisation against an index.
        """
        sql = text(
            """
            SELECT * FROM (
              SELECT
                'article'::text AS target_type,
                ar.article_id AS target_id,
                ar.kind AS kind,
                ar.created_at AS reacted_at,
                a.id AS article_id,
                a.slug AS article_slug,
                a.title AS article_title,
                LEFT(COALESCE(a.content_text, ''), 200) AS snippet
              FROM article_reactions ar
              JOIN articles a ON a.id = ar.article_id
              WHERE ar.user_id = :uid
              UNION ALL
              SELECT
                'message'::text AS target_type,
                mr.message_id AS target_id,
                mr.kind AS kind,
                mr.created_at AS reacted_at,
                a.id AS article_id,
                a.slug AS article_slug,
                a.title AS article_title,
                LEFT(COALESCE(m.content_text, ''), 200) AS snippet
              FROM message_reactions mr
              JOIN messages m ON m.id = mr.message_id
              JOIN articles a ON a.id = m.article_id
              WHERE mr.user_id = :uid
            ) AS combined
            ORDER BY reacted_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        rows = (
            await self._db.execute(
                sql, {"uid": user_id, "limit": limit, "offset": offset}
            )
        ).all()
        return [dict(row._mapping) for row in rows]


__all__ = ["UserRepository"]
