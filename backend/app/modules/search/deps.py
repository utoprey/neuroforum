"""FastAPI dependencies for the ``search`` module.

Picks the concrete :class:`SearchEngine` backend by ``settings.SEARCH_BACKEND``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.modules.search.opensearch import OpenSearchSearchEngine
from app.modules.search.postgres import PostgresSearchEngine
from app.modules.search.protocol import SearchEngine


def get_search_engine(
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SearchEngine:
    """Return whichever backend ``SEARCH_BACKEND`` env selected."""
    if settings.SEARCH_BACKEND == "opensearch":
        return OpenSearchSearchEngine()
    return PostgresSearchEngine(db)


__all__ = ["get_search_engine"]
