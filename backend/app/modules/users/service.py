"""Business logic for user accounts: registration, search, profile updates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.users.exceptions import (
    EmailTaken,
    UsernameTaken,
    UserNotFound,
)
from app.modules.users.models import Role, User, UserProfile, UserStats
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    ProfileUpdate,
    RecentMessage,
    RecentTopic,
    UserCreate,
    UserPublic,
    UserReactionItem,
    UserRead,
)

# Window after which a user is considered offline.
ONLINE_WINDOW = timedelta(minutes=5)


def is_user_online(user: User) -> bool:
    """Return whether ``user.last_seen_at`` is within the online window."""
    if user.last_seen_at is None:
        return False
    last_seen = user.last_seen_at
    # Defensive: treat naive datetimes as UTC.
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last_seen) <= ONLINE_WINDOW


def to_user_public(user: User) -> UserPublic:
    """Build a :class:`UserPublic` enriched with ``is_online``.

    Pydantic's ``from_attributes`` mode can't compute derived fields from
    related attributes, so we materialise the DTO explicitly.
    """
    return UserPublic(
        id=user.id,
        username=user.username,
        display_name=(user.profile.display_name if user.profile else None),
        avatar_url=(user.profile.avatar_url if user.profile else None),
        role=user.role,
        is_online=is_user_online(user),
        last_seen_at=user.last_seen_at,
    )


def to_user_read(user: User) -> UserRead:
    """Build a :class:`UserRead` (self-view) enriched with ``is_online``."""
    payload = UserRead.model_validate(user)
    # ``UserRead`` is built via ``from_attributes`` so ``is_online`` defaults
    # to ``False`` — override with the computed value.
    payload.is_online = is_user_online(user)
    return payload


class UserService:
    """Orchestrates the repository + security primitives.

    Roles, permission checks, and integrity-error translation live here —
    routes stay thin (parse → call service → respond).
    """

    def __init__(self, repo: UserRepository, db: AsyncSession) -> None:
        self._repo = repo
        self._db = db

    # --- Read shortcuts ---------------------------------------------------

    async def get_by_username(self, username: str) -> User:
        user = await self._repo.get_by_username(username)
        if user is None:
            raise UserNotFound(username)
        return user

    async def get_by_id(self, user_id: UUID) -> User:
        user = await self._repo.get(user_id)
        if user is None:
            raise UserNotFound(str(user_id))
        return user

    # --- Registration -----------------------------------------------------

    async def create_user(self, payload: UserCreate, *, role: Role = Role.USER) -> User:
        """Create a user + empty profile + zeroed stats atomically.

        IntegrityError disambiguation: we re-fetch by username/email to find
        out which constraint tripped, rather than relying on driver error
        strings (which differ between asyncpg/psycopg).
        """
        user = User(
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password.get_secret_value()),
            role=role,
            is_active=True,
        )
        profile = UserProfile()
        stats = UserStats()

        # Pre-flight duplicate checks. Avoids the post-IntegrityError dance
        # of trying to recover the session: once a failed INSERT poisons the
        # transaction we can't run the probe queries from inside the same
        # session anyway. The window between check + insert is fine — the
        # UNIQUE constraint is still the source of truth (raised as 500 in
        # the unlikely race).
        if await self._repo.get_by_username(payload.username) is not None:
            raise UsernameTaken(payload.username)
        if await self._repo.get_by_email(payload.email) is not None:
            raise EmailTaken(payload.email)

        try:
            await self._repo.create(user, profile, stats)
        except IntegrityError as exc:
            # Race only — translate generically.
            raise UsernameTaken(payload.username) from exc

        # Re-fetch so ``profile`` / ``stats`` relationships are populated
        # (selectin-loaded) rather than triggering lazy I/O at serialization.
        return await self.get_by_id(user.id)

    # --- Profile ----------------------------------------------------------

    async def update_profile(
        self, user_id: UUID, patch: ProfileUpdate
    ) -> UserProfile:
        data: dict[str, Any] = patch.model_dump(exclude_unset=True)
        updated = await self._repo.update_profile(user_id, data)
        if updated is None:
            raise UserNotFound(str(user_id))
        return updated

    # --- Search -----------------------------------------------------------

    async def search_users(self, q: str, limit: int = 10) -> list[User]:
        """Frontends the ``@prefix`` vs fuzzy split documented in data-model.md."""
        q = q.strip()
        if not q:
            return []
        limit = max(1, min(limit, 50))
        if q.startswith("@"):
            stripped = q[1:]
            if not stripped:
                return []
            return await self._repo.list_search_prefix(stripped, limit)
        return await self._repo.list_search_fuzzy(q, limit)

    # --- Recent activity (cross-module) -----------------------------------

    async def recent_topics(self, user_id: UUID, limit: int = 10) -> list[RecentTopic]:
        # Existence check so we 404 properly when the user is missing.
        await self.get_by_id(user_id)
        rows = await self._repo.recent_topics(
            user_id, limit=max(1, min(limit, 50))
        )
        return [RecentTopic.model_validate(row) for row in rows]

    async def recent_messages(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[RecentMessage]:
        await self.get_by_id(user_id)
        rows = await self._repo.recent_messages(
            user_id,
            limit=max(1, min(limit, 50)),
            offset=max(0, offset),
        )
        return [RecentMessage.model_validate(row) for row in rows]

    # --- User activity lists (cross-module) -------------------------------

    async def user_articles(
        self, username: str, limit: int = 20, offset: int = 0
    ) -> list[Any]:
        """Published articles by ``username``, newest first.

        Returns ``(Article, User)`` tuples so the route layer can hand them
        to the existing ``ArticlePublic`` builder. We resolve the author
        once (it's always ``user``) rather than re-joining at the DB level.
        """
        user = await self.get_by_username(username)
        rows = await self._repo.user_articles(
            user.id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )
        return [(article, user) for article in rows]

    async def user_reactions(
        self, username: str, limit: int = 20, offset: int = 0
    ) -> list[UserReactionItem]:
        user = await self.get_by_username(username)
        rows = await self._repo.user_reactions(
            user.id,
            limit=max(1, min(limit, 100)),
            offset=max(0, offset),
        )
        return [UserReactionItem.model_validate(row) for row in rows]


__all__ = ["UserService"]
