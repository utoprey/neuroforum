"""Utility extractors over ``DocSchema`` (plain text, mentions, attachments).

All other modules MUST go through these helpers — never re-parse JSONB
in module code. See ``docs/data-model.md`` > "Module: content".
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.modules.content.exceptions import ContentValidationError
from app.modules.content.schemas import (
    BulletListBlock,
    CalloutBlock,
    CodeBlock,
    DocSchema,
    EmbedBlock,
    GifBlock,
    HeadingBlock,
    ImageBlock,
    LinkNode,
    ListItemBlock,
    MathBlock,
    MentionNode,
    OrderedListBlock,
    ParagraphBlock,
    QuoteBlock,
    TextNode,
    VideoBlock,
)

# Blocks treated as "block-level" for newline separation in plain-text output.
# Lists and list items emit newlines around their children; inline-ish nodes
# (mention, link, text) don't add extra newlines beyond the parent block's.


def validate_doc(raw: dict[str, Any]) -> DocSchema:
    """Parse raw JSON-able dict into ``DocSchema`` or raise ``ContentValidationError``.

    Wraps Pydantic's ``ValidationError`` so callers don't depend on Pydantic.
    """
    try:
        return DocSchema.model_validate(raw)
    except ValidationError as exc:
        raise ContentValidationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------


def extract_plain_text(doc: DocSchema) -> str:
    """Depth-first concatenation of every text node, newline between block-level.

    The result feeds the ``content_text`` projection used by Postgres
    FTS (``content_tsv``) and listing snippets.
    """
    parts: list[str] = []
    for block in doc.content:
        rendered = _render_block_text(block)
        if rendered:
            parts.append(rendered)
    return "\n".join(parts)


def _render_block_text(block: Any) -> str:
    """Recursively render a block's text content."""
    if isinstance(block, ParagraphBlock | HeadingBlock):
        return _render_inlines(block.content)
    if isinstance(block, CodeBlock):
        return "".join(n.text for n in block.content)
    if isinstance(block, MathBlock):
        return block.attrs.latex
    if isinstance(block, EmbedBlock):
        return block.attrs.url
    if isinstance(block, ImageBlock | GifBlock):
        attrs = block.attrs
        return getattr(attrs, "alt", "") or getattr(attrs, "caption", "") or ""
    if isinstance(block, VideoBlock):
        return block.attrs.caption or ""
    if isinstance(block, BulletListBlock | OrderedListBlock):
        return "\n".join(_render_block_text(item) for item in block.content)
    if isinstance(block, ListItemBlock):
        return "\n".join(_render_block_text(child) for child in block.content)
    if isinstance(block, CalloutBlock | QuoteBlock):
        return "\n".join(_render_block_text(child) for child in block.content)
    if isinstance(block, MentionNode):
        # Mentions render as @user_id placeholder in plain text.
        return f"@{block.attrs.user_id}"
    if isinstance(block, LinkNode):
        return block.attrs.title or block.attrs.href
    return ""


def _render_inlines(nodes: list[Any]) -> str:
    out: list[str] = []
    for n in nodes:
        if isinstance(n, TextNode):
            out.append(n.text)
        elif isinstance(n, MentionNode):
            out.append(f"@{n.attrs.user_id}")
        elif isinstance(n, LinkNode):
            out.append(n.attrs.title or n.attrs.href)
    return "".join(out)


# ---------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------


def extract_mentioned_user_ids(doc: DocSchema) -> set[UUID]:
    """Walk the document, collecting every ``mention`` block's ``user_id``."""
    found: set[UUID] = set()
    for block in doc.content:
        _walk_for_mentions(block, found)
    return found


def _walk_for_mentions(node: Any, into: set[UUID]) -> None:
    if isinstance(node, MentionNode):
        into.add(node.attrs.user_id)
        return
    # All container blocks expose .content with either inlines or nested blocks.
    children = getattr(node, "content", None)
    if children:
        for child in children:
            _walk_for_mentions(child, into)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


def extract_attachment_ids(doc: DocSchema) -> set[UUID]:
    """Collect every ``attachment_id`` referenced from image/video/gif blocks."""
    found: set[UUID] = set()
    for block in doc.content:
        _walk_for_attachments(block, found)
    return found


def _walk_for_attachments(node: Any, into: set[UUID]) -> None:
    if isinstance(node, ImageBlock | VideoBlock | GifBlock):
        # ``attachment_id`` is optional now (a media block may carry only a
        # raw ``src``) — skip when missing instead of None-poisoning the set.
        if node.attrs.attachment_id is not None:
            into.add(node.attrs.attachment_id)
        return
    children = getattr(node, "content", None)
    if children:
        for child in children:
            _walk_for_attachments(child, into)


__all__ = [
    "extract_attachment_ids",
    "extract_mentioned_user_ids",
    "extract_plain_text",
    "validate_doc",
]
