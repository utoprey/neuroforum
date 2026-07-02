"""Service-layer tests for the ``imports`` module (arXiv Level 1)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import ArticleStatus
from app.modules.articles.repository import ArticleRepository
from app.modules.articles.service import ArticleService
from app.modules.forum.exceptions import InsufficientRole
from app.modules.forum.repository import ForumRepository
from app.modules.forum.schemas import SectionCreate, TopicCreate
from app.modules.forum.service import ForumService
from app.modules.imports.exceptions import DuplicateImport, InvalidArxivId
from app.modules.imports.models import ExternalSource
from app.modules.imports.repository import ExternalSourceRepository
from app.modules.imports.schemas import ArxivImportRequest
from app.modules.imports.service import ImportService
from app.modules.users.models import Role, User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserCreate
from app.modules.users.service import UserService

ArxivClient = Callable[[str], Awaitable[dict[str, Any]]]


def _make_arxiv_meta(arxiv_id: str = "2401.12345") -> dict[str, Any]:
    return {
        "id": f"{arxiv_id}v2",
        "title": "Cortical Dynamics via Deep State Space Models",
        "authors": [
            {"name": "Ada Lovelace", "affiliation": "Cambridge"},
            {"name": "Alan Turing", "affiliation": None},
        ],
        "summary": "We present a novel approach to cortical dynamics.",
        "categories": ["q-bio.NC", "cs.LG"],
        "primary_category": "q-bio.NC",
        "published": datetime(2024, 1, 23, 17, 9, 32, tzinfo=UTC),
        "updated": datetime(2024, 2, 1, 12, 0, 0, tzinfo=UTC),
        "doi": "10.1234/example",
        "journal_ref": "Nature Neuroscience 27, 555-560 (2024)",
        "pdf_url": f"http://arxiv.org/pdf/{arxiv_id}v2",
        "source_url": f"http://arxiv.org/abs/{arxiv_id}v2",
    }


def _make_fake_client(meta: dict[str, Any]) -> ArxivClient:
    async def _client(arxiv_id: str) -> dict[str, Any]:
        return meta

    return _client


@pytest.fixture
def users_svc(db_session: AsyncSession) -> UserService:
    return UserService(UserRepository(db_session), db_session)


@pytest.fixture
def forum_svc(db_session: AsyncSession) -> ForumService:
    return ForumService(ForumRepository(db_session), db_session)


@pytest.fixture
def articles_svc(db_session: AsyncSession) -> ArticleService:
    return ArticleService(
        ArticleRepository(db_session), ForumRepository(db_session), db_session
    )


@pytest.fixture
def imports_svc(
    db_session: AsyncSession, articles_svc: ArticleService
) -> ImportService:
    return ImportService(
        ExternalSourceRepository(db_session),
        articles_svc,
        db_session,
        arxiv_client=_make_fake_client(_make_arxiv_meta()),
    )


async def _make_user(
    users_svc: UserService,
    db_session: AsyncSession,
    *,
    username: str,
    role: Role = Role.USER,
) -> User:
    user = await users_svc.create_user(
        UserCreate(
            username=username,
            email=f"{username}@x.io",
            password=SecretStr("hunter22!"),
        )
    )
    if role is not Role.USER:
        await db_session.execute(
            text("UPDATE users SET role = :r WHERE id = :id"),
            {"r": role.value, "id": user.id},
        )
        await db_session.flush()
        await db_session.refresh(user)
    return user


async def _make_topic(
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
    *,
    section_slug: str,
) -> tuple[User, User, uuid.UUID]:
    admin = await _make_user(
        users_svc, db_session, username=f"adm_{section_slug}", role=Role.ADMIN
    )
    mod = await _make_user(
        users_svc, db_session, username=f"mod_{section_slug}", role=Role.MODERATOR
    )
    await forum_svc.create_section(
        admin, SectionCreate(title=section_slug.upper(), slug=section_slug)
    )
    topic, _ = await forum_svc.create_topic(
        admin, section_slug, TopicCreate(title="Topic")
    )
    return admin, mod, topic.id


# ---------------------------------------------------------------------------
# preview_arxiv
# ---------------------------------------------------------------------------


async def test_preview_arxiv_happy_path(
    imports_svc: ImportService,
) -> None:
    preview = await imports_svc.preview_arxiv("https://arxiv.org/abs/2401.12345v2")
    assert preview.arxiv_id == "2401.12345v2"
    assert "Cortical" in preview.title
    assert preview.authors == ["Ada Lovelace", "Alan Turing"]
    assert preview.primary_category == "q-bio.NC"
    assert preview.doi == "10.1234/example"
    assert preview.pdf_url == "http://arxiv.org/pdf/2401.12345v2"


async def test_preview_rejects_bad_id(imports_svc: ImportService) -> None:
    with pytest.raises(InvalidArxivId):
        await imports_svc.preview_arxiv("not an arxiv id")


# ---------------------------------------------------------------------------
# import_arxiv
# ---------------------------------------------------------------------------


async def test_import_arxiv_creates_draft_article(
    imports_svc: ImportService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, mod, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="i1"
    )
    article, _author, source = await imports_svc.import_arxiv(
        mod,
        ArxivImportRequest(url_or_id="2401.12345", topic_id=topic_id),
    )
    assert article.status == ArticleStatus.DRAFT
    assert "Cortical" in article.title
    assert source.source == ExternalSource.ARXIV
    assert source.external_id == "2401.12345"
    assert source.article_id == article.id
    assert source.pdf_url == "http://arxiv.org/pdf/2401.12345v2"
    # Doc has at least a heading + abstract + auto-imported note.
    content = article.content
    assert isinstance(content, dict)
    types = [b.get("type") for b in content.get("content", [])]
    assert "heading" in types
    assert "callout" in types


async def test_import_arxiv_requires_moderator(
    imports_svc: ImportService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, _mod, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="i2"
    )
    user = await _make_user(users_svc, db_session, username="plain_user_i2")
    with pytest.raises(InsufficientRole):
        await imports_svc.import_arxiv(
            user,
            ArxivImportRequest(url_or_id="2401.12345", topic_id=topic_id),
        )


async def test_import_arxiv_duplicate(
    imports_svc: ImportService,
    forum_svc: ForumService,
    users_svc: UserService,
    db_session: AsyncSession,
) -> None:
    _admin, mod, topic_id = await _make_topic(
        forum_svc, users_svc, db_session, section_slug="i3"
    )
    article, _, _ = await imports_svc.import_arxiv(
        mod,
        ArxivImportRequest(url_or_id="2401.12345", topic_id=topic_id),
    )
    with pytest.raises(DuplicateImport) as exc_info:
        await imports_svc.import_arxiv(
            mod,
            ArxivImportRequest(url_or_id="2401.12345", topic_id=topic_id),
        )
    assert exc_info.value.article_id == article.id
