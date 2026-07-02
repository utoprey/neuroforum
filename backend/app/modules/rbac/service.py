"""Permission helpers + ban orchestration."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.exceptions import (
    AlreadyBanned,
    BanNotFound,
    CannotBanAdmin,
    InsufficientRole,
)
from app.modules.rbac.models import BanScope, UserBan
from app.modules.rbac.repository import RbacRepository
from app.modules.rbac.schemas import BanCreate
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository

_MOD_ROLES: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})


class RbacService:
    """RBAC + ban issuance.

    Notes:
    - Moderators may not ban admins or moderators; admins may not ban admins.
    - Idempotency: trying to issue a second ban with the same (user_id,
      scope, section_id, topic_id) tuple while a previous one is still
      active raises :class:`AlreadyBanned`.
    - ``is_banned`` is read-fast — used on every authed request.
    """

    def __init__(
        self,
        repo: RbacRepository,
        users: UserRepository,
        db: AsyncSession,
    ) -> None:
        self._repo = repo
        self._users = users
        self._db = db

    # ------------------------------------------------------------------
    # Ban / lift
    # ------------------------------------------------------------------

    async def ban_user(self, actor: User, payload: BanCreate) -> UserBan:
        if actor.role not in _MOD_ROLES:
            raise InsufficientRole("Moderator or admin role required")

        target = await self._users.get(payload.user_id)
        if target is None:
            raise BanNotFound(f"target {payload.user_id} not found")

        # Moderators can't ban moderators or admins. Admins can ban
        # everyone except other admins (preserves root-of-trust).
        if actor.role is Role.MODERATOR and target.role in _MOD_ROLES:
            raise CannotBanAdmin(
                "Moderators cannot ban moderators or admins"
            )
        if target.role is Role.ADMIN:
            raise CannotBanAdmin("Admins cannot be banned")

        # Idempotency: refuse if an identical active ban already exists.
        existing = await self._repo.list_active_bans(
            target.id,
            scope=payload.scope,
            section_id=payload.section_id,
            topic_id=payload.topic_id,
        )
        if existing:
            raise AlreadyBanned(str(existing[0].id))

        ban = UserBan(
            user_id=target.id,
            banned_by=actor.id,
            reason=payload.reason,
            scope=payload.scope,
            section_id=payload.section_id,
            topic_id=payload.topic_id,
            expires_at=payload.expires_at,
        )
        return await self._repo.create_ban(ban)

    async def lift_ban(self, actor: User, ban_id: UUID, reason: str) -> UserBan:
        if actor.role not in _MOD_ROLES:
            raise InsufficientRole("Moderator or admin role required")
        ban = await self._repo.get(ban_id)
        if ban is None:
            raise BanNotFound(str(ban_id))
        if ban.lifted_at is not None:
            # Idempotent — return as-is.
            return ban
        return await self._repo.lift_ban(ban, lifted_by=actor.id, reason=reason)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_my_active_bans(self, user_id: UUID) -> list[UserBan]:
        return await self._repo.list_active_bans(user_id)

    async def is_banned(
        self,
        user_id: UUID,
        *,
        scope: BanScope,
        section_id: UUID | None = None,
        topic_id: UUID | None = None,
    ) -> bool:
        """Return True if the user is banned at the requested scope.

        - ``scope='global'`` checks only for an active global ban.
        - ``scope='section'`` returns True for either an active global ban
          OR an active section ban with the matching ``section_id``.
        - ``scope='topic'`` returns True for an active global ban OR an
          active topic ban for ``topic_id``.

          NOTE: cascading "section ban covers all of its topics" is
          deferred until the ``forum`` module lands (we'd need to look up
          ``topic.section_id`` here, which isn't queryable yet). The
          ``forum`` agent will extend this method.
        """
        # A global ban always wins.
        global_bans = await self._repo.list_active_bans(user_id, scope=BanScope.GLOBAL)
        if global_bans:
            return True
        if scope is BanScope.GLOBAL:
            return False
        if scope is BanScope.SECTION:
            if section_id is None:
                return False
            section_bans = await self._repo.list_active_bans(
                user_id, scope=BanScope.SECTION, section_id=section_id
            )
            return bool(section_bans)
        # scope is BanScope.TOPIC
        if topic_id is None:
            return False
        topic_bans = await self._repo.list_active_bans(
            user_id, scope=BanScope.TOPIC, topic_id=topic_id
        )
        return bool(topic_bans)


__all__ = ["RbacService"]
