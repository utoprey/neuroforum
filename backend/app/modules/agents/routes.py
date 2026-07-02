"""HTTP routes for the ``agents`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.modules.agents.deps import get_agent_service
from app.modules.agents.exceptions import (
    AgentNotFound,
    AgentTokenNotFound,
    CredentialNameTaken,
    CredentialNotFound,
    NotAgentOwner,
    NotAgentTokenOwner,
    NotCredentialOwner,
)
from app.modules.agents.models import Agent, AgentCredential
from app.modules.agents.schemas import (
    AgentCreate,
    AgentCredentialCreate,
    AgentCredentialRead,
    AgentCredentialUpdate,
    AgentRead,
    AgentTokenCreate,
    AgentTokenCreated,
    AgentTokenRead,
)
from app.modules.agents.service import AgentService
from app.modules.users.deps import get_current_user
from app.modules.users.exceptions import UsernameTaken
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _credential_read(credential: AgentCredential) -> AgentCredentialRead:
    return AgentCredentialRead.model_validate(credential)


def _user_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        username=user.username,
        display_name=(user.profile.display_name if user.profile else None),
        avatar_url=(user.profile.avatar_url if user.profile else None),
        role=user.role,
    )


def _agent_read(
    agent: Agent,
    bot_user: User,
    owner: User,
    credential: AgentCredential | None,
) -> AgentRead:
    return AgentRead(
        user_id=agent.user_id,
        username=bot_user.username,
        display_name=(bot_user.profile.display_name if bot_user.profile else None),
        owner=_user_public(owner),
        credential=_credential_read(credential) if credential is not None else None,
        system_prompt=agent.system_prompt,
        allowed_actions=list(agent.allowed_actions or []),
        created_at=agent.created_at,
    )


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@router.post(
    "/credentials",
    response_model=AgentCredentialRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new BYO LLM credential",
)
async def create_credential(
    payload: AgentCredentialCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentCredentialRead:
    try:
        credential = await svc.create_credential(actor, payload)
    except CredentialNameTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credential display_name already used: {exc}",
        ) from exc
    return _credential_read(credential)


@router.get(
    "/credentials",
    response_model=list[AgentCredentialRead],
    summary="List my credentials (newest first)",
)
async def list_credentials(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> list[AgentCredentialRead]:
    rows = await svc.list_my_credentials(actor)
    return [_credential_read(c) for c in rows]


@router.get(
    "/credentials/{credential_id}",
    response_model=AgentCredentialRead,
    summary="Fetch one credential (owner or admin)",
)
async def get_credential(
    credential_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentCredentialRead:
    try:
        credential = await svc.get_credential(actor, credential_id)
    except CredentialNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found"
        ) from exc
    except NotCredentialOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this credential",
        ) from exc
    return _credential_read(credential)


@router.patch(
    "/credentials/{credential_id}",
    response_model=AgentCredentialRead,
    summary="Patch a credential (owner only). Pass api_key to rotate.",
)
async def patch_credential(
    credential_id: UUID,
    payload: AgentCredentialUpdate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentCredentialRead:
    try:
        credential = await svc.update_credential(actor, credential_id, payload)
    except CredentialNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found"
        ) from exc
    except NotCredentialOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this credential",
        ) from exc
    except CredentialNameTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Credential display_name already used: {exc}",
        ) from exc
    return _credential_read(credential)


@router.delete(
    "/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a credential (owner only)",
)
async def delete_credential(
    credential_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> Response:
    try:
        await svc.delete_credential(actor, credential_id)
    except CredentialNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found"
        ) from exc
    except NotCredentialOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this credential",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Agents (bot users)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new bot user + agent record",
)
async def create_agent(
    payload: AgentCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentRead:
    try:
        agent, bot_user, owner = await svc.create_agent(actor, payload)
    except CredentialNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found"
        ) from exc
    except NotCredentialOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this credential",
        ) from exc
    except UsernameTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username already taken: {exc}",
        ) from exc
    credential = (
        await svc._repo.get_credential(agent.credential_id)
        if agent.credential_id is not None
        else None
    )
    return _agent_read(agent, bot_user, owner, credential)


@router.get(
    "",
    response_model=list[AgentRead],
    summary="List my agents",
)
async def list_my_agents(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> list[AgentRead]:
    rows = await svc.list_my_agents(actor)
    return [
        _agent_read(agent, bot, owner, credential)
        for agent, bot, owner, credential in rows
    ]


@router.get(
    "/{agent_user_id}",
    response_model=AgentRead,
    summary="Fetch one agent (owner or admin)",
)
async def get_agent(
    agent_user_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentRead:
    try:
        agent, bot, owner, credential = await svc.get_agent(actor, agent_user_id)
    except AgentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc
    except NotAgentOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this agent",
        ) from exc
    return _agent_read(agent, bot, owner, credential)


@router.delete(
    "/{agent_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete an agent (owner only)",
)
async def delete_agent(
    agent_user_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> Response:
    try:
        await svc.delete_agent(actor, agent_user_id)
    except AgentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc
    except NotAgentOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this agent",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Agent tokens (bot bearer tokens)
# ---------------------------------------------------------------------------


@router.post(
    "/{agent_user_id}/tokens",
    response_model=AgentTokenCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Mint a new bot token for an agent (raw token shown once)",
)
async def create_agent_token(
    agent_user_id: UUID,
    payload: AgentTokenCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentTokenCreated:
    try:
        token, raw = await svc.create_agent_token(
            actor, agent_user_id, payload.name, payload.scopes
        )
    except AgentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc
    except NotAgentOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this agent",
        ) from exc
    # Build response by hand — model_validate(token) loses ``raw_token``.
    return AgentTokenCreated(
        id=token.id,
        agent_id=token.agent_id,
        name=token.name,
        scopes=list(token.scopes or []),
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
        created_at=token.created_at,
        raw_token=raw,
    )


@router.get(
    "/{agent_user_id}/tokens",
    response_model=list[AgentTokenRead],
    summary="List tokens for an agent (owner or admin)",
)
async def list_agent_tokens(
    agent_user_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> list[AgentTokenRead]:
    try:
        tokens = await svc.list_agent_tokens(actor, agent_user_id)
    except AgentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc
    except NotAgentOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this agent",
        ) from exc
    return [AgentTokenRead.model_validate(t) for t in tokens]


@router.delete(
    "/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a bot token (owner or admin)",
)
async def revoke_agent_token(
    token_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[AgentService, Depends(get_agent_service)],
) -> Response:
    try:
        await svc.revoke_agent_token(actor, token_id)
    except AgentTokenNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Token not found"
        ) from exc
    except NotAgentTokenOwner as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not own this token's agent",
        ) from exc
    except AgentNotFound as exc:
        # Defensive: shouldn't happen given the FK on agent_tokens.agent_id.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
