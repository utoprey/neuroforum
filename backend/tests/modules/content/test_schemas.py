"""Pydantic discriminated-union validation for the content schema."""

from __future__ import annotations

import uuid

import pytest

from app.modules.content.exceptions import ContentValidationError
from app.modules.content.schemas import DocSchema
from app.modules.content.utils import validate_doc


def _user_id() -> str:
    return str(uuid.uuid4())


def _attachment_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_validate_sample_tiptap_doc() -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "fMRI denoising"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "See "},
                    {"type": "mention", "attrs": {"user_id": _user_id()}},
                    {"type": "text", "text": " for the original idea."},
                ],
            },
            {
                "type": "math",
                "attrs": {"latex": r"\sigma^2", "display": False},
            },
            {
                "type": "codeBlock",
                "attrs": {"language": "python"},
                "content": [{"type": "text", "text": "import numpy as np"}],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "step one"}],
                            }
                        ],
                    }
                ],
            },
            {
                "type": "callout",
                "attrs": {"kind": "info", "icon": "bulb"},
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "ahem"}],
                    }
                ],
            },
        ],
    }
    doc = validate_doc(raw)
    assert isinstance(doc, DocSchema)
    assert len(doc.content) == 6


def test_text_marks_validate() -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "bold",
                        "marks": [{"type": "bold"}],
                    },
                    {
                        "type": "text",
                        "text": "linked",
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {"href": "https://x", "title": "x"},
                            }
                        ],
                    },
                ],
            }
        ],
    }
    doc = validate_doc(raw)
    assert doc.content[0].content[0].marks[0].type == "bold"  # type: ignore[index, union-attr]


def test_embed_whitelist_accepts_youtube() -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "embed",
                "attrs": {
                    "provider": "youtube",
                    "url": "https://youtu.be/dQw4w9WgXcQ",
                },
            }
        ],
    }
    doc = validate_doc(raw)
    assert doc.content[0].attrs.provider == "youtube"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Rejection cases
# ---------------------------------------------------------------------------


def test_rejects_unknown_block_type() -> None:
    raw = {
        "type": "doc",
        "content": [{"type": "spaceship", "attrs": {}}],
    }
    with pytest.raises(ContentValidationError):
        validate_doc(raw)


def test_rejects_heading_level_out_of_range() -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 7},
                "content": [{"type": "text", "text": "x"}],
            }
        ],
    }
    with pytest.raises(ContentValidationError):
        validate_doc(raw)


def test_rejects_embed_provider_not_in_whitelist() -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "embed",
                "attrs": {"provider": "twitter", "url": "https://x.com"},
            }
        ],
    }
    with pytest.raises(ContentValidationError):
        validate_doc(raw)


def test_rejects_top_level_not_doc() -> None:
    raw = {"type": "paragraph", "content": []}
    with pytest.raises(ContentValidationError):
        validate_doc(raw)


def test_rejects_extra_field_on_block() -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "hi"}],
                "evil": True,
            }
        ],
    }
    with pytest.raises(ContentValidationError):
        validate_doc(raw)


def test_image_allows_missing_attachment_id_when_src_provided() -> None:
    """Backend enricher resolves ``attachment_id`` → ``src``, but content
    imported from external sources or upload flows that haven't created an
    Attachment row yet may carry only ``src``. The schema accepts that
    shape now — previously both fields were rejected when ``attachment_id``
    was missing.
    """
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {
                    "src": "https://picsum.photos/seed/x/800/450",
                    "alt": "external",
                },
            }
        ],
    }
    doc = validate_doc(raw)
    assert doc.content[0].attrs.attachment_id is None  # type: ignore[union-attr]
    assert doc.content[0].attrs.src == "https://picsum.photos/seed/x/800/450"  # type: ignore[union-attr]


def test_image_attachment_id_must_be_uuid() -> None:
    raw = {
        "type": "doc",
        "content": [
            {
                "type": "image",
                "attrs": {"attachment_id": "not-a-uuid", "alt": "x"},
            }
        ],
    }
    with pytest.raises(ContentValidationError):
        validate_doc(raw)
