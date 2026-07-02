"""HTTP routes for the ``mentions`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.modules.mentions.deps import get_mention_service
from app.modules.mentions.schemas import MentionRead
from app.modules.mentions.service import MentionService
from app.modules.users.deps import get_current_user
from app.modules.users.models import User
from app.modules.users.service import to_user_public as _user_public

router = APIRouter(tags=["mentions"])


@router.get(
    "/me/mentions",
    response_model=list[MentionRead],
    summary="List the current user's mentions, newest first",
)
async def list_my_mentions(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[MentionService, Depends(get_mention_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    unread: Annotated[bool, Query()] = False,
) -> list[MentionRead]:
    triples = await svc.list_my_mentions(
        actor, limit=limit, offset=offset, unread_only=unread
    )
    return [
        MentionRead(
            id=mention.id,
            source_type=mention.source_type,
            source_id=mention.source_id,
            mentioned_user=_user_public(mentioned_user),
            author=_user_public(author),
            created_at=mention.created_at,
            notified_at=mention.notified_at,
        )
        for mention, mentioned_user, author in triples
    ]


__all__ = ["router"]
