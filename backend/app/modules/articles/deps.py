"""FastAPI dependencies for the ``articles`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.service import ArticleService
from app.modules.forum.deps import get_forum_repository
from app.modules.forum.repository import ForumRepository
from app.modules.mentions.deps import get_mention_service
from app.modules.mentions.service import MentionService
from app.modules.notifications.deps import get_notification_service
from app.modules.notifications.service import NotificationService
from app.modules.users.deps import get_user_service
from app.modules.users.service import UserService


def get_article_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ArticleRepository:
    return ArticleRepository(db)


def get_article_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[ArticleRepository, Depends(get_article_repository)],
    forum: Annotated[ForumRepository, Depends(get_forum_repository)],
    mentions: Annotated[MentionService, Depends(get_mention_service)],
    notifications: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
    users: Annotated[UserService, Depends(get_user_service)],
) -> ArticleService:
    return ArticleService(
        repo,
        forum,
        db,
        mention_service=mentions,
        notification_service=notifications,
        user_service=users,
    )


__all__ = ["get_article_repository", "get_article_service"]
