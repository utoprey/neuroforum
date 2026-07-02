"""Pydantic v2 schemas mirroring the ProseMirror/TipTap JSON contract.

Source of truth: ``docs/data-model.md`` ("Notion blocks"). Any change here
requires an ADR.

The whole document is a single discriminated union (by ``type``) so we can
validate untrusted JSON in one ``DocSchema.model_validate`` call.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Embed provider whitelist
# ---------------------------------------------------------------------------

EmbedProvider = Literal["youtube", "github_gist", "telegram", "vk"]
EMBED_PROVIDERS: frozenset[str] = frozenset({"youtube", "github_gist", "telegram", "vk"})

CalloutKind = Literal["info", "warn", "note"]


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------


class _MarkBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BoldMark(_MarkBase):
    type: Literal["bold"]


class ItalicMark(_MarkBase):
    type: Literal["italic"]


class StrikeMark(_MarkBase):
    type: Literal["strike"]


class CodeMark(_MarkBase):
    type: Literal["code"]


class UnderlineMark(_MarkBase):
    type: Literal["underline"]


class LinkMarkAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    href: str
    title: str | None = None


class LinkMark(_MarkBase):
    type: Literal["link"]
    attrs: LinkMarkAttrs


MarkSchema = Annotated[
    BoldMark | ItalicMark | StrikeMark | CodeMark | UnderlineMark | LinkMark,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Inline nodes
# ---------------------------------------------------------------------------


class TextNode(BaseModel):
    """Leaf inline node carrying text + optional marks."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str
    marks: list[MarkSchema] | None = None


class MentionAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID


class MentionNode(BaseModel):
    """``@user`` mention. Backend extracts ``user_id`` for notifications."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["mention"]
    attrs: MentionAttrs


class LinkNodeAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    href: str
    title: str | None = None


class LinkNode(BaseModel):
    """Shorthand link block (no surrounding text). See data-model.md."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["link"]
    attrs: LinkNodeAttrs


InlineNode = Annotated[
    TextNode | MentionNode | LinkNode,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Block nodes — forward references because lists/callouts nest blocks.
# ---------------------------------------------------------------------------


class ParagraphBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["paragraph"]
    content: list[InlineNode] = Field(default_factory=list)


class HeadingAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: int = Field(ge=1, le=6)


class HeadingBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["heading"]
    attrs: HeadingAttrs
    content: list[InlineNode] = Field(default_factory=list)


class ListItemBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["listItem"]
    # ``BlockType`` is defined below; quoted forward ref.
    content: list[BlockType] = Field(default_factory=list)


class BulletListBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["bulletList"]
    content: list[ListItemBlock] = Field(default_factory=list)


class OrderedListAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: int = 1


class OrderedListBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["orderedList"]
    attrs: OrderedListAttrs = Field(default_factory=OrderedListAttrs)
    content: list[ListItemBlock] = Field(default_factory=list)


class CodeBlockAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str = ""


class CodeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["codeBlock"]
    attrs: CodeBlockAttrs = Field(default_factory=CodeBlockAttrs)
    content: list[TextNode] = Field(default_factory=list)


class MathAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    latex: str
    display: bool = False


class MathBlock(BaseModel):
    """KaTeX-rendered formula. ``display=True`` = block, False = inline."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["math"]
    attrs: MathAttrs


class ImageAttrs(BaseModel):
    # Media attrs accept an optional ``src`` so the backend can hand the
    # frontend a ready-to-render URL alongside (or instead of) the
    # ``attachment_id`` — see ``app.modules.content.enricher``. The id is
    # also optional because in seed/import flows we sometimes only know
    # the external URL (no Attachment row exists yet).
    model_config = ConfigDict(extra="forbid")
    attachment_id: UUID | None = None
    src: str | None = None
    alt: str = ""
    caption: str = ""


class ImageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["image"]
    attrs: ImageAttrs


class VideoAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: UUID | None = None
    src: str | None = None
    caption: str = ""


class VideoBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["video"]
    attrs: VideoAttrs


class GifAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attachment_id: UUID | None = None
    src: str | None = None
    alt: str = ""


class GifBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["gif"]
    attrs: GifAttrs


class EmbedAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: EmbedProvider
    url: str

    @field_validator("provider")
    @classmethod
    def _provider_in_whitelist(cls, v: str) -> str:
        # Literal already enforces this, but we double-check so the
        # whitelist constant ``EMBED_PROVIDERS`` stays authoritative.
        if v not in EMBED_PROVIDERS:
            raise ValueError(f"Embed provider must be one of {sorted(EMBED_PROVIDERS)}, got {v!r}")
        return v


class EmbedBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["embed"]
    attrs: EmbedAttrs


class CalloutAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: CalloutKind = "info"
    icon: str = ""


class CalloutBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["callout"]
    attrs: CalloutAttrs = Field(default_factory=CalloutAttrs)
    content: list[BlockType] = Field(default_factory=list)


class QuoteAttrs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cite_url: str | None = None


class QuoteBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["quote"]
    attrs: QuoteAttrs = Field(default_factory=QuoteAttrs)
    content: list[BlockType] = Field(default_factory=list)


# Top-level block discriminated union. ``mention`` is also valid as a
# block-level shorthand for pages that consist of a single mention.
BlockType = Annotated[
    (
        ParagraphBlock
        | HeadingBlock
        | BulletListBlock
        | OrderedListBlock
        | ListItemBlock
        | CodeBlock
        | MathBlock
        | ImageBlock
        | VideoBlock
        | GifBlock
        | EmbedBlock
        | MentionNode
        | CalloutBlock
        | QuoteBlock
        | LinkNode
    ),
    Field(discriminator="type"),
]


# Resolve forward references on the recursive types.
ListItemBlock.model_rebuild()
CalloutBlock.model_rebuild()
QuoteBlock.model_rebuild()


# ---------------------------------------------------------------------------
# Top-level document
# ---------------------------------------------------------------------------


class DocSchema(BaseModel):
    """A complete ProseMirror document. Stored as JSONB in content tables."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["doc"]
    content: list[BlockType] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reply-on-selection (referenced by ``messages`` module — defined here so
# every consumer pulls it from one place).
# ---------------------------------------------------------------------------


class ReplyTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["article", "message"]
    id: UUID


class ReplySelection(BaseModel):
    """Structured pointer into a parent document's block tree."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    target: ReplyTarget
    block_path: list[int]
    from_: int = Field(alias="from")
    to: int
    quote_text: str


__all__ = [
    "EMBED_PROVIDERS",
    "BlockType",
    "BoldMark",
    "BulletListBlock",
    "CalloutBlock",
    "CodeBlock",
    "CodeMark",
    "DocSchema",
    "EmbedBlock",
    "EmbedProvider",
    "GifBlock",
    "HeadingBlock",
    "ImageBlock",
    "InlineNode",
    "ItalicMark",
    "LinkMark",
    "LinkNode",
    "ListItemBlock",
    "MarkSchema",
    "MathBlock",
    "MentionNode",
    "OrderedListBlock",
    "ParagraphBlock",
    "QuoteBlock",
    "ReplySelection",
    "ReplyTarget",
    "StrikeMark",
    "TextNode",
    "UnderlineMark",
    "VideoBlock",
]


