"""FastAPI dependencies for the ``agents`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.agents.repository import AgentRepository
from app.modules.agents.service import AgentService
from app.modules.users.repository import UserRepository


def get_agent_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AgentRepository:
    return AgentRepository(db)


def get_agent_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[AgentRepository, Depends(get_agent_repository)],
) -> AgentService:
    return AgentService(repo, UserRepository(db), db)


__all__ = ["get_agent_repository", "get_agent_service"]
