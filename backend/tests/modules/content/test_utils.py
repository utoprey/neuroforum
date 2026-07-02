"""Plain-text, mention, and attachment extractors over ``DocSchema``."""

from __future__ import annotations

import uuid

from app.modules.content.utils import (
    extract_attachment_ids,
    extract_mentioned_user_ids,
    extract_plain_text,
    validate_doc,
)


def test_extract_plain_text_basic() -> None:
    doc = validate_doc(
        {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Title"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "world"},
                    ],
                },
                {
                    "type": "codeBlock",
                    "attrs": {"language": "py"},
                    "content": [{"type": "text", "text": "x = 1"}],
                },
            ],
        }
    )
    out = extract_plain_text(doc)
    # Each block is newline-separated. Headings/paragraphs concatenate their inlines.
    assert out == "Title\nHello world\nx = 1"


def test_extract_plain_text_handles_nested_lists_and_callouts() -> None:
    doc = validate_doc(
        {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "a"}],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "b"}],
                                }
                            ],
                        },
                    ],
                },
                {
                    "type": "callout",
                    "attrs": {"kind": "info", "icon": ""},
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "note"}],
                        }
                    ],
                },
            ],
        }
    )
    out = extract_plain_text(doc)
    assert "a" in out
    assert "b" in out
    assert "note" in out


def test_extract_mentioned_user_ids() -> None:
    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    doc = validate_doc(
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "cc "},
                        {"type": "mention", "attrs": {"user_id": str(u1)}},
                        {"type": "text", "text": " and "},
                        {"type": "mention", "attrs": {"user_id": str(u2)}},
                    ],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        # Duplicate mention — must be deduped.
                                        {
                                            "type": "mention",
                                            "attrs": {"user_id": str(u1)},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    )
    result = extract_mentioned_user_ids(doc)
    assert result == {u1, u2}


def test_extract_mentioned_user_ids_empty() -> None:
    doc = validate_doc({"type": "doc", "content": []})
    assert extract_mentioned_user_ids(doc) == set()


def test_extract_attachment_ids_across_image_video_gif() -> None:
    a = uuid.uuid4()
    b = uuid.uuid4()
    c = uuid.uuid4()
    doc = validate_doc(
        {
            "type": "doc",
            "content": [
                {
                    "type": "image",
                    "attrs": {"attachment_id": str(a), "alt": "", "caption": ""},
                },
                {
                    "type": "video",
                    "attrs": {"attachment_id": str(b), "caption": ""},
                },
                {
                    "type": "gif",
                    "attrs": {"attachment_id": str(c), "alt": ""},
                },
            ],
        }
    )
    assert extract_attachment_ids(doc) == {a, b, c}


def test_validate_doc_returns_typed_model() -> None:
    doc = validate_doc({"type": "doc", "content": []})
    assert doc.type == "doc"
    assert doc.content == []
