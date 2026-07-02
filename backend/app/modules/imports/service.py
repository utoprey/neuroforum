"""Business logic for the ``imports`` module (arXiv Level 1)."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.articles.models import Article
from app.modules.articles.schemas import ArticleCreate
from app.modules.articles.service import ArticleService
from app.modules.content.schemas import DocSchema
from app.modules.content.utils import validate_doc
from app.modules.imports.arxiv_client import fetch_arxiv
from app.modules.imports.exceptions import (
    DuplicateImport,
    InvalidArxivId,
)
from app.modules.imports.models import ExternalSource, ExternalSourceRecord
from app.modules.imports.repository import ExternalSourceRepository
from app.modules.imports.schemas import (
    ArxivImportRequest,
    ArxivPreview,
)
from app.modules.users.models import Role, User

ArxivClient = Callable[[str], Awaitable[dict[str, Any]]]

# arXiv id formats:
#  - New: ``2401.12345`` or ``2401.12345v2`` (YYMM.NNNNN[vN])
#  - Old: ``hep-th/9901001`` or ``math.AG/0703001`` (CATEGORY/YYMMDDD)
_NEW_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/)?"
    r"(?P<id>\d{4}\.\d{4,5})"
    r"(?P<ver>v\d+)?",
    re.IGNORECASE,
)
_OLD_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/)?"
    r"(?P<id>[a-z\-]+(?:\.[A-Z]+)?/\d{7})"
    r"(?P<ver>v\d+)?",
    re.IGNORECASE,
)

_MOD_OR_ADMIN: frozenset[Role] = frozenset({Role.MODERATOR, Role.ADMIN})


class ImportService:
    """Parses arXiv ids, fetches metadata, and creates a draft article."""

    def __init__(
        self,
        repo: ExternalSourceRepository,
        article_service: ArticleService,
        db: AsyncSession,
        arxiv_client: ArxivClient | None = None,
    ) -> None:
        self._repo = repo
        self._articles = article_service
        self._db = db
        # DI for tests — when None we hit the real export.arxiv.org.
        self._arxiv: ArxivClient = arxiv_client or fetch_arxiv

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_arxiv_id(url_or_id: str) -> tuple[str, str | None]:
        """Return ``(id, version)`` or raise :class:`InvalidArxivId`."""
        candidate = url_or_id.strip()
        # Strip a trailing ``.pdf`` so ``…/abs/2401.12345.pdf`` works.
        if candidate.lower().endswith(".pdf"):
            candidate = candidate[:-4]
        for pat in (_NEW_ID_RE, _OLD_ID_RE):
            m = pat.search(candidate)
            if m:
                return m.group("id"), m.group("ver")
        raise InvalidArxivId(url_or_id)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    async def preview_arxiv(self, url_or_id: str) -> ArxivPreview:
        arxiv_id, version = self.parse_arxiv_id(url_or_id)
        full_id = f"{arxiv_id}{version}" if version else arxiv_id
        meta = await self._arxiv(full_id)
        return ArxivPreview(
            arxiv_id=str(meta.get("id") or arxiv_id),
            title=str(meta.get("title") or ""),
            authors=[a["name"] for a in meta.get("authors") or [] if a.get("name")],
            abstract=str(meta.get("summary") or ""),
            categories=list(meta.get("categories") or []),
            primary_category=meta.get("primary_category"),
            published_at=meta.get("published"),
            doi=meta.get("doi"),
            pdf_url=meta.get("pdf_url"),
            source_url=str(meta.get("source_url") or f"https://arxiv.org/abs/{arxiv_id}"),
        )

    # ------------------------------------------------------------------
    # Existing-import check
    # ------------------------------------------------------------------

    async def check_existing(
        self, source: ExternalSource, external_id: str
    ) -> ExternalSourceRecord | None:
        return await self._repo.get_by_source_and_id(source, external_id)

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    async def import_arxiv(
        self, actor: User, payload: ArxivImportRequest
    ) -> tuple[Article, User, ExternalSourceRecord]:
        if actor.role not in _MOD_OR_ADMIN:
            # Routes layer can wrap this into a 403 — service stays decoupled
            # from HTTP, but we reuse the existing role-policy expression.
            from app.modules.forum.exceptions import InsufficientRole

            raise InsufficientRole("Only moderator/admin can import arXiv articles")

        arxiv_id, version = self.parse_arxiv_id(payload.url_or_id)
        existing = await self._repo.get_by_source_and_id(ExternalSource.ARXIV, arxiv_id)
        if existing is not None:
            raise DuplicateImport(
                f"arXiv:{arxiv_id} already imported",
                article_id=existing.article_id,
            )

        full_id = f"{arxiv_id}{version}" if version else arxiv_id
        meta = await self._arxiv(full_id)

        doc = self._build_doc(arxiv_id, meta)
        # Validate the doc before handing it to ArticleService — catches
        # any schema regression in ``_build_doc`` early.
        validate_doc(doc.model_dump(mode="json"))

        title = str(meta.get("title") or f"arXiv:{arxiv_id}")
        abstract = str(meta.get("summary") or "")
        summary = abstract[:280] if abstract else None

        article, _author = await self._articles.create_article(
            actor,
            payload.topic_id,
            ArticleCreate(title=title, summary=summary, content=doc),
        )

        record = ExternalSourceRecord(
            article_id=article.id,
            source=ExternalSource.ARXIV,
            external_id=arxiv_id,
            version=version,
            source_url=str(
                meta.get("source_url") or f"https://arxiv.org/abs/{arxiv_id}"
            ),
            pdf_url=meta.get("pdf_url"),
            metadata_={
                "authors": meta.get("authors") or [],
                "categories": meta.get("categories") or [],
                "primary_category": meta.get("primary_category"),
                "doi": meta.get("doi"),
                "journal_ref": meta.get("journal_ref"),
            },
            fetched_at=datetime.now(UTC),
            published_at=meta.get("published"),
        )
        await self._repo.add(record)
        return article, actor, record

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_doc(arxiv_id: str, meta: dict[str, Any]) -> DocSchema:
        """Assemble a ProseMirror ``DocSchema`` from arXiv metadata."""
        title = str(meta.get("title") or f"arXiv:{arxiv_id}")
        authors = [a["name"] for a in meta.get("authors") or [] if a.get("name")]
        abstract = str(meta.get("summary") or "")
        categories = list(meta.get("categories") or [])
        doi = meta.get("doi")
        pdf_url = meta.get("pdf_url")

        author_line = "by " + ", ".join(authors) if authors else ""
        cat_line = "Categories: " + ", ".join(categories) if categories else ""
        doi_line = f"DOI: {doi}" if doi else ""
        meta_text = "\n".join(line for line in (cat_line, doi_line) if line)

        blocks: list[dict[str, Any]] = []
        # 1. heading level 1 — title
        blocks.append(
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": title}],
            }
        )
        # 2. authors paragraph in italics
        if author_line:
            blocks.append(
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": author_line,
                            "marks": [{"type": "italic"}],
                        }
                    ],
                }
            )
        # 3. callout info: categories + DOI
        if meta_text:
            blocks.append(
                {
                    "type": "callout",
                    "attrs": {"kind": "info", "icon": ""},
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": meta_text}],
                        }
                    ],
                }
            )
        # 4. heading 2 — Abstract
        blocks.append(
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Abstract"}],
            }
        )
        # 5. abstract paragraph
        blocks.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": abstract}],
            }
        )
        # 6. callout note: auto-imported marker
        blocks.append(
            {
                "type": "callout",
                "attrs": {"kind": "note", "icon": ""},
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": f"[Auto-imported from arXiv:{arxiv_id}]",
                            }
                        ],
                    }
                ],
            }
        )
        # 7. link block to PDF, when available
        if pdf_url:
            blocks.append(
                {
                    "type": "link",
                    "attrs": {"href": pdf_url, "title": "PDF on arXiv"},
                }
            )

        return DocSchema.model_validate({"type": "doc", "content": blocks})


__all__ = ["ArxivClient", "ImportService"]
