"""Moderation business logic: hide / unhide / role assignment + audit log.

Every public method writes a row in ``audit_log`` so we never lose track of
who did what, when, from where.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import Article, ArticleStatus
from app.modules.moderation.exceptions import (
    ArticleNotFound,
    InsufficientRole,
    UserNotFound,
)
from app.modules.moderation.models import AuditLog
from app.modules.moderation.repository import ModerationRepository
from app.modules.users.models import Role, User

_MOD_OR_ADMIN: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})
_ADMIN_ONLY: frozenset[Role] = frozenset({Role.ADMIN})


class ModerationService:
    """Hide articles, assign roles, list audit log — all RBAC-checked."""

    def __init__(
        self, repo: ModerationRepository, db: AsyncSession
    ) -> None:
        self._repo = repo
        self._db = db

    # ------------------------------------------------------------------
    # Audit writer (used internally + can be called by other services)
    # ------------------------------------------------------------------

    async def log_action(
        self,
        actor: User,
        action: str,
        target_type: str,
        target_id: UUID,
        payload: dict[str, Any] | None = None,
        request: Request | None = None,
    ) -> AuditLog:
        """Record a row in ``audit_log``. ``request`` is optional — pulled for ip/ua."""
        ip, user_agent = _extract_client(request)
        return await self._repo.log_action(
            actor_id=actor.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=payload or {},
            ip=ip,
            user_agent=user_agent,
        )

    # ------------------------------------------------------------------
    # Article hide / unhide
    # ------------------------------------------------------------------

    async def hide_article(
        self,
        actor: User,
        article_id: UUID,
        reason: str,
        request: Request | None = None,
    ) -> Article:
        if actor.role not in _MOD_OR_ADMIN:
            raise InsufficientRole(
                "Moderator or admin role required to hide articles"
            )
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))
        previous_status = article.status.value
        article.status = ArticleStatus.HIDDEN
        await self._db.flush()
        await self._db.refresh(article, attribute_names=("updated_at",))
        await self.log_action(
            actor,
            "hide_article",
            "article",
            article.id,
            payload={"reason": reason, "previous_status": previous_status},
            request=request,
        )
        return article

    async def unhide_article(
        self,
        actor: User,
        article_id: UUID,
        reason: str,
        request: Request | None = None,
    ) -> Article:
        if actor.role not in _MOD_OR_ADMIN:
            raise InsufficientRole(
                "Moderator or admin role required to unhide articles"
            )
        article = await self._db.get(Article, article_id)
        if article is None:
            raise ArticleNotFound(str(article_id))
        previous_status = article.status.value
        article.status = ArticleStatus.PUBLISHED
        await self._db.flush()
        await self._db.refresh(article, attribute_names=("updated_at",))
        await self.log_action(
            actor,
            "unhide_article",
            "article",
            article.id,
            payload={"reason": reason, "previous_status": previous_status},
            request=request,
        )
        return article

    # ------------------------------------------------------------------
    # Role assignment
    # ------------------------------------------------------------------

    async def assign_role(
        self,
        actor: User,
        target_user_id: UUID,
        new_role: Role,
        request: Request | None = None,
    ) -> User:
        if actor.role not in _ADMIN_ONLY:
            raise InsufficientRole(
                "Admin role required to assign roles"
            )
        target = await self._db.get(User, target_user_id)
        if target is None:
            raise UserNotFound(str(target_user_id))
        previous_role = target.role.value
        target.role = new_role
        await self._db.flush()
        await self._db.refresh(target, attribute_names=("updated_at",))
        await self.log_action(
            actor,
            "assign_role",
            "user",
            target.id,
            payload={
                "previous_role": previous_role,
                "new_role": new_role.value,
            },
            request=request,
        )
        return target

    # ------------------------------------------------------------------
    # Audit read
    # ------------------------------------------------------------------

    async def list_audit(
        self,
        actor: User,
        *,
        actor_id: UUID | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        if actor.role not in _ADMIN_ONLY:
            raise InsufficientRole(
                "Admin role required to read the audit log"
            )
        return await self._repo.list_audit(
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            action=action,
            since=since,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )


def _extract_client(request: Request | None) -> tuple[str | None, str | None]:
    """Return ``(ip, user_agent)`` if the request carries them, else ``(None, None)``."""
    if request is None:
        return (None, None)
    ip: str | None = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return (ip, ua)


__all__ = ["ModerationService"]
