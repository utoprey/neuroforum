"""Pydantic v2 schemas for the ``reactions`` module."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.modules.reactions.models import ReactionKind


class ReactionRequest(BaseModel):
    """Body of POST endpoints — only the ``kind`` is configurable."""

    model_config = ConfigDict(extra="forbid")

    kind: ReactionKind


class ReactionSummary(BaseModel):
    """One ``(kind, count)`` pair from the denormalised ``reaction_counts`` map."""

    model_config = ConfigDict(from_attributes=True)

    kind: ReactionKind
    count: int


__all__ = ["ReactionRequest", "ReactionSummary"]
