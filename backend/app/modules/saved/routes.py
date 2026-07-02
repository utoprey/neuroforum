"""HTTP routes for the ``saved`` module."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.modules.articles.models import Article
from app.modules.articles.schemas import ArticlePublic
from app.modules.saved.deps import get_saved_service
from app.modules.saved.exceptions import ArticleNotFound
from app.modules.saved.schemas import SavedArticleRead
from app.modules.saved.service import SavedService
from app.modules.users.deps import get_current_user
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(tags=["saved"])


def _author_public(author: User) -> UserPublic:
    return UserPublic(
        id=author.id,
        username=author.username,
        display_name=(author.profile.display_name if author.profile else None),
        avatar_url=(author.profile.avatar_url if author.profile else None),
        role=author.role,
    )


def _article_public(article: Article, author: User) -> ArticlePublic:
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


@router.post(
    "/me/saved/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Bookmark an article (idempotent — double-save is a no-op)",
)
async def save_article(
    article_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[SavedService, Depends(get_saved_service)],
) -> Response:
    try:
        await svc.save(actor, article_id)
    except ArticleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Article not found"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/me/saved/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Remove an article from the user's bookmarks (idempotent)",
)
async def unsave_article(
    article_id: UUID,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[SavedService, Depends(get_saved_service)],
) -> Response:
    await svc.unsave(actor, article_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me/saved",
    response_model=list[SavedArticleRead],
    summary="List the current user's saved articles, newest first",
)
async def list_my_saved(
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[SavedService, Depends(get_saved_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SavedArticleRead]:
    triples = await svc.list_my_saved(actor, limit=limit, offset=offset)
    return [
        SavedArticleRead(
            article_id=saved.article_id,
            saved_at=saved.saved_at,
            article=_article_public(article, author),
        )
        for saved, article, author in triples
    ]


__all__ = ["router"]
