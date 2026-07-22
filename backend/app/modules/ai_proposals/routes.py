"""HTTP routes for the ``ai_proposals`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.modules.ai_proposals.deps import (
    get_ai_proposal_repository,
    get_ai_proposal_service,
)
from app.modules.ai_proposals.exceptions import (
    NotAllowedToPropose,
    ProposalAlreadyDecided,
    ProposalExpired,
    ProposalNotFound,
)
from app.modules.ai_proposals.models import (
    AIProposalStatus,
    ArticleAIProposal,
)
from app.modules.ai_proposals.repository import AIProposalRepository
from app.modules.ai_proposals.schemas import (
    AIProposalContentUpdate,
    AIProposalCreate,
    AIProposalDecision,
    AIProposalRead,
    SelectionSchema,
)
from app.modules.ai_proposals.service import AIProposalService
from app.modules.articles.exceptions import ArticleNotFound, ContentInvalid
from app.modules.content.schemas import DocSchema
from app.modules.users.deps import get_current_user
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(tags=["ai_proposals"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        username=user.username,
        display_name=(user.profile.display_name if user.profile else None),
        avatar_url=(user.profile.avatar_url if user.profile else None),
        role=user.role,
    )


def _proposal_read(
    proposal: ArticleAIProposal, requester: User
) -> AIProposalRead:
    selection: SelectionSchema | None = None
    if proposal.selection:
        selection = SelectionSchema.model_validate(proposal.selection)
    context = proposal.context or {}
    raw_llm_meta = context.get("llm_meta") if isinstance(context, dict) else None
    llm_meta = raw_llm_meta if isinstance(raw_llm_meta, dict) else None
    return AIProposalRead(
        id=proposal.id,
        article_id=proposal.article_id,
        requested_by=_user_public(requester),
        agent=None,  # full agent enrichment deferred to a future iteration
        action=proposal.action,
        selection=selection,
        prompt=proposal.prompt,
        proposed_content=DocSchema.model_validate(proposal.proposed_content),
        status=proposal.status,
        decided_by=None,  # likewise — keep the wire shape stable, fill later
        decided_at=proposal.decided_at,
        created_at=proposal.created_at,
        expires_at=proposal.expires_at,
        llm_meta=llm_meta,
    )


# ---------------------------------------------------------------------------
# Create + list
# ---------------------------------------------------------------------------


@router.post(
    "/articles/{article_id}/ai-proposals",
    response_model=AIProposalRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an AI proposal for an article (author / mod / admin)",
)
async def create_proposal(
    article_id: UUID,
    payload: AIProposalCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AIProposalService, Depends(get_ai_proposal_service)],
) -> AIProposalRead:
    try:
        proposal, requester = await svc.create_proposal(
            actor, article_id, payload
        )
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except NotAllowedToPropose as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return _proposal_read(proposal, requester)


@router.get(
    "/articles/{article_id}/ai-proposals",
    response_model=list[AIProposalRead],
    summary="List AI proposals attached to an article",
)
async def list_proposals(
    article_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AIProposalService, Depends(get_ai_proposal_service)],
    status_filter: Annotated[
        AIProposalStatus | None, Query(alias="status")
    ] = None,
) -> list[AIProposalRead]:
    try:
        rows = await svc.list_for_article(
            actor, article_id, status_filter=status_filter
        )
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except NotAllowedToPropose as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return [_proposal_read(p, r) for p, r in rows]


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


@router.post(
    "/ai-proposals/{proposal_id}/accept",
    response_model=AIProposalRead,
    summary=(
        "Mark a proposal as accepted (useful). "
        "Does NOT modify the article — author can pick up the text manually."
    ),
)
async def accept_proposal(
    proposal_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AIProposalService, Depends(get_ai_proposal_service)],
) -> AIProposalRead:
    try:
        proposal = await svc.accept_proposal(actor, proposal_id)
    except ProposalNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found"
        ) from exc
    except ProposalExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Proposal has expired",
        ) from exc
    except ProposalAlreadyDecided as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal has already been decided",
        ) from exc
    except NotAllowedToPropose as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    return _proposal_read(proposal, actor)


@router.patch(
    "/ai-proposals/{proposal_id}",
    response_model=AIProposalRead,
    summary="Edit the proposed content (requester or mod/admin)",
)
async def update_proposal_content(
    proposal_id: UUID,
    payload: AIProposalContentUpdate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AIProposalService, Depends(get_ai_proposal_service)],
    repo: Annotated[
        AIProposalRepository, Depends(get_ai_proposal_repository)
    ],
) -> AIProposalRead:
    try:
        proposal = await svc.update_proposal_content(
            actor, proposal_id, payload.proposed_content
        )
    except ProposalNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found"
        ) from exc
    except ProposalExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Proposal has expired",
        ) from exc
    except NotAllowedToPropose as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except ContentInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    # Refetch with the original requester so the response wire shape stays
    # correct when a moderator edits someone else's proposal.
    with_user = await repo.get_with_users(proposal.id)
    requester = with_user[1] if with_user is not None else actor
    return _proposal_read(proposal, requester)


@router.post(
    "/ai-proposals/{proposal_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reject a pending proposal (optional reason in body)",
)
async def reject_proposal(
    proposal_id: UUID,
    payload: AIProposalDecision | None,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AIProposalService, Depends(get_ai_proposal_service)],
) -> Response:
    reason = payload.reason if payload is not None else None
    try:
        await svc.reject_proposal(actor, proposal_id, reason)
    except ProposalNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found"
        ) from exc
    except ProposalExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Proposal has expired",
        ) from exc
    except ProposalAlreadyDecided as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal has already been decided",
        ) from exc
    except NotAllowedToPropose as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
