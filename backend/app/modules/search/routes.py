"""HTTP routes for the ``search`` module."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.modules.search.deps import get_search_engine
from app.modules.search.protocol import SearchEngine
from app.modules.search.schemas import UnifiedSearchResult

router = APIRouter(tags=["search"])

SearchType = Literal["all", "articles", "messages", "users"]


@router.get(
    "/search",
    response_model=UnifiedSearchResult,
    summary="Search articles + messages + users (Postgres FTS / pg_trgm)",
)
async def search(
    engine: Annotated[SearchEngine, Depends(get_search_engine)],
    q: Annotated[str, Query(min_length=1)],
    type: Annotated[SearchType, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> UnifiedSearchResult:
    result = UnifiedSearchResult()
    if type in {"all", "articles"}:
        result.articles = await engine.search_articles(q, limit)
    if type in {"all", "messages"}:
        result.messages = await engine.search_messages(q, limit)
    if type in {"all", "users"}:
        result.users = await engine.search_users(q, limit)
    return result


__all__ = ["router"]
