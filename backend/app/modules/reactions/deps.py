"""FastAPI dependencies for the ``reactions`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.reactions.service import ReactionService


def get_reaction_service(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ReactionService:
    return ReactionService(db)


__all__ = ["get_reaction_service"]
