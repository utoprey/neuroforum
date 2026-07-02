"""HTTP routes for the ``forum`` module — sections and topics."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.modules.forum.deps import get_forum_service
from app.modules.forum.exceptions import (
    InsufficientRole,
    SectionNotFound,
    SlugConflict,
    TopicNotFound,
)
from app.modules.forum.models import Topic, TopicKind
from app.modules.forum.schemas import (
    SectionCreate,
    SectionRead,
    SectionUpdate,
    TopicCreate,
    TopicLockToggle,
    TopicRead,
    TopicUpdate,
)
from app.modules.forum.service import ForumService
from app.modules.users.deps import get_current_user, require_roles
from app.modules.users.models import Role, User
from app.modules.users.service import to_user_public

# Empty prefix because this module owns *two* distinct prefixes (``/sections``
# and ``/topics``); the path on each handler does the rest.
router = APIRouter(tags=["forum"])

_admin_only = require_roles(Role.ADMIN)
_mod_or_admin = require_roles(Role.MODERATOR, Role.ADMIN)


def _topic_read(topic: Topic, author: User, section_slug: str | None = None) -> TopicRead:
    """Serialize a topic. ``section_slug`` may be passed explicitly when the
    caller already knows it (route path param); otherwise we read it from
    the eager-loaded ``Topic.section`` relationship.
    """
    resolved_section_slug = (
        section_slug if section_slug is not None else topic.section.slug
    )
    return TopicRead(
        id=topic.id,
        section_id=topic.section_id,
        section_slug=resolved_section_slug,
        slug=topic.slug,
        title=topic.title,
        description=topic.description,
        is_locked=topic.is_locked,
        is_pinned=topic.is_pinned,
        kind=topic.kind,
        created_by=to_user_public(author),
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@router.get(
    "/sections",
    response_model=list[SectionRead],
    summary="List forum sections (ordered by position)",
)
async def list_sections(
    svc: Annotated[ForumService, Depends(get_forum_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SectionRead]:
    sections = await svc.list_sections(limit=limit, offset=offset)
    return [SectionRead.model_validate(s) for s in sections]


@router.post(
    "/sections",
    response_model=SectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a section (admin only)",
)
async def create_section(
    payload: SectionCreate,
    actor: Annotated[User, Depends(_admin_only)],
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> SectionRead:
    try:
        section = await svc.create_section(actor, payload)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except SlugConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return SectionRead.model_validate(section)


@router.get(
    "/sections/{slug}",
    response_model=SectionRead,
    summary="Fetch a section by slug",
)
async def get_section(
    slug: str,
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> SectionRead:
    try:
        section = await svc.get_section_by_slug(slug)
    except SectionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
        ) from exc
    return SectionRead.model_validate(section)


@router.patch(
    "/sections/{slug}",
    response_model=SectionRead,
    summary="Update a section (admin only)",
)
async def patch_section(
    slug: str,
    payload: SectionUpdate,
    actor: Annotated[User, Depends(_admin_only)],
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> SectionRead:
    try:
        section = await svc.update_section(actor, slug, payload)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except SectionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
        ) from exc
    except SlugConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return SectionRead.model_validate(section)


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


@router.get(
    "/sections/{slug}/topics",
    response_model=list[TopicRead],
    summary="List topics in a section (pinned first, newest after)",
)
async def list_topics(
    slug: str,
    svc: Annotated[ForumService, Depends(get_forum_service)],
    kind: Annotated[TopicKind | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TopicRead]:
    try:
        pairs = await svc.list_topics_for_section(
            slug, kind=kind, limit=limit, offset=offset
        )
    except SectionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
        ) from exc
    return [_topic_read(topic, author, slug) for topic, author in pairs]


@router.post(
    "/sections/{slug}/topics",
    response_model=TopicRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a topic in a section (any authed user for "
    "discussion/help/flood; mod/admin for news)",
)
async def create_topic(
    slug: str,
    payload: TopicCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> TopicRead:
    try:
        topic, author = await svc.create_topic(actor, slug, payload)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except SectionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
        ) from exc
    except SlugConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _topic_read(topic, author, slug)


@router.get(
    "/topics/{topic_id}",
    response_model=TopicRead,
    summary="Fetch a topic by id",
)
async def get_topic(
    topic_id: UUID,
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> TopicRead:
    try:
        topic, author = await svc.get_topic(topic_id)
    except TopicNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        ) from exc
    return _topic_read(topic, author)


@router.get(
    "/sections/{section_slug}/topics/{topic_slug}",
    response_model=TopicRead,
    summary="Fetch a topic by (section_slug, topic_slug)",
)
async def get_topic_by_slug(
    section_slug: str,
    topic_slug: str,
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> TopicRead:
    """Slug-based topic resolution.

    Mirrors :func:`get_topic` but takes the human-readable
    ``(section_slug, topic_slug)`` pair. Distinguishes 404 on missing
    section vs missing topic via the message detail.
    """
    try:
        topic, author = await svc.get_topic_by_slug(section_slug, topic_slug)
    except SectionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
        ) from exc
    except TopicNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        ) from exc
    return _topic_read(topic, author, section_slug)


@router.patch(
    "/topics/{topic_id}",
    response_model=TopicRead,
    summary="Update a topic (moderator/admin)",
)
async def patch_topic(
    topic_id: UUID,
    payload: TopicUpdate,
    actor: Annotated[User, Depends(_mod_or_admin)],
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> TopicRead:
    try:
        topic, author = await svc.update_topic(actor, topic_id, payload)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except TopicNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        ) from exc
    return _topic_read(topic, author)


@router.post(
    "/topics/{topic_id}/lock",
    response_model=TopicRead,
    summary="Toggle a topic's locked flag (moderator/admin)",
)
async def lock_topic(
    topic_id: UUID,
    payload: TopicLockToggle,
    actor: Annotated[User, Depends(_mod_or_admin)],
    svc: Annotated[ForumService, Depends(get_forum_service)],
) -> TopicRead:
    try:
        topic, author = await svc.lock_topic(actor, topic_id, payload.locked)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except TopicNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        ) from exc
    return _topic_read(topic, author)


__all__ = ["router"]
