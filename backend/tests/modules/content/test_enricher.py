"""Tests for ``app.modules.content.enricher``.

Covers the three resolver paths (external picsum, external giphy, real
MinIO bucket) plus the walk semantics: deep nesting, no mutation of the
input, and missing-attachment graceful fallthrough.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.attachments.models import (
    Attachment,
    AttachmentKind,
    ProcessingStatus,
)
from app.modules.content.enricher import attachment_to_src, enrich_content
from app.modules.users.models import Role, User


async def _make_user(db: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        username=f"user_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex[:8]}@test.local",
        password_hash="x",
        role=Role.USER,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_attachment(
    db: AsyncSession,
    user: User,
    *,
    bucket: str,
    object_key: str,
    kind: AttachmentKind = AttachmentKind.IMAGE,
    mime_type: str = "image/jpeg",
) -> Attachment:
    att = Attachment(
        id=uuid.uuid4(),
        uploader_id=user.id,
        kind=kind,
        bucket=bucket,
        object_key=object_key,
        mime_type=mime_type,
        size_bytes=1,
        processing_status=ProcessingStatus.READY,
    )
    db.add(att)
    await db.flush()
    return att


# ---------------------------------------------------------------------------
# attachment_to_src
# ---------------------------------------------------------------------------


def test_attachment_to_src_picsum() -> None:
    att = Attachment(
        id=uuid.uuid4(),
        uploader_id=uuid.uuid4(),
        kind=AttachmentKind.IMAGE,
        bucket="external",
        object_key="picsum/predcoding/800/450",
        mime_type="image/jpeg",
        size_bytes=1,
    )
    assert attachment_to_src(att) == "https://picsum.photos/seed/predcoding/800/450"


def test_attachment_to_src_giphy_falls_back_to_picsum() -> None:
    att = Attachment(
        id=uuid.uuid4(),
        uploader_id=uuid.uuid4(),
        kind=AttachmentKind.GIF,
        bucket="external",
        object_key="giphy/flood-foo.gif",
        mime_type="image/gif",
        size_bytes=1,
    )
    assert attachment_to_src(att).startswith("https://picsum.photos/seed/gif-")


def test_attachment_to_src_real_minio_bucket() -> None:
    att = Attachment(
        id=uuid.uuid4(),
        uploader_id=uuid.uuid4(),
        kind=AttachmentKind.IMAGE,
        bucket="forum-media",
        object_key="2025/06/abc.jpg",
        mime_type="image/jpeg",
        size_bytes=1,
    )
    url = attachment_to_src(att)
    assert url.endswith("/forum-media/2025/06/abc.jpg")


# ---------------------------------------------------------------------------
# enrich_content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrich_content_populates_src_for_image_block(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    att = await _make_attachment(
        db_session, user, bucket="external", object_key="picsum/foo/800/450"
    )
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"attachment_id": str(att.id), "alt": "x", "caption": ""},
            }
        ],
    }
    enriched = await enrich_content(raw, db_session)
    assert enriched is not None
    assert (
        enriched["content"][0]["attrs"]["src"]
        == "https://picsum.photos/seed/foo/800/450"
    )
    # Original input must not be mutated.
    assert "src" not in raw["content"][0]["attrs"]


@pytest.mark.asyncio
async def test_enrich_content_skips_when_src_already_set(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    att = await _make_attachment(
        db_session, user, bucket="external", object_key="picsum/bar/800/450"
    )
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {
                    "attachment_id": str(att.id),
                    "src": "https://example.com/already-set.png",
                    "alt": "",
                    "caption": "",
                },
            }
        ],
    }
    enriched = await enrich_content(raw, db_session)
    assert enriched is not None
    assert (
        enriched["content"][0]["attrs"]["src"]
        == "https://example.com/already-set.png"
    )


@pytest.mark.asyncio
async def test_enrich_content_recurses_into_callouts_and_lists(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session)
    att = await _make_attachment(
        db_session, user, bucket="external", object_key="picsum/nested/400/300"
    )
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "callout",
                "attrs": {"kind": "info", "icon": ""},
                "content": [
                    {
                        "type": "image",
                        "attrs": {
                            "attachment_id": str(att.id),
                            "alt": "",
                            "caption": "",
                        },
                    }
                ],
            }
        ],
    }
    enriched = await enrich_content(raw, db_session)
    assert enriched is not None
    inner = enriched["content"][0]["content"][0]
    assert inner["attrs"]["src"] == "https://picsum.photos/seed/nested/400/300"


@pytest.mark.asyncio
async def test_enrich_content_handles_missing_attachment(
    db_session: AsyncSession,
) -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {
                    "attachment_id": str(uuid.uuid4()),
                    "alt": "",
                    "caption": "",
                },
            }
        ],
    }
    enriched = await enrich_content(raw, db_session)
    assert enriched is not None
    # No attachment exists → src stays absent. Render falls back to the
    # "image missing" placeholder, no crash.
    assert "src" not in enriched["content"][0]["attrs"]


@pytest.mark.asyncio
async def test_enrich_content_none_passthrough(db_session: AsyncSession) -> None:
    assert await enrich_content(None, db_session) is None


@pytest.mark.asyncio
async def test_enrich_content_no_media_blocks(db_session: AsyncSession) -> None:
    raw = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}
        ],
    }
    enriched = await enrich_content(raw, db_session)
    assert enriched == raw
    assert enriched is not raw  # deep-copied
