"""Pydantic v2 schemas for the ``messages`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.content.schemas import DocSchema
from app.modules.messages.models import MessageStatus
from app.modules.users.schemas import UserPublic


def _coerce_doc(value: Any) -> DocSchema:
    """Accept either a raw dict (HTTP JSON body) or an already-built ``DocSchema``."""
    if isinstance(value, DocSchema):
        return value
    if isinstance(value, dict):
        return DocSchema.model_validate(value)
    raise ValueError("content must be a DocSchema or a JSON object")


# ---------------------------------------------------------------------------
# Reply-on-selection — request shape
# ---------------------------------------------------------------------------


class ReplyTargetSchema(BaseModel):
    """Pointer to the parent row a reply hangs off."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["article", "message"]
    id: UUID


class ReplyToSelectionSchema(BaseModel):
    """Structured pointer + denormalised quote text.

    Mirrors :class:`app.modules.content.schemas.ReplySelection` but lives in
    this module because it's also the wire shape the route accepts and the
    JSONB shape we store on disk.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    target: ReplyTargetSchema
    block_path: list[int] = Field(default_factory=list)
    from_: int = Field(alias="from", ge=0)
    to: int = Field(ge=0)
    quote_text: str = ""


# ---------------------------------------------------------------------------
# Create / update payloads
# ---------------------------------------------------------------------------


class MessageCreate(BaseModel):
    """Body of ``POST /articles/{article_id}/messages``."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    content: DocSchema
    parent_id: UUID | None = None
    reply_to_selection: ReplyToSelectionSchema | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _validate_content(cls, value: Any) -> DocSchema:
        return _coerce_doc(value)


class MessageUpdate(BaseModel):
    """Body of ``PATCH /messages/{message_id}``."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    content: DocSchema
    edit_reason: str | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _validate_content(cls, value: Any) -> DocSchema:
        return _coerce_doc(value)


# ---------------------------------------------------------------------------
# Read shape
# ---------------------------------------------------------------------------


class MessageRead(BaseModel):
    """Wire shape returned by every messages endpoint.

    ``content`` is ``None`` (and ``placeholder`` is populated) for messages
    in ``deleted_by_author`` / ``hidden_by_mod`` states — the UI renders the
    placeholder text instead of the original body.
    """

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: UUID
    article_id: UUID
    parent_id: UUID | None = None
    thread_root_id: UUID | None = None
    depth: int
    path: str
    author: UserPublic
    content: DocSchema | None = None
    placeholder: str | None = None
    status: MessageStatus
    reply_to_selection: ReplyToSelectionSchema | None = None
    mentioned_user_ids: list[UUID] = Field(default_factory=list)
    reaction_counts: dict[str, int] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


__all__ = [
    "MessageCreate",
    "MessageRead",
    "MessageUpdate",
    "ReplyTargetSchema",
    "ReplyToSelectionSchema",
]
