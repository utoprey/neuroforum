"""FastAPI dependencies for the ``attachments`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.attachments.repository import AttachmentRepository
from app.modules.attachments.service import AttachmentService


def get_attachment_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AttachmentRepository:
    return AttachmentRepository(db)


def get_attachment_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[AttachmentRepository, Depends(get_attachment_repository)],
) -> AttachmentService:
    return AttachmentService(repo, db)


__all__ = ["get_attachment_repository", "get_attachment_service"]
