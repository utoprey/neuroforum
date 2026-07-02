# ADR 0002 — ProseMirror JSON in JSONB as the single content format

- **Status:** Accepted
- **Date:** 2026-06-21
- **Deciders:** project owner + Claude
- **Supersedes:** —

## Context

The forum has three classes of rich-text content:

1. **Articles** — long-form, Notion-like, with headings, code blocks,
   LaTeX math, images, video, embeds, mentions, callouts.
2. **Messages** — comments / discussion posts under articles, with full
   threading and reply-on-selection (a reply pinned to a specific span
   inside a parent block).
3. **Direct messages** — same rich-text capability as messages, scoped
   to a conversation.

We need:

- One editor on the frontend that works for all three.
- Server-side validation of structure (no XSS via embed HTML, no
  arbitrary block types).
- Plain-text projection for full-text search.
- The ability to compute structural diffs for revisions.
- Reply-on-selection: addressable positions inside a parent doc.
- Extractable references (mentioned users, used attachments) so feeds
  and GC work without re-parsing the blob.

The frontend is decided as TipTap (CLAUDE.md). TipTap's native data
model is ProseMirror JSON.

## Decision

**One content format: ProseMirror JSON, stored in a `JSONB content`
column on every content-bearing table** (`articles`, `messages`,
`direct_messages`).

Companion columns on every such table:

- `content_text TEXT NOT NULL DEFAULT ''` — plain-text projection,
  populated by the service via `content.extract_plain_text()` on every
  write.
- `content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('russian',
  coalesce(content_text, ''))) STORED` — driven by Postgres, no service
  involvement, indexed with GIN for FTS.
- `mentioned_user_ids UUID[] NOT NULL DEFAULT '{}'` — extracted at
  write time via `content.extract_mentioned_user_ids()`, GIN-indexed.

Pydantic validates the structure as a **discriminated union over
`type`** with a closed set of block types and inline marks. See
`docs/data-model.md` § "Notion blocks" for the full schema.

Embeds are restricted to a whitelist of four providers (`youtube`,
`github_gist`, `telegram`, `vk`). Each has a server-side parser that
produces sanitized metadata; oEmbed HTML is **never** trusted or
rendered. This keeps the embed surface auditable.

Reply-on-selection is a structured pointer (`reply_to_selection JSONB`
on `messages`), not a free-text quote — it carries
`{target, block_path, from, to, quote_text}`. The `quote_text` is a
denormalized snapshot so the UI degrades gracefully if the parent is
later edited.

## Consequences

### Positive

- **One editor, one schema, one validator.** TipTap on the frontend,
  Pydantic discriminated union on the backend, JSONB in storage —
  zero impedance mismatch.
- **Reply-on-selection is natural.** ProseMirror exposes a Range API
  that maps directly to `(block_path, from, to)`. With markdown or HTML
  this would require custom anchor logic.
- **Search is cheap.** Postgres handles the heavy lifting via the
  generated `tsvector` column; we never write a search-indexing job for
  text content.
- **Structural diffs for revisions.** JSONB blob → JSONB blob diff is a
  solved problem (`jsonb_diff`-style libraries, RFC 6902), enabling
  good revision UIs.
- **References are queryable.** GIN on `mentioned_user_ids` makes
  "@me" feeds an index lookup, not a full-table scan + JSON walk.
- **No HTML sanitization at storage time.** We never store HTML; we
  store a constrained tree. Sanitization is structural, not
  string-based.

### Negative

- **Vendor coupling to TipTap / ProseMirror.** Switching the frontend
  editor would require either (a) finding another editor that speaks
  ProseMirror JSON, or (b) writing a converter. Mitigation: ProseMirror
  JSON is a well-documented public schema, and at least three major
  editors (TipTap, BlockNote, ProseMirror itself) use it.
- **Bigger payloads than markdown.** A simple paragraph that would be
  `"hello"` in markdown is `{"type":"paragraph","content":[{"type":
  "text","text":"hello"}]}` in our format. Network and storage cost is
  noticeable for very short messages. Acceptable for forum-shaped
  content; revisit if we ever add a Twitter-like feature.
- **JSONB indexing is more nuanced than column indexing.** GIN
  (`jsonb_path_ops`) is the default but doesn't help every query; some
  queries will need expression indexes on specific JSON paths. We'll
  add those reactively, not preemptively.

### Neutral

- Plain text projection must be kept in sync. The service layer owns
  this: every write to `content` MUST recompute `content_text` from the
  same `extract_plain_text` helper. A regression test catches drift.

## Alternatives considered

### Markdown + GitHub-flavored extensions

Rejected. Reply-on-selection requires anchoring to specific positions
inside specific blocks, and markdown has no stable addressing — a
reflow rewrites the document. Also: math + embeds + mentions force us
into a half-dozen non-standard extensions that we'd have to parse
ourselves anyway.

### HTML

Rejected. XSS surface is enormous; sanitization is fragile; embeds via
oEmbed HTML would be exactly the wrong call. HTML loses structure
(headings vs. paragraphs become string parsing), which makes diffing
revisions and feeding LLM agents painful.

### Editor.js block format

Rejected. Editor.js has no native selection model on the frontend that
maps to backend addressing — reply-on-selection would require
substantial editor patching. Block ecosystem is also smaller than
ProseMirror's.

### BlockNote

Rejected for now (still uses ProseMirror under the hood, so a future
swap from TipTap → BlockNote is cheap and doesn't break this ADR).

### Lexical (Meta)

Rejected. Different serialization format means we'd lose the
"one schema end-to-end" property. Lexical's collaboration story is
also less mature for ProseMirror's collab protocol.

## References

- TipTap docs: <https://tiptap.dev/>
- ProseMirror schema: <https://prosemirror.net/docs/ref/#model.Schema>
- `docs/data-model.md` § Notion blocks
- `docs/data-model.md` § Reply-on-selection
