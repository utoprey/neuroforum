"""Pydantic v2 schemas for the ``dm`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.content.schemas import DocSchema
from app.modules.dm.models import ConversationKind, DirectMessageStatus
from app.modules.users.schemas import UserPublic


def _coerce_doc(value: Any) -> DocSchema:
    """Accept a raw dict (HTTP JSON) or an already-built ``DocSchema``."""
    if isinstance(value, DocSchema):
        return value
    if isinstance(value, dict):
        return DocSchema.model_validate(value)
    raise ValueError("content must be a DocSchema or a JSON object")


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------


class ConversationCreateDM(BaseModel):
    """Body of ``POST /conversations/dm``."""

    model_config = ConfigDict(extra="forbid")

    target_user_id: UUID


class ConversationRead(BaseModel):
    """Wire shape returned by conversation list/lookup endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: ConversationKind
    title: str | None = None
    participants: list[UserPublic] = Field(default_factory=list)
    last_message_at: datetime | None = None
    unread_count: int = 0


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class DirectMessageCreate(BaseModel):
    """Body of ``POST /conversations/{id}/messages``."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    content: DocSchema
    reply_to_id: UUID | None = None
    attachments: list[UUID] = Field(default_factory=list)

    @field_validator("content", mode="before")
    @classmethod
    def _validate_content(cls, value: Any) -> DocSchema:
        return _coerce_doc(value)


class DirectMessageUpdate(BaseModel):
    """Body of ``PATCH /messages/dm/{message_id}``."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    content: DocSchema

    @field_validator("content", mode="before")
    @classmethod
    def _validate_content(cls, value: Any) -> DocSchema:
        return _coerce_doc(value)


class DirectMessageRead(BaseModel):
    """Wire shape returned by every direct-message endpoint.

    ``content`` is ``None`` (and ``placeholder`` populated) when the message
    is in a soft-deleted state — the UI renders the placeholder instead.
    """

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: UUID
    conversation_id: UUID
    author: UserPublic
    content: DocSchema | None = None
    placeholder: str | None = None
    reply_to_id: UUID | None = None
    status: DirectMessageStatus
    attachments: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MarkAllReadRequest(BaseModel):
    """Empty body for ``POST /conversations/{id}/mark-read``."""

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "ConversationCreateDM",
    "ConversationRead",
    "DirectMessageCreate",
    "DirectMessageRead",
    "DirectMessageUpdate",
    "MarkAllReadRequest",
]
