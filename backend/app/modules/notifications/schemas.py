"""Pydantic v2 schemas for the ``notifications`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    is_read: bool
    created_at: datetime


class MarkReadRequest(BaseModel):
    """Body of ``POST /me/notifications/mark-read``."""

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(default_factory=list)


class UnreadCount(BaseModel):
    count: int


__all__ = ["MarkReadRequest", "NotificationRead", "UnreadCount"]
