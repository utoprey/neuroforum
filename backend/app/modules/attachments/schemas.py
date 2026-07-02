"""Pydantic v2 schemas for the ``attachments`` module."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.attachments.models import AttachmentKind, ProcessingStatus


class AttachmentUploadRequest(BaseModel):
    """Client describes what it wants to PUT — server validates + issues URL."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)
    kind: AttachmentKind


class AttachmentUploadResponse(BaseModel):
    """Server response: ``attachment_id`` + a presigned PUT URL."""

    model_config = ConfigDict(extra="forbid")

    attachment_id: UUID
    upload_url: str
    upload_method: str = "PUT"
    expires_in_sec: int
    object_key: str
    headers: dict[str, str] = Field(default_factory=dict)


class AttachmentFinalizeRequest(BaseModel):
    """Client confirmation after a successful PUT.

    Width/height/duration are optional client-side measurements; the
    backend trusts them only for metadata purposes (rendering hints).
    For VIDEO this also triggers the processing actor.
    """

    model_config = ConfigDict(extra="forbid")

    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    duration_sec: int | None = Field(default=None, ge=1)
    sha256_hash: str | None = Field(default=None, max_length=64)


class AttachmentRead(BaseModel):
    """Read view: public URL + metadata + processing state."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: AttachmentKind
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_sec: int | None = None
    processing_status: ProcessingStatus
    url: str
    poster_url: str | None = None
    created_at: datetime


class AttachmentKindLimits(BaseModel):
    """Per-kind upload constraints exposed to the frontend."""

    model_config = ConfigDict(extra="forbid")

    kind: AttachmentKind
    max_bytes: int
    max_mb: float
    allowed_mime_types: list[str]


class AttachmentLimits(BaseModel):
    """Aggregate response: all kinds and their limits."""

    model_config = ConfigDict(extra="forbid")

    kinds: list[AttachmentKindLimits]


__all__ = [
    "AttachmentFinalizeRequest",
    "AttachmentKindLimits",
    "AttachmentLimits",
    "AttachmentRead",
    "AttachmentUploadRequest",
    "AttachmentUploadResponse",
]
