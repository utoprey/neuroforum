"""Pydantic v2 schemas for the ``ai_proposals`` module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.ai_proposals.models import AIProposalAction, AIProposalStatus
from app.modules.content.schemas import DocSchema
from app.modules.users.schemas import UserPublic


def _coerce_doc(value: Any) -> DocSchema:
    """Accept a raw dict (HTTP JSON) or an already-built ``DocSchema``."""
    if isinstance(value, DocSchema):
        return value
    if isinstance(value, dict):
        return DocSchema.model_validate(value)
    raise ValueError("content must be a DocSchema or a JSON object")


class SelectionSchema(BaseModel):
    """Pointer into the article's ProseMirror tree."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    block_path: list[int] = Field(default_factory=list)
    from_: int = Field(alias="from", ge=0)
    to: int = Field(ge=0)


class AIProposalCreate(BaseModel):
    """Body of ``POST /articles/{article_id}/ai-proposals``."""

    model_config = ConfigDict(extra="forbid")

    action: AIProposalAction
    selection: SelectionSchema | None = None
    prompt: str | None = None
    agent_id: UUID | None = None


class AIProposalDecision(BaseModel):
    """Body of ``POST /ai-proposals/{id}/reject`` (and similar)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "reject"]
    reason: str | None = None


class AIProposalContentUpdate(BaseModel):
    """Body of ``PATCH /ai-proposals/{id}``.

    Plain ``dict`` here — validation against ``DocSchema`` happens in the
    service layer via ``content.validate_doc`` so callers get a consistent
    error path regardless of which entry point edits a proposal.
    """

    model_config = ConfigDict(extra="forbid")

    proposed_content: dict[str, Any]


class AIProposalRead(BaseModel):
    """Wire shape returned by every AI proposal endpoint."""

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)

    id: UUID
    article_id: UUID
    requested_by: UserPublic
    agent: UserPublic | None = None
    action: AIProposalAction
    selection: SelectionSchema | None = None
    prompt: str | None = None
    proposed_content: DocSchema
    status: AIProposalStatus
    decided_by: UserPublic | None = None
    decided_at: datetime | None = None
    created_at: datetime
    expires_at: datetime
    # Optional metadata about the LLM call that produced ``proposed_content``.
    # Populated only when a real provider (e.g. OpenRouter) handled the
    # request; ``None`` for stubbed proposals. Shape: ``{"model": str,
    # "input_tokens": int, "output_tokens": int, "cost_usd": str,
    # "duration_ms": int | None}``.
    llm_meta: dict[str, Any] | None = None

    @field_validator("proposed_content", mode="before")
    @classmethod
    def _validate_content(cls, value: Any) -> DocSchema:
        return _coerce_doc(value)


__all__ = [
    "AIProposalContentUpdate",
    "AIProposalCreate",
    "AIProposalDecision",
    "AIProposalRead",
    "SelectionSchema",
]
