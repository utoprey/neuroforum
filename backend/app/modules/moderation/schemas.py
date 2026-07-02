"""Pydantic v2 schemas for the ``moderation`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.users.models import Role


class HideArticleRequest(BaseModel):
    """Body of ``POST /moderation/articles/{id}/hide`` and ``/unhide``."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class AssignRoleRequest(BaseModel):
    """Body of ``POST /moderation/users/{id}/role``."""

    model_config = ConfigDict(extra="forbid")

    role: Role


class AuditLogRead(BaseModel):
    """Single audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: UUID
    action: str
    target_type: str
    target_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime


__all__ = ["AssignRoleRequest", "AuditLogRead", "HideArticleRequest"]
