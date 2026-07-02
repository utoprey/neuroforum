"""Data access for ``sections`` / ``topics``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.forum.models import Section, Topic, TopicKind
from app.modules.users.models import User


class ForumRepository:
    """Thin DAL — no business logic."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ----- Sections -------------------------------------------------------

    async def get_section(self, section_id: UUID) -> Section | None:
        stmt = select(Section).where(Section.id == section_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_section_by_slug(self, slug: str) -> Section | None:
        stmt = select(Section).where(Section.slug == slug)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_sections(self, *, limit: int, offset: int) -> list[Section]:
        stmt = (
            select(Section)
            .order_by(Section.position.asc(), Section.title.asc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def create_section(self, section: Section) -> Section:
        self._db.add(section)
        await self._db.flush()
        return section

    # ----- Topics ---------------------------------------------------------

    async def get_topic(self, topic_id: UUID) -> Topic | None:
        stmt = (
            select(Topic)
            .where(Topic.id == topic_id)
            .options(selectinload(Topic.section))
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_topic_with_author(
        self, topic_id: UUID
    ) -> tuple[Topic, User] | None:
        stmt = (
            select(Topic, User)
            .join(User, User.id == Topic.created_by)
            .where(Topic.id == topic_id)
            .options(
                selectinload(User.profile),
                selectinload(Topic.section),
            )
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])

    async def get_topic_in_section_by_slug(
        self, section_id: UUID, slug: str
    ) -> Topic | None:
        stmt = select(Topic).where(
            Topic.section_id == section_id, Topic.slug == slug
        )
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_topic_with_author_by_slug(
        self, section_id: UUID, slug: str
    ) -> tuple[Topic, User] | None:
        """Resolve ``(topic, author)`` by ``(section_id, slug)`` pair.

        Mirrors :meth:`get_topic_with_author` for the slug-based URL routes
        — eager-loads the author profile so the response can be serialized
        without lazy I/O outside a greenlet.
        """
        stmt = (
            select(Topic, User)
            .join(User, User.id == Topic.created_by)
            .where(Topic.section_id == section_id, Topic.slug == slug)
            .options(
                selectinload(User.profile),
                selectinload(Topic.section),
            )
        )
        row = (await self._db.execute(stmt)).first()
        if row is None:
            return None
        return (row[0], row[1])

    async def list_topics_for_section(
        self,
        section_id: UUID,
        *,
        kind: TopicKind | None = None,
        limit: int,
        offset: int,
    ) -> list[tuple[Topic, User]]:
        stmt = (
            select(Topic, User)
            .join(User, User.id == Topic.created_by)
            .where(Topic.section_id == section_id)
            # Pinned topics first, then newest at the top.
            .order_by(Topic.is_pinned.desc(), desc(Topic.created_at))
            .options(
                selectinload(User.profile),
                selectinload(Topic.section),
            )
            .limit(limit)
            .offset(offset)
        )
        if kind is not None:
            stmt = stmt.where(Topic.kind == kind)
        result = await self._db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def create_topic(self, topic: Topic) -> Topic:
        self._db.add(topic)
        await self._db.flush()
        return topic


__all__ = ["ForumRepository"]
