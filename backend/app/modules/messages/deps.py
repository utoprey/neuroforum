"""FastAPI dependencies for the ``messages`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.mentions.deps import get_mention_service
from app.modules.mentions.service import MentionService
from app.modules.messages.repository import MessageRepository
from app.modules.messages.service import MessageService
from app.modules.notifications.deps import get_notification_service
from app.modules.notifications.service import NotificationService


def get_message_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MessageRepository:
    return MessageRepository(db)


def get_message_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[MessageRepository, Depends(get_message_repository)],
    mentions: Annotated[MentionService, Depends(get_mention_service)],
    notifications: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
) -> MessageService:
    return MessageService(
        repo,
        db,
        mention_service=mentions,
        notification_service=notifications,
    )


__all__ = ["get_message_repository", "get_message_service"]
