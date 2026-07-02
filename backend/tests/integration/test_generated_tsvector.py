"""Verify the production Alembic migration installs GENERATED tsvector columns.

This test requires the Alembic-built schema (``TESTS_USE_ALEMBIC=1``)
because ``Base.metadata.create_all`` only creates plain TSVECTOR columns
with an empty default — the GENERATED-ALWAYS-AS-STORED behaviour is added
manually in the initial schema migration. See ``backend/alembic/versions/*``
and ``backend/app/modules/articles/models.py`` for context.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [
    pytest.mark.requires_alembic,
    pytest.mark.skipif(
        os.environ.get("TESTS_USE_ALEMBIC", "").lower() not in {"1", "true", "yes"},
        reason="GENERATED tsvector only present when TESTS_USE_ALEMBIC=1",
    ),
]


async def test_articles_content_tsv_is_generated(db_session: AsyncSession) -> None:
    """Insert a user + topic + article, then check that ``content_tsv``
    auto-populates from ``content_text`` via the GENERATED column."""
    user_id = uuid.uuid4()
    section_id = uuid.uuid4()
    topic_id = uuid.uuid4()
    article_id = uuid.uuid4()

    await db_session.execute(
        text(
            "INSERT INTO users (id, username, email, password_hash, role, is_active)"
            " VALUES (:id, :u, :e, '', 'user', TRUE)"
        ),
        {"id": user_id, "u": f"tsvuser_{user_id.hex[:6]}", "e": f"{user_id.hex[:6]}@x.io"},
    )
    await db_session.execute(
        text(
            "INSERT INTO sections (id, slug, title) "
            "VALUES (:id, :slug, 'TSV')"
        ),
        {"id": section_id, "slug": f"tsv_{section_id.hex[:6]}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO topics (id, section_id, slug, title, created_by) "
            "VALUES (:id, :sid, :slug, 'T', :uid)"
        ),
        {
            "id": topic_id,
            "sid": section_id,
            "slug": f"tsvt_{topic_id.hex[:6]}",
            "uid": user_id,
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO articles (id, topic_id, slug, title, content, "
            "content_text, author_id, status) "
            "VALUES (:id, :tid, :slug, 'A', '{}'::jsonb, "
            ":txt, :uid, 'published')"
        ),
        {
            "id": article_id,
            "tid": topic_id,
            "slug": f"tsvart_{article_id.hex[:6]}",
            "txt": "нейровизуализация и фМРТ",
            "uid": user_id,
        },
    )
    await db_session.commit()

    # content_tsv is GENERATED — it should be non-empty and match the FTS query.
    result = await db_session.execute(
        text(
            "SELECT content_tsv IS NOT NULL AND content_tsv <> ''::tsvector "
            "FROM articles WHERE id = :id"
        ),
        {"id": article_id},
    )
    assert result.scalar_one() is True

    # And the FTS query against 'russian' config returns the row.
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM articles "
            "WHERE id = :id AND content_tsv @@ to_tsquery('russian', :q)"
        ),
        {"id": article_id, "q": "нейровизуализация"},
    )
    assert result.scalar_one() == 1
