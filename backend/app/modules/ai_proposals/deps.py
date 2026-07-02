"""FastAPI dependencies for the ``ai_proposals`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.agents.deps import get_agent_service
from app.modules.agents.service import AgentService
from app.modules.ai_proposals.repository import AIProposalRepository
from app.modules.ai_proposals.service import AIProposalService
from app.modules.articles.deps import get_article_service
from app.modules.articles.service import ArticleService


def get_ai_proposal_repository(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> AIProposalRepository:
    return AIProposalRepository(db)


def get_ai_proposal_service(
    db: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[
        AIProposalRepository, Depends(get_ai_proposal_repository)
    ],
    articles: Annotated[ArticleService, Depends(get_article_service)],
    agents: Annotated[AgentService, Depends(get_agent_service)],
) -> AIProposalService:
    # ``agent_service`` is wired in by default so the production POST flow
    # uses the user's BYO LLM credential. Unit tests bypass DI and construct
    # the service directly with ``agent_service=None`` to stay on the stub.
    return AIProposalService(repo, articles, db, agent_service=agents)


__all__ = ["get_ai_proposal_repository", "get_ai_proposal_service"]
