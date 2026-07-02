"""HTTP routes for the ``dm`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.content.enricher import enrich_content
from app.modules.content.schemas import DocSchema
from app.modules.dm.deps import get_dm_service
from app.modules.dm.exceptions import (
    CannotDmYourself,
    ConversationNotFound,
    DirectMessageNotFound,
    NotEditable,
    NotParticipant,
)
from app.modules.dm.models import (
    Conversation,
    ConversationParticipant,
    DirectMessage,
)
from app.modules.dm.schemas import (
    ConversationCreateDM,
    ConversationRead,
    DirectMessageCreate,
    DirectMessageRead,
    DirectMessageUpdate,
)
from app.modules.dm.service import DMService
from app.modules.users.deps import get_current_user
from app.modules.users.exceptions import UserNotFound
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic
from app.modules.users.service import to_user_public

router = APIRouter(tags=["dm"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_public(user: User) -> UserPublic:
    return to_user_public(user)


def _conversation_read(
    conversation: Conversation,
    participants: list[tuple[ConversationParticipant, User]],
    unread: int,
) -> ConversationRead:
    return ConversationRead(
        id=conversation.id,
        kind=conversation.kind,
        title=conversation.title,
        participants=[_user_public(u) for _, u in participants],
        last_message_at=conversation.last_message_at,
        unread_count=unread,
    )


async def _message_read(
    message: DirectMessage, author: User, db: AsyncSession
) -> DirectMessageRead:
    placeholder = DMService.placeholder_for(message)
    if DMService.is_redacted(message):
        content: DocSchema | None = None
    else:
        enriched = await enrich_content(message.content, db)
        content = DocSchema.model_validate(enriched)
    return DirectMessageRead(
        id=message.id,
        conversation_id=message.conversation_id,
        author=_user_public(author),
        content=content,
        placeholder=placeholder,
        reply_to_id=message.reply_to_id,
        status=message.status,
        attachments=list(message.attachments or []),
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


@router.post(
    "/conversations/dm",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Open (or fetch existing) DM between the actor and target_user_id",
)
async def create_dm_conversation(
    payload: ConversationCreateDM,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[DMService, Depends(get_dm_service)],
) -> ConversationRead:
    try:
        conversation = await svc.start_dm(actor, payload.target_user_id)
    except CannotDmYourself as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot start a DM with yourself",
        ) from exc
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target user not found",
        ) from exc
    # Build the response with participants + zero unread (just opened).
    participants = await svc._repo.list_participants(
        conversation.id
    )
    participant = await svc._repo.get_participant(
        conversation.id, actor.id
    )
    unread = await svc._repo.count_unread_for_participant(
        conversation.id,
        actor.id,
        participant.last_read_at if participant else None,
    )
    return _conversation_read(conversation, participants, unread)


@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    summary="List my conversations, newest activity first",
)
async def list_my_conversations(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[DMService, Depends(get_dm_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ConversationRead]:
    triples = await svc.list_my_conversations(actor, limit=limit, offset=offset)
    return [
        _conversation_read(conversation, participants, unread)
        for conversation, participants, unread in triples
    ]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[DirectMessageRead],
    summary="List messages in a conversation (newest first)",
)
async def list_messages(
    conversation_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[DMService, Depends(get_dm_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DirectMessageRead]:
    try:
        pairs = await svc.list_messages(
            actor, conversation_id, limit=limit, offset=offset
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from exc
    except NotParticipant as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this conversation",
        ) from exc
    return [await _message_read(m, a, db) for m, a in pairs]


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=DirectMessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Post a message in a conversation",
)
async def post_message(
    conversation_id: UUID,
    payload: DirectMessageCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[DMService, Depends(get_dm_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> DirectMessageRead:
    try:
        message, author = await svc.send_message(
            actor, conversation_id, payload
        )
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from exc
    except NotParticipant as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this conversation",
        ) from exc
    return await _message_read(message, author, db)


@router.patch(
    "/messages/dm/{message_id}",
    response_model=DirectMessageRead,
    summary="Edit a direct message (author only)",
)
async def patch_message(
    message_id: UUID,
    payload: DirectMessageUpdate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[DMService, Depends(get_dm_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> DirectMessageRead:
    try:
        message, author = await svc.edit_message(actor, message_id, payload)
    except DirectMessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc
    except NotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except NotParticipant as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this conversation",
        ) from exc
    return await _message_read(message, author, db)


@router.delete(
    "/messages/dm/{message_id}",
    response_model=DirectMessageRead,
    summary="Soft-delete a direct message (author only)",
)
async def delete_message(
    message_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[DMService, Depends(get_dm_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> DirectMessageRead:
    try:
        message, author = await svc.delete_message(actor, message_id)
    except DirectMessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc
    except NotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return await _message_read(message, author, db)


@router.post(
    "/conversations/{conversation_id}/mark-read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark this conversation as read up to now",
)
async def mark_read(
    conversation_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[DMService, Depends(get_dm_service)],
) -> Response:
    try:
        await svc.mark_read(actor, conversation_id)
    except ConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        ) from exc
    except NotParticipant as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this conversation",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
