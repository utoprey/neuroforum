"""Pydantic v2 schemas for the ``mentions`` module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.mentions.models import MentionSourceType
from app.modules.users.schemas import UserPublic


class MentionRead(BaseModel):
    """Wire shape for ``GET /me/mentions``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: MentionSourceType
    source_id: UUID
    mentioned_user: UserPublic
    author: UserPublic
    created_at: datetime
    notified_at: datetime | None = None


__all__ = ["MentionRead"]
