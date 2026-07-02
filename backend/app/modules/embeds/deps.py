"""FastAPI dependencies for the ``embeds`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.embeds.repository import EmbedRepository
from app.modules.embeds.service import EmbedService


def get_embed_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> EmbedRepository:
    return EmbedRepository(db)


def get_embed_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[EmbedRepository, Depends(get_embed_repository)],
) -> EmbedService:
    return EmbedService(repo, db)


__all__ = ["get_embed_repository", "get_embed_service"]
