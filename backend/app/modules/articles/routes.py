"""HTTP routes for the ``articles`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.modules.articles.deps import get_article_service
from app.modules.articles.exceptions import (
    ArticleNotEditable,
    ArticleNotFound,
    MissingEditReason,
    SlugConflict,
)
from app.modules.articles.models import Article, ArticleRevision, ArticleStatus
from app.modules.articles.schemas import (
    ArticleCreate,
    ArticlePublic,
    ArticleRead,
    ArticleRevisionRead,
    ArticleUpdate,
)
from app.modules.articles.service import ArticleService
from app.modules.content.enricher import enrich_content
from app.modules.content.schemas import DocSchema
from app.modules.forum.deps import get_forum_service
from app.modules.forum.exceptions import (
    SectionNotFound,
    TopicLocked,
    TopicNotFound,
)
from app.modules.forum.service import ForumService
from app.modules.rbac.exceptions import InsufficientRole
from app.modules.users.deps import get_current_user, oauth2_scheme
from app.modules.users.exceptions import UserNotFound
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserPublic
from app.modules.users.service import to_user_public

router = APIRouter(tags=["articles"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def get_optional_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> User | None:
    """Like ``get_current_user`` but returns ``None`` for anonymous requests.

    Needed so anonymous viewers can fetch published articles without
    Authorization, but authed viewers still see their own drafts.
    """
    if not token:
        return None
    from uuid import UUID as _UUID

    from app.core.security import InvalidTokenError, decode_token

    try:
        claims = decode_token(token)
    except InvalidTokenError:
        return None
    if claims.get("type") != "access":
        return None
    sub = claims.get("sub")
    if not sub:
        return None
    try:
        user_id = _UUID(str(sub))
    except (ValueError, TypeError):
        return None
    try:
        user = await UserRepository(db).get(user_id)
    except UserNotFound:
        return None
    if user is None or not user.is_active:
        return None
    return user


def _author_public(author: User) -> UserPublic:
    return to_user_public(author)


async def _article_read(
    article: Article, author: User, db: AsyncSession
) -> ArticleRead:
    """Build an ``ArticleRead`` response with media-block ``src`` populated.

    The ``content`` JSONB only stores ``attachment_id`` for each media
    block — we hydrate ``src`` via :func:`enrich_content` so the frontend
    can render images without an additional round-trip per attachment.
    """
    enriched = await enrich_content(article.content, db)
    return ArticleRead(
        id=article.id,
        topic_id=article.topic_id,
        slug=article.slug,
        title=article.title,
        summary=article.summary,
        content=DocSchema.model_validate(enriched),
        author=_author_public(author),
        status=article.status,
        published_at=article.published_at,
        view_count=article.view_count,
        comment_count=article.comment_count,
        mentioned_user_ids=list(article.mentioned_user_ids or []),
        reaction_counts=dict(article.reaction_counts or {}),
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


def build_article_public(article: Article, author: User) -> ArticlePublic:
    """Public builder so sibling modules (``users``) can reuse the mapping."""
    return ArticlePublic(
        id=article.id,
        slug=article.slug,
        topic_id=article.topic_id,
        title=article.title,
        summary=article.summary,
        author=_author_public(author),
        status=article.status,
        published_at=article.published_at,
        view_count=article.view_count,
        comment_count=article.comment_count,
        reaction_counts=dict(article.reaction_counts or {}),
    )


# Backwards-compatible private alias — already used in this module.
_article_public = build_article_public


async def _revision_read(
    revision: ArticleRevision, editor: User, db: AsyncSession
) -> ArticleRevisionRead:
    enriched = await enrich_content(revision.content, db)
    return ArticleRevisionRead(
        id=revision.id,
        revision=revision.revision,
        editor=_author_public(editor),
        editor_role_at_edit=revision.editor_role_at_edit,
        title=revision.title,
        content=DocSchema.model_validate(enriched),
        edit_reason=revision.edit_reason,
        created_at=revision.created_at,
    )


# ---------------------------------------------------------------------------
# Create / list per topic
# ---------------------------------------------------------------------------


@router.post(
    "/topics/{topic_id}/articles",
    response_model=ArticleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft article inside a topic (authed users)",
)
async def create_article(
    topic_id: UUID,
    payload: ArticleCreate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ArticleRead:
    try:
        article, author = await svc.create_article(actor, topic_id, payload)
    except TopicNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        ) from exc
    except TopicLocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Topic is locked"
        ) from exc
    except SlugConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return await _article_read(article, author, db)


@router.get(
    "/topics/{topic_id}/articles",
    response_model=list[ArticlePublic],
    summary="List articles in a topic (defaults to published only)",
)
async def list_articles_for_topic(
    topic_id: UUID,
    svc: Annotated[ArticleService, Depends(get_article_service)],
    article_status: Annotated[ArticleStatus | None, Query(alias="status")] = (
        ArticleStatus.PUBLISHED
    ),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ArticlePublic]:
    pairs = await svc.list_for_topic(
        topic_id, status=article_status, limit=limit, offset=offset
    )
    return [_article_public(article, author) for article, author in pairs]


@router.get(
    "/sections/{section_slug}/topics/{topic_slug}/articles",
    response_model=list[ArticlePublic],
    summary=(
        "List articles in a topic by (section_slug, topic_slug) "
        "(defaults to published only)"
    ),
)
async def list_articles_for_topic_by_slug(
    section_slug: str,
    topic_slug: str,
    forum_svc: Annotated[ForumService, Depends(get_forum_service)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    article_status: Annotated[ArticleStatus | None, Query(alias="status")] = (
        ArticleStatus.PUBLISHED
    ),
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ArticlePublic]:
    """Slug-based mirror of :func:`list_articles_for_topic`.

    Resolves ``(section_slug, topic_slug)`` to a topic id, then delegates
    to the existing service method. Section/topic 404s are surfaced
    distinctly so the frontend can decide whether to retry, redirect, or
    show a section-not-found page.
    """
    try:
        topic, _author = await forum_svc.get_topic_by_slug(
            section_slug, topic_slug
        )
    except SectionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Section not found"
        ) from exc
    except TopicNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        ) from exc
    pairs = await svc.list_for_topic(
        topic.id, status=article_status, limit=limit, offset=offset
    )
    return [_article_public(article, author) for article, author in pairs]


# ---------------------------------------------------------------------------
# Article get / patch / publish
# ---------------------------------------------------------------------------


@router.get(
    "/articles/{article_id}",
    response_model=ArticleRead,
    summary="Fetch an article (drafts hidden from non-authors)",
)
async def get_article(
    article_id: UUID,
    viewer: Annotated[User | None, Depends(get_optional_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ArticleRead:
    try:
        article, author = await svc.get_for_viewer(article_id, viewer)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    return await _article_read(article, author, db)


@router.patch(
    "/articles/{article_id}",
    response_model=ArticleRead,
    summary="Edit an article (author or moderator/admin with reason)",
)
async def patch_article(
    article_id: UUID,
    payload: ArticleUpdate,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ArticleRead:
    try:
        article, author = await svc.edit_article(actor, article_id, payload)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except MissingEditReason as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ArticleNotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return await _article_read(article, author, db)


@router.post(
    "/articles/{article_id}/publish",
    response_model=ArticleRead,
    summary="Move article to ``published`` (author or moderator/admin)",
)
async def publish_article(
    article_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ArticleRead:
    try:
        article, author = await svc.publish_article(actor, article_id)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except ArticleNotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return await _article_read(article, author, db)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@router.delete(
    "/articles/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an article (author/mod/admin → soft; admin + hard=true → hard)",
)
async def delete_article(
    article_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    hard: bool = False,
) -> None:
    """Delete an article.

    - Author / moderator / admin → soft delete (``status=archived``).
    - ``hard=true`` is admin-only — the row is removed and child
      messages / revisions / reactions / saved cascade.
    """
    try:
        await svc.delete_article(actor, article_id, hard=hard)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except (ArticleNotEditable, InsufficientRole) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------


@router.get(
    "/articles/{article_id}/revisions",
    response_model=list[ArticleRevisionRead],
    summary="List article revisions (author or moderator/admin)",
)
async def list_revisions(
    article_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[ArticleRevisionRead]:
    try:
        pairs = await svc.list_revisions(article_id, actor)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    except ArticleNotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return [await _revision_read(rev, editor, db) for rev, editor in pairs]


@router.get(
    "/articles/{article_id}/revisions/{revision}",
    response_model=ArticleRevisionRead,
    summary="Fetch a single revision (author or moderator/admin)",
)
async def get_revision(
    article_id: UUID,
    revision: int,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ArticleRevisionRead:
    try:
        rev, editor = await svc.get_revision(article_id, revision, actor)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found"
        ) from exc
    except ArticleNotEditable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return await _revision_read(rev, editor, db)


# ---------------------------------------------------------------------------
# Me / drafts
# ---------------------------------------------------------------------------


@router.get(
    "/me/drafts",
    response_model=list[ArticlePublic],
    summary="List the current user's drafts",
)
async def list_my_drafts(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ArticleService, Depends(get_article_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ArticlePublic]:
    pairs = await svc.list_drafts_for_user(actor.id, limit=limit, offset=offset)
    return [_article_public(article, author) for article, author in pairs]


__all__ = ["build_article_public", "router"]
