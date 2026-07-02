"""Reaction business logic: idempotent insert/delete + denormalised counters.

We keep two sources of truth in sync:

1. The row-per-reaction tables (``article_reactions``, ``message_reactions``)
   — authoritative for "did user X react with kind K?" queries.
2. The denormalised ``reaction_counts JSONB`` map on the parent row
   (``articles.reaction_counts``, ``messages.reaction_counts``) — keeps
   listing feeds O(1) and removes the need for ``GROUP BY`` at read time.

The ``jsonb_set`` update is applied only when the membership table actually
changed (``rowcount`` from the underlying insert/delete) — so double-react
becomes a no-op end-to-end and the count never overshoots.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import Article
from app.modules.messages.models import Message
from app.modules.reactions.exceptions import ArticleNotFound, MessageNotFound
from app.modules.reactions.models import (
    ArticleReaction,
    MessageReaction,
    ReactionKind,
)
from app.modules.reactions.schemas import ReactionSummary
from app.modules.users.models import User


class ReactionService:
    """Idempotent react/unreact + JSONB-counter maintenance."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Article reactions
    # ------------------------------------------------------------------

    async def react_to_article(
        self, user: User, article_id: UUID, kind: ReactionKind
    ) -> None:
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))

        stmt = (
            insert(ArticleReaction)
            .values(user_id=user.id, article_id=article_id, kind=kind)
            .on_conflict_do_nothing(
                index_elements=["user_id", "article_id", "kind"]
            )
        )
        result = await self._db.execute(stmt)
        # Only bump the counter if a new row was actually inserted —
        # double-react is then a true no-op.
        if _rowcount(result) > 0:
            self._adjust_counter(article, kind, +1)
            await self._bump_received_reactions(article.author_id, +1)
            await self._db.flush()

    async def unreact_article(
        self, user: User, article_id: UUID, kind: ReactionKind
    ) -> None:
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))

        stmt = delete(ArticleReaction).where(
            ArticleReaction.user_id == user.id,
            ArticleReaction.article_id == article_id,
            ArticleReaction.kind == kind,
        )
        result = await self._db.execute(stmt)
        if _rowcount(result) > 0:
            self._adjust_counter(article, kind, -1)
            await self._bump_received_reactions(article.author_id, -1)
            await self._db.flush()

    async def get_article_reactions(
        self, article_id: UUID
    ) -> list[ReactionSummary]:
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))
        return _summary_from_counts(article.reaction_counts)

    async def list_user_reactions_for_article(
        self, user: User, article_id: UUID
    ) -> list[ReactionKind]:
        stmt = select(ArticleReaction.kind).where(
            ArticleReaction.user_id == user.id,
            ArticleReaction.article_id == article_id,
        )
        result = await self._db.execute(stmt)
        return [row[0] for row in result.all()]

    # ------------------------------------------------------------------
    # Message reactions
    # ------------------------------------------------------------------

    async def react_to_message(
        self, user: User, message_id: UUID, kind: ReactionKind
    ) -> None:
        message = await self._db.get(Message, message_id)
        if message is None:
            raise MessageNotFound(str(message_id))

        stmt = (
            insert(MessageReaction)
            .values(user_id=user.id, message_id=message_id, kind=kind)
            .on_conflict_do_nothing(
                index_elements=["user_id", "message_id", "kind"]
            )
        )
        result = await self._db.execute(stmt)
        if _rowcount(result) > 0:
            self._adjust_counter(message, kind, +1)
            await self._bump_received_reactions(message.author_id, +1)
            await self._db.flush()

    async def unreact_message(
        self, user: User, message_id: UUID, kind: ReactionKind
    ) -> None:
        message = await self._db.get(Message, message_id)
        if message is None:
            raise MessageNotFound(str(message_id))

        stmt = delete(MessageReaction).where(
            MessageReaction.user_id == user.id,
            MessageReaction.message_id == message_id,
            MessageReaction.kind == kind,
        )
        result = await self._db.execute(stmt)
        if _rowcount(result) > 0:
            self._adjust_counter(message, kind, -1)
            await self._bump_received_reactions(message.author_id, -1)
            await self._db.flush()

    async def get_message_reactions(
        self, message_id: UUID
    ) -> list[ReactionSummary]:
        message = await self._db.get(Message, message_id)
        if message is None:
            raise MessageNotFound(str(message_id))
        return _summary_from_counts(message.reaction_counts)

    async def list_user_reactions_for_message(
        self, user: User, message_id: UUID
    ) -> list[ReactionKind]:
        stmt = select(MessageReaction.kind).where(
            MessageReaction.user_id == user.id,
            MessageReaction.message_id == message_id,
        )
        result = await self._db.execute(stmt)
        return [row[0] for row in result.all()]

    # ------------------------------------------------------------------
    # Internal: maintain the denormalised JSONB counter
    # ------------------------------------------------------------------

    async def _bump_received_reactions(self, user_id: UUID, delta: int) -> None:
        """Atomic bump of ``user_stats.received_reactions_count``.

        Self-reactions count too — the data-model doesn't carve out a
        special case and special-casing it here would create drift between
        the membership tables and the denormalised total.
        """
        from app.modules.users.repository import UserRepository

        await UserRepository(self._db).increment_stat(
            user_id, "received_reactions_count", delta
        )

    @staticmethod
    def _adjust_counter(
        parent: Article | Message, kind: ReactionKind, delta: int
    ) -> None:
        """In-place mutation of the parent's ``reaction_counts`` dict.

        We keep this on the loaded ORM object (rather than ``jsonb_set``
        raw SQL) so the value is always available without re-querying —
        and because SQLAlchemy's dirty-tracking picks up dict reassignment
        via the change-flag idiom.
        """
        counts: dict[str, Any] = dict(parent.reaction_counts or {})
        new_value = int(counts.get(kind.value, 0)) + delta
        if new_value <= 0:
            counts.pop(kind.value, None)
        else:
            counts[kind.value] = new_value
        # Reassign so SQLAlchemy detects the change (JSONB is treated as
        # an immutable scalar by the default mutation tracker).
        parent.reaction_counts = counts


def _rowcount(result: Any) -> int:
    """Read ``rowcount`` off a CursorResult without tripping mypy.

    ``AsyncSession.execute`` is typed as returning a ``Result[Any]`` which
    doesn't expose ``rowcount`` — but for DML statements the runtime object
    is always a :class:`sqlalchemy.engine.CursorResult` that does. Falls
    back to ``0`` if the attribute is missing or ``None``.
    """
    rc = getattr(result, "rowcount", 0)
    return int(rc) if rc is not None else 0


def _summary_from_counts(
    counts: dict[str, int] | None,
) -> list[ReactionSummary]:
    """Materialise the denormalised count map as a sorted list."""
    if not counts:
        return []
    summaries: list[ReactionSummary] = []
    for raw_kind, count in counts.items():
        try:
            kind = ReactionKind(raw_kind)
        except ValueError:
            # Unknown enum value in the JSONB — ignore so a future enum
            # change doesn't break old rows.
            continue
        summaries.append(ReactionSummary(kind=kind, count=int(count)))
    summaries.sort(key=lambda s: s.kind.value)
    return summaries


__all__ = ["ReactionService"]
