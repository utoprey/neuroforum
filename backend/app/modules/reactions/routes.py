"""HTTP routes for the ``reactions`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.modules.reactions.deps import get_reaction_service
from app.modules.reactions.exceptions import ArticleNotFound, MessageNotFound
from app.modules.reactions.models import ReactionKind
from app.modules.reactions.schemas import ReactionRequest, ReactionSummary
from app.modules.reactions.service import ReactionService
from app.modules.users.deps import get_current_user
from app.modules.users.models import User

router = APIRouter(tags=["reactions"])


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


@router.post(
    "/articles/{article_id}/reactions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Add a reaction to an article (idempotent — double-post is a no-op)",
)
async def react_to_article(
    article_id: UUID,
    payload: ReactionRequest,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ReactionService, Depends(get_reaction_service)],
) -> Response:
    try:
        await svc.react_to_article(actor, article_id, payload.kind)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/articles/{article_id}/reactions/{kind}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a reaction from an article (idempotent)",
)
async def unreact_article(
    article_id: UUID,
    kind: ReactionKind,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ReactionService, Depends(get_reaction_service)],
) -> Response:
    try:
        await svc.unreact_article(actor, article_id, kind)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/articles/{article_id}/reactions",
    response_model=list[ReactionSummary],
    summary="List denormalised reaction counts for an article",
)
async def list_article_reactions(
    article_id: UUID,
    svc: Annotated[ReactionService, Depends(get_reaction_service)],
) -> list[ReactionSummary]:
    try:
        return await svc.get_article_reactions(article_id)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@router.post(
    "/messages/{message_id}/reactions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Add a reaction to a message (idempotent)",
)
async def react_to_message(
    message_id: UUID,
    payload: ReactionRequest,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ReactionService, Depends(get_reaction_service)],
) -> Response:
    try:
        await svc.react_to_message(actor, message_id, payload.kind)
    except MessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/messages/{message_id}/reactions/{kind}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove a reaction from a message (idempotent)",
)
async def unreact_message(
    message_id: UUID,
    kind: ReactionKind,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ReactionService, Depends(get_reaction_service)],
) -> Response:
    try:
        await svc.unreact_message(actor, message_id, kind)
    except MessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/messages/{message_id}/reactions",
    response_model=list[ReactionSummary],
    summary="List denormalised reaction counts for a message",
)
async def list_message_reactions(
    message_id: UUID,
    svc: Annotated[ReactionService, Depends(get_reaction_service)],
) -> list[ReactionSummary]:
    try:
        return await svc.get_message_reactions(message_id)
    except MessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc


__all__ = ["router"]
