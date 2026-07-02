"""HTTP routes for the ``embeds`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.modules.embeds.deps import get_embed_service
from app.modules.embeds.exceptions import EmbedFetchFailed, UnsupportedProvider
from app.modules.embeds.schemas import EmbedResponse
from app.modules.embeds.service import EmbedService
from app.modules.users.deps import require_roles
from app.modules.users.models import Role, User

router = APIRouter(prefix="/embeds", tags=["embeds"])


@router.get(
    "/",
    response_model=EmbedResponse,
    summary="Resolve a URL to embed metadata (cached for 7 days)",
)
async def fetch_embed(
    svc: Annotated[EmbedService, Depends(get_embed_service)],
    url: Annotated[str, Query(min_length=1)],
) -> EmbedResponse:
    try:
        return await svc.fetch_embed(url)
    except UnsupportedProvider as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported embed provider for url: {url}",
        ) from exc
    except EmbedFetchFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc


@router.delete(
    "/",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Invalidate the cached embed for the given URL (admin only)",
)
async def invalidate_embed(
    url: Annotated[str, Query(min_length=1)],
    svc: Annotated[EmbedService, Depends(get_embed_service)],
    _admin: Annotated[User, Depends(require_roles(Role.ADMIN))],
) -> Response:
    await svc.invalidate(url)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
