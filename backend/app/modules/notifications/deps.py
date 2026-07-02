"""FastAPI dependencies for the ``notifications`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.service import NotificationService


def get_notification_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> NotificationRepository:
    return NotificationRepository(db)


def get_notification_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[
        NotificationRepository, Depends(get_notification_repository)
    ],
) -> NotificationService:
    return NotificationService(repo, db)


__all__ = ["get_notification_repository", "get_notification_service"]
