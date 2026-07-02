"""Pydantic v2 schemas for the ``rbac`` module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.modules.rbac.models import BanScope


class BanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    reason: str
    scope: BanScope
    section_id: UUID | None = None
    topic_id: UUID | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _scope_target_consistency(self) -> BanCreate:
        if self.scope is BanScope.GLOBAL:
            if self.section_id is not None or self.topic_id is not None:
                raise ValueError(
                    "global ban must not specify section_id or topic_id"
                )
        elif self.scope is BanScope.SECTION:
            if self.section_id is None or self.topic_id is not None:
                raise ValueError(
                    "section ban requires section_id and forbids topic_id"
                )
        else:  # TOPIC
            if self.topic_id is None or self.section_id is not None:
                raise ValueError(
                    "topic ban requires topic_id and forbids section_id"
                )
        return self


class BanLift(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class BanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    banned_by: UUID
    reason: str
    scope: BanScope
    section_id: UUID | None = None
    topic_id: UUID | None = None
    starts_at: datetime
    expires_at: datetime | None = None
    lifted_at: datetime | None = None
    lifted_by: UUID | None = None
    lift_reason: str | None = None
    created_at: datetime


__all__ = ["BanCreate", "BanLift", "BanRead"]
