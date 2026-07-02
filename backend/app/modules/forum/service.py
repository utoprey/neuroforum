"""Forum business logic: section/topic CRUD with RBAC + slug allocation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forum.exceptions import (
    InsufficientRole,
    SectionNotFound,
    SlugConflict,
    TopicNotFound,
)
from app.modules.forum.models import Section, Topic, TopicKind
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import (
    SectionCreate,
    SectionUpdate,
    TopicCreate,
    TopicUpdate,
)
from app.modules.forum.utils import make_slug
from app.modules.users.models import Role, User

_ADMIN_ONLY: frozenset[Role] = frozenset({Role.ADMIN})
_MOD_OR_ADMIN: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})

# Max attempts at suffixing ``-2 .. -N`` when a slug collides.
_SLUG_COLLISION_RETRIES = 10


class ForumService:
    """Sections + topics CRUD. Permission checks happen here, not in routes."""

    def __init__(self, repo: ForumRepository, db: AsyncSession) -> None:
        self._repo = repo
        self._db = db

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------

    async def create_section(self, actor: User, payload: SectionCreate) -> Section:
        if actor.role not in _ADMIN_ONLY:
            raise InsufficientRole("Admin role required to create sections")

        slug = payload.slug or make_slug(payload.title)
        # Sections live in a single global namespace — collision is a hard error
        # (no -2/-3 retry: admins explicitly choose section slugs).
        if await self._repo.get_section_by_slug(slug) is not None:
            raise SlugConflict(f"Section slug already exists: {slug!r}")

        section = Section(
            slug=slug,
            title=payload.title,
            description=payload.description,
            position=payload.position,
            icon=payload.icon,
        )
        return await self._repo.create_section(section)

    async def update_section(
        self, actor: User, slug: str, payload: SectionUpdate
    ) -> Section:
        if actor.role not in _ADMIN_ONLY:
            raise InsufficientRole("Admin role required to update sections")

        section = await self._repo.get_section_by_slug(slug)
        if section is None:
            raise SectionNotFound(slug)

        data = payload.model_dump(exclude_unset=True)
        new_slug = data.get("slug")
        if new_slug is not None and new_slug != section.slug:
            if await self._repo.get_section_by_slug(new_slug) is not None:
                raise SlugConflict(f"Section slug already exists: {new_slug!r}")
            section.slug = new_slug
        for field in ("title", "description", "position", "icon"):
            if field in data:
                setattr(section, field, data[field])
        await self._db.flush()
        await self._db.refresh(section, attribute_names=("updated_at",))
        return section

    async def get_section_by_slug(self, slug: str) -> Section:
        section = await self._repo.get_section_by_slug(slug)
        if section is None:
            raise SectionNotFound(slug)
        return section

    async def list_sections(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[Section]:
        return await self._repo.list_sections(
            limit=max(1, min(limit, 200)), offset=max(0, offset)
        )

    # ------------------------------------------------------------------
    # Topics
    # ------------------------------------------------------------------

    async def create_topic(
        self, actor: User, section_slug: str, payload: TopicCreate
    ) -> tuple[Topic, User]:
        """Create a topic under ``section_slug``.

        Any authenticated user may create ``discussion`` / ``help`` /
        ``flood`` topics. Only moderators/admins may create ``news`` topics
        (long-form article containers).

        Returns ``(topic, author)`` so the route can build the ``TopicRead``
        response without re-querying the author.
        """
        if payload.kind == TopicKind.NEWS and actor.role not in _MOD_OR_ADMIN:
            raise InsufficientRole(
                "Only moderators or admins may create news topics"
            )

        section = await self._repo.get_section_by_slug(section_slug)
        if section is None:
            raise SectionNotFound(section_slug)

        base_slug = payload.slug or make_slug(payload.title, max_length=140)
        slug = await self._allocate_topic_slug(section.id, base_slug)

        topic = Topic(
            section_id=section.id,
            slug=slug,
            title=payload.title,
            description=payload.description,
            kind=payload.kind,
            created_by=actor.id,
        )
        await self._repo.create_topic(topic)
        return (topic, actor)

    async def _allocate_topic_slug(self, section_id: UUID, base: str) -> str:
        """Find a free slug ``base``, ``base-2``, ``base-3`` … up to 10 tries."""
        if await self._repo.get_topic_in_section_by_slug(section_id, base) is None:
            return base
        for i in range(2, 2 + _SLUG_COLLISION_RETRIES):
            candidate = f"{base}-{i}"
            if (
                await self._repo.get_topic_in_section_by_slug(section_id, candidate)
                is None
            ):
                return candidate
        raise SlugConflict(
            f"Could not allocate a free slug for base {base!r} after "
            f"{_SLUG_COLLISION_RETRIES} attempts"
        )

    async def update_topic(
        self, actor: User, topic_id: UUID, payload: TopicUpdate
    ) -> tuple[Topic, User]:
        if actor.role not in _MOD_OR_ADMIN:
            raise InsufficientRole("Moderator or admin role required to update topics")

        row = await self._repo.get_topic_with_author(topic_id)
        if row is None:
            raise TopicNotFound(str(topic_id))
        topic, author = row

        data = payload.model_dump(exclude_unset=True)
        for field in ("title", "description", "is_locked", "is_pinned", "kind"):
            if field in data:
                setattr(topic, field, data[field])
        await self._db.flush()
        # Re-read server-managed ``updated_at`` so callers can serialize the
        # response without triggering lazy I/O outside a greenlet.
        await self._db.refresh(topic, attribute_names=("updated_at",))
        return (topic, author)

    async def get_topic(self, topic_id: UUID) -> tuple[Topic, User]:
        row = await self._repo.get_topic_with_author(topic_id)
        if row is None:
            raise TopicNotFound(str(topic_id))
        return row

    async def get_topic_by_slug(
        self, section_slug: str, topic_slug: str
    ) -> tuple[Topic, User]:
        """Resolve a topic by ``(section_slug, topic_slug)``.

        Section is global, topic-slug is unique within section. Raises
        :class:`SectionNotFound` / :class:`TopicNotFound` so route handlers
        can distinguish between the two failure modes when needed.
        """
        section = await self._repo.get_section_by_slug(section_slug)
        if section is None:
            raise SectionNotFound(section_slug)
        row = await self._repo.get_topic_with_author_by_slug(
            section.id, topic_slug
        )
        if row is None:
            raise TopicNotFound(topic_slug)
        return row

    async def list_topics_for_section(
        self,
        section_slug: str,
        *,
        kind: TopicKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[Topic, User]]:
        section = await self._repo.get_section_by_slug(section_slug)
        if section is None:
            raise SectionNotFound(section_slug)
        return await self._repo.list_topics_for_section(
            section.id,
            kind=kind,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def lock_topic(
        self, actor: User, topic_id: UUID, locked: bool
    ) -> tuple[Topic, User]:
        if actor.role not in _MOD_OR_ADMIN:
            raise InsufficientRole("Moderator or admin role required to lock topics")
        row = await self._repo.get_topic_with_author(topic_id)
        if row is None:
            raise TopicNotFound(str(topic_id))
        topic, author = row
        topic.is_locked = locked
        await self._db.flush()
        await self._db.refresh(topic, attribute_names=("updated_at",))
        return (topic, author)


__all__ = ["ForumService"]
