"""HTTP routes for the ``messages`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.content.enricher import enrich_content
from app.modules.content.schemas import DocSchema
from app.modules.messages.deps import get_message_service
from app.modules.messages.exceptions import (
    ArticleNotPostable,
    MaxDepthExceeded,
    MessageNotFound,
    MissingEditReason,
    NotEditable,
    ParentNotInSameArticle,
    ReplyTargetNotFound,
)
from app.modules.messages.models import Message
from app.modules.messages.schemas import (
    MessageCreate,
    MessageRead,
    MessageUpdate,
    ReplyToSelectionSchema,
)
from app.modules.messages.service import MessageService
from app.modules.users.deps import get_current_user
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic
from app.modules.users.service import to_user_public

router = APIRouter(tags=["messages"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _author_public(author: User) -> UserPublic:
    return to_user_public(author)


async def _message_read(
    message: Message, author: User, db: AsyncSession
) -> MessageRead:
    placeholder = MessageService.placeholder_for(message)
    if MessageService.is_redacted(message):
        content: DocSchema | None = None
    else:
        enriched = await enrich_content(message.content, db)
        content = DocSchema.model_validate(enriched)

    reply: ReplyToSelectionSchema | None
    if message.reply_to_selection:
        reply = ReplyToSelectionSchema.model_validate(message.reply_to_selection)
    else:
        reply = None

    return MessageRead(
        id=message.id,
        article_id=message.article_id,
        parent_id=message.parent_id,
        thread_root_id=message.thread_root_id,
        depth=message.depth,
        path=message.path,
        author=_author_public(author),
        content=content,
        placeholder=placeholder,
        status=message.status,
        reply_to_selection=reply,
        mentioned_user_ids=list(message.mentioned_user_ids or []),
        reaction_counts=dict(message.reaction_counts or {}),
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


# ---------------------------------------------------------------------------
# List per article + thread
# ---------------------------------------------------------------------------


@router.get(
    "/articles/{article_id}/messages",
    response_model=list[MessageRead],
    summary="List top-level messages (with immediate children) for an article",
)
async def list_messages_for_article(
    article_id: UUID,
    svc: Annotated[MessageService, Depends(get_message_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MessageRead]:
    pairs = await svc.list_for_article(article_id, limit=limit, offset=offset)
    return [await _message_read(m, u, db) for m, u in pairs]


@router.get(
    "/messages/{message_id}/thread",
    response_model=list[MessageRead],
    summary="Fetch a message and every descendant in subtree order",
)
async def get_thread(
    message_id: UUID,
    svc: Annotated[MessageService, Depends(get_message_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[MessageRead]:
    try:
        pairs = await svc.get_thread(message_id)
    except MessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc
    return [await _message_read(m, u, db) for m, u in pairs]


# ---------------------------------------------------------------------------
# Post / edit / delete
# ---------------------------------------------------------------------------


@router.post(
    "/articles/{article_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Post a message (top-level or reply) on a published article",
)
async def post_message(
    article_id: UUID,
    payload: MessageCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[MessageService, Depends(get_message_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MessageRead:
    try:
        message, author = await svc.post_message(actor, article_id, payload)
    except ArticleNotPostable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article is not published or does not exist",
        ) from exc
    except ParentNotInSameArticle as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="parent_id belongs to a different article",
        ) from exc
    except MaxDepthExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ReplyTargetNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"reply_to_selection.target not found: {exc}",
        ) from exc
    except MessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parent message not found"
        ) from exc
    return await _message_read(message, author, db)


@router.patch(
    "/messages/{message_id}",
    response_model=MessageRead,
    summary="Edit a message (author or moderator/admin with reason)",
)
async def patch_message(
    message_id: UUID,
    payload: MessageUpdate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[MessageService, Depends(get_message_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MessageRead:
    try:
        message, author = await svc.edit_message(actor, message_id, payload)
    except MessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc
    except MissingEditReason as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except NotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return await _message_read(message, author, db)


@router.delete(
    "/messages/{message_id}",
    response_model=MessageRead,
    summary="Soft-delete a message (author -> deleted; mod -> hidden)",
)
async def delete_message(
    message_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[MessageService, Depends(get_message_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> MessageRead:
    try:
        message, author = await svc.soft_delete_message(actor, message_id)
    except MessageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc
    except NotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return await _message_read(message, author, db)


__all__ = ["router"]
