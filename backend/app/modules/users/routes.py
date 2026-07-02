"""HTTP routes for the ``users`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.ratelimit import limiter
from app.modules.articles.schemas import ArticlePublic
from app.modules.users.deps import get_current_user, get_user_service
from app.modules.users.exceptions import (
    EmailTaken,
    UsernameTaken,
    UserNotFound,
)
from app.modules.users.models import User
from app.modules.users.schemas import (
    ProfileRead,
    ProfileUpdate,
    RecentMessage,
    RecentTopic,
    UserCreate,
    UserPublic,
    UserReactionItem,
    UserRead,
)
from app.modules.users.service import UserService, to_user_public, to_user_read

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
@limiter.limit("3/minute")  # abuse guard for the public open endpoint
async def register_user(
    payload: UserCreate,
    request: Request,
    svc: Annotated[UserService, Depends(get_user_service)],
) -> UserRead:
    try:
        user = await svc.create_user(payload)
    except UsernameTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already taken"
        ) from exc
    except EmailTaken as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc
    return to_user_read(user)


@router.get("/me", response_model=UserRead, summary="Current user (self)")
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserRead:
    return to_user_read(current_user)


@router.patch(
    "/me/profile", response_model=ProfileRead, summary="Update current user's profile"
)
async def patch_my_profile(
    payload: ProfileUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    svc: Annotated[UserService, Depends(get_user_service)],
) -> ProfileRead:
    profile = await svc.update_profile(current_user.id, payload)
    return ProfileRead.model_validate(profile)


@router.get(
    "/search",
    response_model=list[UserPublic],
    summary="Search users (@prefix or trigram fuzzy)",
)
async def search_users(
    q: Annotated[str, Query(min_length=1)],
    svc: Annotated[UserService, Depends(get_user_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[UserPublic]:
    users = await svc.search_users(q, limit=limit)
    return [to_user_public(u) for u in users]


@router.get("/{username}", response_model=UserRead, summary="Public user view")
async def get_user_by_username(
    username: str,
    svc: Annotated[UserService, Depends(get_user_service)],
) -> UserRead:
    try:
        user = await svc.get_by_username(username)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    # Return the same wire-shape as ``/users/me`` (profile + stats) so the
    # public profile page can show full bio, ORCID, social links, and the
    # activity counters. Strip the email since that's user-private.
    out = to_user_read(user)
    return out.model_copy(update={"email": None})


@router.get(
    "/{username}/recent-topics",
    response_model=list[RecentTopic],
    summary="Recently active topics for the user (by latest authored message)",
)
async def get_recent_topics(
    username: str,
    svc: Annotated[UserService, Depends(get_user_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[RecentTopic]:
    try:
        user = await svc.get_by_username(username)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    return await svc.recent_topics(user.id, limit=limit)


@router.get(
    "/{username}/recent-messages",
    response_model=list[RecentMessage],
    summary="Recent messages authored by the user (with topic/article context)",
)
async def get_recent_messages(
    username: str,
    svc: Annotated[UserService, Depends(get_user_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[RecentMessage]:
    try:
        user = await svc.get_by_username(username)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    return await svc.recent_messages(user.id, limit=limit)


# ---------------------------------------------------------------------------
# Paginated activity feeds — articles / messages / reactions
# ---------------------------------------------------------------------------


@router.get(
    "/{username}/articles",
    response_model=list[ArticlePublic],
    summary="List published articles authored by the user (newest first)",
)
async def list_user_articles(
    username: str,
    svc: Annotated[UserService, Depends(get_user_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ArticlePublic]:
    # Import the public builder lazily to avoid a circular import at module
    # load: ``articles.routes`` imports ``users.service`` for ``to_user_public``.
    from app.modules.articles.routes import build_article_public

    try:
        pairs = await svc.user_articles(username, limit=limit, offset=offset)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    return [build_article_public(article, author) for article, author in pairs]


@router.get(
    "/{username}/messages",
    response_model=list[RecentMessage],
    summary="Paginated list of messages authored by the user (newest first)",
)
async def list_user_messages(
    username: str,
    svc: Annotated[UserService, Depends(get_user_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RecentMessage]:
    try:
        user = await svc.get_by_username(username)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc
    return await svc.recent_messages(user.id, limit=limit, offset=offset)


@router.get(
    "/{username}/reactions",
    response_model=list[UserReactionItem],
    summary="List reactions the user has left (articles + messages merged)",
)
async def list_user_reactions(
    username: str,
    svc: Annotated[UserService, Depends(get_user_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserReactionItem]:
    try:
        return await svc.user_reactions(username, limit=limit, offset=offset)
    except UserNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        ) from exc


__all__ = ["router"]
