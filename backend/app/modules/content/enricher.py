"""Resolve ``attachment_id`` → public ``src`` URL for media blocks.

Frontend renders ``image`` / ``gif`` / ``video`` blocks from the ``src``
attribute. The DB stores ``attachment_id`` (UUID into ``attachments``) so
the URL stays stable across storage backends. This module is the bridge:
walk a ProseMirror doc, batch-load every referenced attachment, and patch
``attrs.src`` in place for callers that need a render-ready document.

Used by ``articles`` / ``messages`` / ``dm`` route layers right before
emitting their respective ``*Read`` schemas.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.attachments.models import Attachment

# Block ``type``s that carry an ``attachment_id`` / ``src`` in their attrs.
MEDIA_TYPES: frozenset[str] = frozenset({"image", "gif", "video"})


# A neutral 1x1 transparent fallback when seed data references a bucket
# pattern we don't know how to resolve. Never returned for real MinIO
# uploads — those always resolve through ``MINIO_PUBLIC_BASE_URL``.
_FALLBACK_VIDEO_URL = (
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"
)


def attachment_to_src(att: Attachment) -> str:
    """Build a public URL for ``att`` based on its bucket / object-key conventions.

    The ``external`` bucket is a synthetic marker used by the seed script
    (and any future external-source import) so we don't need a real MinIO
    upload to render images. Recognised object-key prefixes:

    - ``picsum/{seed}/{w}/{h}`` → ``https://picsum.photos/seed/{seed}/{w}/{h}``
    - ``giphy/{seed}.gif``      → mem-style picsum image (giphy can't be
      keyed by seed, so we fall back to a picsum-derived URL)
    - ``sample-video/{n}.mp4``  → Big Buck Bunny on the Google CDN

    Anything else under ``external`` returns a debug placeholder URL —
    rendering will fail visibly, which is what we want in dev.

    For real MinIO buckets we just concatenate ``MINIO_PUBLIC_BASE_URL``
    with the bucket + object key. The presigned-GET flow used by the
    upload helper is intentionally bypassed here because read URLs for
    public buckets don't need signing — and unsigned URLs render in
    ``<img>`` tags without CORS preflight overhead.
    """
    if att.bucket == "external":
        key = att.object_key
        if key.startswith("picsum/"):
            parts = key.split("/")
            if len(parts) >= 4:
                _, seed, w, h = parts[:4]
                return f"https://picsum.photos/seed/{seed}/{w}/{h}"
        if key.startswith("giphy/"):
            seed = key.removeprefix("giphy/").removesuffix(".gif")
            return f"https://picsum.photos/seed/gif-{seed}/600/400"
        if key.startswith("sample-video/"):
            return _FALLBACK_VIDEO_URL
        return f"https://placeholder.invalid/{key}"
    base = settings.MINIO_PUBLIC_BASE_URL or f"http://{settings.MINIO_ENDPOINT}"
    return f"{base.rstrip('/')}/{att.bucket}/{att.object_key}"


def _collect_attachment_ids(node: dict[str, Any], into: set[UUID]) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") in MEDIA_TYPES:
        attrs = node.get("attrs") or {}
        aid = attrs.get("attachment_id")
        if aid and not attrs.get("src"):
            try:
                into.add(UUID(str(aid)))
            except (ValueError, TypeError):
                # Malformed id in stored content — skip silently rather
                # than 500 the request. The render will just lack a src.
                pass
    for child in node.get("content", []) or []:
        _collect_attachment_ids(child, into)


def _patch_src_in_place(
    node: dict[str, Any], attachments: dict[UUID, Attachment]
) -> None:
    if not isinstance(node, dict):
        return
    if node.get("type") in MEDIA_TYPES:
        attrs = node.get("attrs") or {}
        aid = attrs.get("attachment_id")
        if aid and not attrs.get("src"):
            try:
                att = attachments.get(UUID(str(aid)))
            except (ValueError, TypeError):
                att = None
            if att is not None:
                attrs["src"] = attachment_to_src(att)
                node["attrs"] = attrs
    for child in node.get("content", []) or []:
        _patch_src_in_place(child, attachments)


async def enrich_content(
    content: dict[str, Any] | None, db: AsyncSession
) -> dict[str, Any] | None:
    """Return a copy of ``content`` with media-block ``src`` populated.

    - Walks every block (recurses through ``content`` children — lists,
      callouts, quotes).
    - Skips blocks that already carry ``src`` (set client-side or by seed).
    - Batches the attachment lookup into a single ``SELECT … WHERE id IN``.
    - Never mutates the input dict.

    ``None`` is passed through unchanged so callers can chain on
    soft-deleted message content (which is ``None`` in the schema).
    """
    if content is None:
        return None
    result = copy.deepcopy(content)
    ids: set[UUID] = set()
    _collect_attachment_ids(result, ids)
    if not ids:
        return result
    rows = await db.execute(
        select(Attachment).where(Attachment.id.in_(ids))
    )
    attachments: dict[UUID, Attachment] = {a.id: a for a in rows.scalars()}
    if not attachments:
        return result
    _patch_src_in_place(result, attachments)
    return result


__all__ = [
    "MEDIA_TYPES",
    "attachment_to_src",
    "enrich_content",
]
