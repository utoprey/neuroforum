"""HTTP routes for the ``imports`` module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.modules.articles.models import Article
from app.modules.articles.schemas import ArticleRead
from app.modules.content.schemas import DocSchema
from app.modules.forum.exceptions import InsufficientRole, TopicLocked, TopicNotFound
from app.modules.imports.deps import (
    get_external_source_repository,
    get_import_service,
)
from app.modules.imports.exceptions import (
    ArxivFetchFailed,
    ArxivNotFound,
    DuplicateImport,
    InvalidArxivId,
)
from app.modules.imports.models import ExternalSource, ExternalSourceRecord
from app.modules.imports.repository import ExternalSourceRepository
from app.modules.imports.schemas import (
    ArxivImportRequest,
    ArxivImportResponse,
    ArxivPreview,
    ExternalSourceRead,
)
from app.modules.imports.service import ImportService
from app.modules.users.deps import get_current_user
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(prefix="/imports", tags=["imports"])


def _author_public(author: User) -> UserPublic:
    return UserPublic(
        id=author.id,
        username=author.username,
        display_name=(author.profile.display_name if author.profile else None),
        avatar_url=(author.profile.avatar_url if author.profile else None),
        role=author.role,
    )


def _article_read(article: Article, author: User) -> ArticleRead:
    return ArticleRead(
        id=article.id,
        topic_id=article.topic_id,
        slug=article.slug,
        title=article.title,
        summary=article.summary,
        content=DocSchema.model_validate(article.content),
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


def _source_read(record: ExternalSourceRecord) -> ExternalSourceRead:
    return ExternalSourceRead(
        id=record.id,
        article_id=record.article_id,
        source=record.source,
        external_id=record.external_id,
        version=record.version,
        source_url=record.source_url,
        pdf_url=record.pdf_url,
        metadata_=dict(record.metadata_ or {}),
        fetched_at=record.fetched_at,
        published_at=record.published_at,
    )


@router.get(
    "/arxiv/preview",
    response_model=ArxivPreview,
    summary="Preview arXiv metadata without persisting anything",
)
async def preview_arxiv(
    svc: Annotated[ImportService, Depends(get_import_service)],
    _user: Annotated[User, Depends(get_current_user)],
    id: Annotated[str, Query(min_length=1, alias="id")] = "",
) -> ArxivPreview:
    try:
        return await svc.preview_arxiv(id)
    except InvalidArxivId as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse arXiv id from {id!r}",
        ) from exc
    except ArxivNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"arXiv id not found: {id}"
        ) from exc
    except ArxivFetchFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc


@router.post(
    "/arxiv",
    response_model=ArxivImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import an arXiv paper as a draft article (moderator/admin only)",
)
async def import_arxiv(
    payload: ArxivImportRequest,
    actor: Annotated[User, Depends(get_current_user)],
    svc: Annotated[ImportService, Depends(get_import_service)],
) -> ArxivImportResponse:
    try:
        article, author, record = await svc.import_arxiv(actor, payload)
    except InsufficientRole as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except InvalidArxivId as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse arXiv id from {payload.url_or_id!r}",
        ) from exc
    except DuplicateImport as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "article_id": str(exc.article_id)},
        ) from exc
    except TopicNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found"
        ) from exc
    except TopicLocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Topic is locked"
        ) from exc
    except ArxivNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="arXiv id not found"
        ) from exc
    except ArxivFetchFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return ArxivImportResponse(
        article=_article_read(article, author),
        source=_source_read(record),
    )


@router.get(
    "/sources",
    response_model=ExternalSourceRead,
    summary="Lookup an external_source row by (source, external_id)",
)
async def get_external_source(
    repo: Annotated[
        ExternalSourceRepository, Depends(get_external_source_repository)
    ],
    source: Annotated[ExternalSource, Query()],
    id: Annotated[str, Query(min_length=1, alias="id")] = "",
) -> ExternalSourceRead:
    record = await repo.get_by_source_and_id(source, id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No external source for {source.value}:{id}",
        )
    return _source_read(record)


__all__ = ["router"]
