# Data model

> Source of truth for Postgres schema, content payloads, and cross-module
> conventions. Module agents MUST read this file before writing migrations,
> models, or Pydantic schemas. Anything not described here is up for
> discussion — but everything described here is ratified and should not be
> changed without an ADR.

---

## Conventions

- **Primary keys.** UUID v4 by default (`id UUID PK DEFAULT uuid_generate_v4()`).
  Exception: high-volume append-only tables (e.g. `audit_log`) use `BIGSERIAL`
  because UUID indexes bloat for time-ordered inserts.
- **Timestamps.** Always `TIMESTAMPTZ`, never `TIMESTAMP`. Default `now()`.
  Naive `datetime` is forbidden — `core/db.py` configures SQLAlchemy and
  Alembic to enforce this.
- **Content payloads.** All rich-text (articles, messages, DMs) lives in a
  `JSONB content` column following the ProseMirror schema defined below.
  A `content_text TEXT` projection holds the extracted plain text; a
  `content_tsv TSVECTOR GENERATED ALWAYS AS (...) STORED` column is built
  from it for full-text search.
- **Naming convention.** `core/db.py` registers a SQLAlchemy
  `naming_convention` for `ix`/`uq`/`fk`/`pk`/`ck` so Alembic autogenerate
  produces stable diffs. All constraints get explicit names.
- **Soft delete.** Records are not physically deleted. The `content` column
  is set to `'{}'::jsonb`, `content_text` to `''`, status flipped to
  `deleted_by_author` or `hidden_by_mod`. The full pre-delete snapshot is
  kept in the corresponding `*_revisions` table. The UI renders a
  "Сообщение удалено автором" / "Скрыто модератором" placeholder.
- **Slugs.** Auto-generated from title via transliteration. Unique per
  parent: `UNIQUE(topic_id, slug)` for articles, `UNIQUE(section_id, slug)`
  for topics, global `UNIQUE` for sections. URL strategy is Habrahabr-style:
  `/articles/<uuid>/<slug>` — UUID is the canonical identifier, slug is
  cosmetic and may change without breaking links.
- **External secrets.** Per-user API keys (OpenRouter / cloud.ru / etc.)
  are stored Fernet-encrypted under the `ENCRYPTION_KEY` env var. The key
  itself never leaves the backend process; only ciphertext touches the DB.
- **JSONB indexing.** Default to `GIN(... jsonb_path_ops)` for membership
  queries; default to `GIN(content_tsv)` for FTS. Don't index large JSONB
  blobs unless an actual query needs it.
- **Mentions denormalization.** Every content-bearing row carries
  `mentioned_user_ids UUID[] DEFAULT '{}'` (GIN-indexed) for cheap
  "mentions of me" feeds, AND a row in the global `mentions` table for
  history/audit.
- **Reaction denormalization.** Every reactable row carries a
  `reaction_counts JSONB DEFAULT '{}'` map (e.g. `{"brain": 12, "dna": 3}`)
  updated by a trigger or service-layer hook. The source of truth is still
  the row-per-reaction table.

---

## Postgres extensions

The first Alembic migration MUST create these extensions before any table:

| Extension    | Purpose                                                          |
| ------------ | ---------------------------------------------------------------- |
| `uuid-ossp`  | `uuid_generate_v4()` default for PKs                             |
| `citext`     | Case-insensitive email column                                    |
| `pg_trgm`    | Trigram GIN indexes for fuzzy `username` / `display_name` search |
| `ltree`      | Threaded message paths (`messages.path`)                         |

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS ltree;
```

---

## Notion blocks (ProseMirror JSON)

The frontend uses TipTap, which serializes to ProseMirror JSON. We mirror
that schema 1:1 on the backend and validate it with Pydantic v2
discriminated unions. The same schema is used by `articles.content`,
`messages.content`, and `direct_messages.content`.

### Top-level document

```python
class DocSchema(BaseModel):
    type: Literal["doc"]
    content: list[BlockType]
```

### Block types (discriminated by `type`)

| `type`         | Required fields                                  | Notes                                                          |
| -------------- | ------------------------------------------------ | -------------------------------------------------------------- |
| `paragraph`    | `content: list[InlineNode]`                      | Default block                                                  |
| `heading`      | `attrs: {level: 1..6}`, `content`                |                                                                |
| `bulletList`   | `content: list[ListItem]`                        |                                                                |
| `orderedList`  | `attrs: {start: int}`, `content: list[ListItem]` |                                                                |
| `listItem`     | `content: list[BlockType]`                       |                                                                |
| `codeBlock`    | `attrs: {language: str}`, `content`              | Plain text inside                                              |
| `math`         | `attrs: {latex: str, display: bool}`             | KaTeX-rendered on frontend                                     |
| `image`        | `attrs: {attachment_id, alt, caption}`           | `attachment_id` references `attachments.id` (deferred module)  |
| `video`        | `attrs: {attachment_id, caption}`                | Processed via Dramatiq + ffmpeg                                |
| `gif`          | `attrs: {attachment_id, alt}`                    |                                                                |
| `embed`        | `attrs: {provider, url}`                         | `provider` ∈ {`youtube`, `github_gist`, `telegram`, `vk`} only |
| `mention`      | `attrs: {user_id: UUID}`                         | Backend extracts to `mentioned_user_ids`                       |
| `callout`      | `attrs: {kind, icon}`, `content`                 | `kind` ∈ {`info`, `warn`, `note`}                              |
| `quote`        | `attrs: {cite_url: str?}`, `content`             |                                                                |

### Inline nodes

```python
class TextNode(BaseModel):
    type: Literal["text"]
    text: str
    marks: list[MarkSchema] | None = None

class MarkSchema(BaseModel):
    type: Literal["bold", "italic", "strike", "code", "link", "underline"]
    attrs: dict[str, Any] | None = None  # e.g. link: {href, title}
```

A pure `link` block (without surrounding text) is also allowed as a
shorthand: `{"type": "link", "attrs": {"href": "...", "title": "..."}}`.

### Embed whitelist

Only four providers are accepted:

| `provider`     | URL pattern (validated server-side)                  |
| -------------- | ---------------------------------------------------- |
| `youtube`      | `youtube.com/watch?v=`, `youtu.be/`                  |
| `github_gist`  | `gist.github.com/<user>/<id>`                        |
| `telegram`     | `t.me/<channel>/<post_id>`                           |
| `vk`           | `vk.com/video<owner>_<id>`, `vk.com/wall...`         |

oEmbed HTML is **not trusted**. Each provider has a dedicated parser on
the backend that produces sanitized metadata.

### Example article content

```json
{
  "type": "doc",
  "content": [
    {"type": "heading", "attrs": {"level": 1},
     "content": [{"type": "text", "text": "fMRI denoising"}]},
    {"type": "paragraph", "content": [
      {"type": "text", "text": "See "},
      {"type": "mention", "attrs": {"user_id": "5a7e..."}},
      {"type": "text", "text": " for the original idea."}
    ]},
    {"type": "math", "attrs": {"latex": "\\sigma^2", "display": false}},
    {"type": "codeBlock", "attrs": {"language": "python"},
     "content": [{"type": "text", "text": "import numpy as np"}]}
  ]
}
```

---

## Reply-on-selection

When a message replies to a *specific span* inside another article or
message, the link is stored structurally — not as a free-text quote.
The `messages.reply_to_selection` column holds:

```python
class ReplyTarget(BaseModel):
    type: Literal["article", "message"]
    id: UUID

class ReplySelection(BaseModel):
    target: ReplyTarget
    block_path: list[int]   # path into DocSchema.content tree, e.g. [2, 0, 1]
    from_: int = Field(alias="from")  # ProseMirror Range offset
    to: int                # ProseMirror Range offset
    quote_text: str        # plain-text snapshot for rendering if parent changes
```

`quote_text` is denormalized so the UI still has something to show if the
parent block is edited or deleted.

---

## Module: `content` (no tables)

Pure Pydantic schemas and utility functions — no DB models. Exports:

- `DocSchema`, `BlockType`, `TextNode`, `MarkSchema`, `ReplySelection`
- `extract_plain_text(doc: DocSchema) -> str` — populates `content_text`
- `extract_mentioned_user_ids(doc: DocSchema) -> list[UUID]`
- `extract_attachment_ids(doc: DocSchema) -> list[UUID]`
- `validate_embed_url(provider, url) -> bool`

All other modules MUST call these helpers — no parallel implementations.

---

## Module: `users`

### `users`

| Column          | Type                                                | Notes                              |
| --------------- | --------------------------------------------------- | ---------------------------------- |
| `id`            | `UUID PK DEFAULT uuid_generate_v4()`                |                                    |
| `username`      | `VARCHAR(50) NOT NULL UNIQUE`                       | `@handle`, lowercase enforced      |
| `email`         | `CITEXT UNIQUE NULL`                                | NULL for `role='agent'`            |
| `password_hash` | `VARCHAR(255) NULL`                                 | argon2; NULL for agents            |
| `role`          | `user_role NOT NULL DEFAULT 'user'`                 | enum below                         |
| `is_active`     | `BOOL NOT NULL DEFAULT TRUE`                        | hard kill-switch                   |
| `created_at`    | `TIMESTAMPTZ NOT NULL DEFAULT now()`                |                                    |
| `updated_at`    | `TIMESTAMPTZ NOT NULL DEFAULT now()`                | service-layer touch                |
| `last_login_at` | `TIMESTAMPTZ NULL`                                  |                                    |

### `user_profiles`

| Column         | Type                                       | Notes                                          |
| -------------- | ------------------------------------------ | ---------------------------------------------- |
| `user_id`      | `UUID PK FK users.id ON DELETE CASCADE`    | 1:1                                            |
| `display_name` | `VARCHAR(100)`                             | "Иван Иванов"                                  |
| `bio`          | `TEXT`                                     |                                                |
| `avatar_url`   | `VARCHAR(500)`                             |                                                |
| `orcid`        | `VARCHAR(19)`                              | `CHECK (orcid ~ '^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$' OR orcid IS NULL)` |
| `social_links` | `JSONB NOT NULL DEFAULT '{}'`              | `{twitter, github, telegram, website}`         |
| `locale`       | `VARCHAR(10) NOT NULL DEFAULT 'ru'`        |                                                |
| `timezone`     | `VARCHAR(50) NOT NULL DEFAULT 'UTC'`       |                                                |

### `user_stats`

| Column                       | Type                                    | Notes                          |
| ---------------------------- | --------------------------------------- | ------------------------------ |
| `user_id`                    | `UUID PK FK users.id ON DELETE CASCADE` |                                |
| `articles_count`             | `INT NOT NULL DEFAULT 0`                |                                |
| `messages_count`             | `INT NOT NULL DEFAULT 0`                |                                |
| `received_reactions_count`   | `INT NOT NULL DEFAULT 0`                |                                |
| `saved_articles_count`       | `INT NOT NULL DEFAULT 0`                |                                |
| `updated_at`                 | `TIMESTAMPTZ NOT NULL DEFAULT now()`    | bumped by trigger / async job  |

### Indexes

- `ix_users_username_trgm` — `GIN(username gin_trgm_ops)` — fuzzy search
- `ix_user_profiles_display_name_trgm` — `GIN(display_name gin_trgm_ops)`
- `ix_users_role` — `B-tree(role)` for filtering agents
- `uq_users_username`, `uq_users_email` — already enforced by `UNIQUE`

### `/users/search?q=` semantics

- If `q` starts with `@` → prefix match against `username` (B-tree LIKE
  `'@'-stripped || '%'`).
- Otherwise → `username ILIKE '%' || q || '%'` AND/OR `display_name`
  trigram similarity over `pg_trgm`, ranked by `similarity()` desc.

---

## Module: `auth`

### `refresh_tokens`

| Column        | Type                                          | Notes                  |
| ------------- | --------------------------------------------- | ---------------------- |
| `id`          | `UUID PK`                                     |                        |
| `user_id`     | `UUID NOT NULL FK users.id ON DELETE CASCADE` |                        |
| `token_hash`  | `VARCHAR(255) NOT NULL UNIQUE`                | SHA-256 of raw token   |
| `expires_at`  | `TIMESTAMPTZ NOT NULL`                        |                        |
| `revoked_at`  | `TIMESTAMPTZ NULL`                            | manual or auto         |
| `user_agent`  | `VARCHAR(500) NULL`                           |                        |
| `ip`          | `INET NULL`                                   |                        |
| `created_at`  | `TIMESTAMPTZ NOT NULL DEFAULT now()`          |                        |

Indexes: `ix_refresh_tokens_user_id_expires_at`.

Bot-token auth for agents is handled in the `agents` module (deferred).

---

## Module: `rbac`

### `user_bans`

| Column        | Type                                                 | Notes                       |
| ------------- | ---------------------------------------------------- | --------------------------- |
| `id`          | `UUID PK`                                            |                             |
| `user_id`     | `UUID NOT NULL FK users.id ON DELETE CASCADE`        | banned user                 |
| `banned_by`   | `UUID NOT NULL FK users.id`                          | moderator/admin             |
| `reason`      | `TEXT NOT NULL`                                      |                             |
| `scope`       | `ban_scope NOT NULL`                                 | `global` / `section` / `topic` |
| `section_id`  | `UUID NULL FK sections.id` (use_alter, deferrable)   | non-null iff `scope='section'` |
| `topic_id`    | `UUID NULL FK topics.id` (use_alter, deferrable)     | non-null iff `scope='topic'` |
| `starts_at`   | `TIMESTAMPTZ NOT NULL DEFAULT now()`                 |                             |
| `expires_at`  | `TIMESTAMPTZ NULL`                                   | NULL = permanent            |
| `lifted_at`   | `TIMESTAMPTZ NULL`                                   | manual unban                |
| `lifted_by`   | `UUID NULL FK users.id`                              |                             |
| `lift_reason` | `TEXT NULL`                                          |                             |
| `created_at`  | `TIMESTAMPTZ NOT NULL DEFAULT now()`                 |                             |

Constraints:

```sql
CHECK (
  (scope = 'global'  AND section_id IS NULL AND topic_id IS NULL) OR
  (scope = 'section' AND section_id IS NOT NULL AND topic_id IS NULL) OR
  (scope = 'topic'   AND section_id IS NULL AND topic_id IS NOT NULL)
)
```

Index: `ix_user_bans_user_id_expires_at(user_id, expires_at)` —
permission check on every authed request.

> **`use_alter` note.** `section_id` / `topic_id` FKs are declared with
> `use_alter=True, deferrable=True` so Alembic can order the cross-module
> migrations without circular-dependency deadlocks.

`users.is_active` is **separate** from bans: it's the hard kill-switch
(e.g. account compromise, deletion request). Bans are scoped and
historical.

---

## Module: `forum`

### `sections`

| Column        | Type                                  | Notes                |
| ------------- | ------------------------------------- | -------------------- |
| `id`          | `UUID PK`                             |                      |
| `slug`        | `VARCHAR(100) NOT NULL UNIQUE`        | e.g. `fmri`          |
| `title`       | `VARCHAR(200) NOT NULL`               |                      |
| `description` | `TEXT`                                |                      |
| `position`    | `INT NOT NULL DEFAULT 0`              | manual ordering      |
| `icon`        | `VARCHAR(50)`                         | icon name token      |
| `created_at`  | `TIMESTAMPTZ NOT NULL DEFAULT now()`  |                      |
| `updated_at`  | `TIMESTAMPTZ NOT NULL DEFAULT now()`  |                      |

### `topics`

| Column        | Type                                              | Notes                  |
| ------------- | ------------------------------------------------- | ---------------------- |
| `id`          | `UUID PK`                                         |                        |
| `section_id`  | `UUID NOT NULL FK sections.id ON DELETE RESTRICT` |                        |
| `slug`        | `VARCHAR(150) NOT NULL`                           | UNIQUE per section     |
| `title`       | `VARCHAR(300) NOT NULL`                           |                        |
| `description` | `TEXT`                                            |                        |
| `is_locked`   | `BOOL NOT NULL DEFAULT FALSE`                     | no new articles        |
| `is_pinned`   | `BOOL NOT NULL DEFAULT FALSE`                     | sort priority          |
| `created_by`  | `UUID NOT NULL FK users.id`                       |                        |
| `created_at`  | `TIMESTAMPTZ NOT NULL DEFAULT now()`              |                        |
| `updated_at`  | `TIMESTAMPTZ NOT NULL DEFAULT now()`              |                        |

Constraints: `UNIQUE(section_id, slug)`.

Indexes: `ix_topics_section_id_is_pinned_updated_at` for listing.

---

## Module: `articles`

### `articles`

| Column                | Type                                                                              | Notes                                                          |
| --------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `id`                  | `UUID PK`                                                                         |                                                                |
| `topic_id`            | `UUID NOT NULL FK topics.id ON DELETE RESTRICT`                                   |                                                                |
| `slug`                | `VARCHAR(200) NOT NULL`                                                           | UNIQUE per topic; transliterated from title                    |
| `title`               | `VARCHAR(300) NOT NULL`                                                           |                                                                |
| `summary`             | `TEXT`                                                                            | short blurb for listings                                       |
| `content`             | `JSONB NOT NULL`                                                                  | ProseMirror `DocSchema`                                        |
| `content_text`        | `TEXT NOT NULL DEFAULT ''`                                                        | populated by service via `extract_plain_text`                  |
| `content_tsv`         | `TSVECTOR GENERATED ALWAYS AS (to_tsvector('russian', coalesce(content_text,''))) STORED` | FTS                                                     |
| `author_id`           | `UUID NOT NULL FK users.id`                                                       |                                                                |
| `status`              | `article_status NOT NULL DEFAULT 'draft'`                                         | `draft` / `published` / `archived` / `hidden`                  |
| `published_at`        | `TIMESTAMPTZ NULL`                                                                | set when transitioning to `published`                          |
| `view_count`          | `INT NOT NULL DEFAULT 0`                                                          | denormalized snapshot; live counter in Redis                   |
| `comment_count`       | `INT NOT NULL DEFAULT 0`                                                          | denormalized                                                   |
| `mentioned_user_ids`  | `UUID[] NOT NULL DEFAULT '{}'`                                                    | GIN-indexed                                                    |
| `reaction_counts`     | `JSONB NOT NULL DEFAULT '{}'`                                                     | `{"brain": 12, ...}`                                           |
| `created_at`          | `TIMESTAMPTZ NOT NULL DEFAULT now()`                                              |                                                                |
| `updated_at`          | `TIMESTAMPTZ NOT NULL DEFAULT now()`                                              |                                                                |

Constraints: `UNIQUE(topic_id, slug)`.

Indexes:

- `ix_articles_topic_status_published_at(topic_id, status, published_at DESC)` — topic feed
- `ix_articles_author_id_created_at(author_id, created_at DESC)` — user's articles
- `ix_articles_content_gin` — `GIN(content jsonb_path_ops)`
- `ix_articles_content_tsv` — `GIN(content_tsv)`
- `ix_articles_mentioned_user_ids` — `GIN(mentioned_user_ids)`

### `article_revisions`

| Column                | Type                                            | Notes                              |
| --------------------- | ----------------------------------------------- | ---------------------------------- |
| `id`                  | `UUID PK`                                       |                                    |
| `article_id`          | `UUID NOT NULL FK articles.id ON DELETE CASCADE`|                                    |
| `revision`            | `INT NOT NULL`                                  | monotonic per `article_id`         |
| `editor_id`           | `UUID NOT NULL FK users.id`                     |                                    |
| `editor_role_at_edit` | `VARCHAR(20) NOT NULL`                          | snapshot of role                   |
| `title`               | `VARCHAR(300) NOT NULL`                         |                                    |
| `content`             | `JSONB NOT NULL`                                | full snapshot                      |
| `edit_reason`         | `TEXT`                                          | required for mod edits             |
| `created_at`          | `TIMESTAMPTZ NOT NULL DEFAULT now()`            |                                    |

Constraints: `UNIQUE(article_id, revision)`.

### Drafts visibility

`status='draft'` articles are returned by the service layer ONLY when the
requester is the author OR has role `moderator` / `admin`. Enforced in
`articles.service.list_visible_for(user)`.

### View counter

Live counter lives in Redis under `article:views:<uuid>`. A Dramatiq cron
actor (`articles.workers.flush_view_counts`, every 60 s) drains the keys
into `articles.view_count`. The Redis key is the source of truth for
real-time UI; the column is the source of truth for analytics and
listings.

---

## Module: `messages`

### `messages`

| Column                | Type                                                                              | Notes                                                       |
| --------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `id`                  | `UUID PK`                                                                         |                                                             |
| `article_id`          | `UUID NOT NULL FK articles.id ON DELETE CASCADE`                                  |                                                             |
| `parent_id`           | `UUID NULL FK messages.id ON DELETE CASCADE`                                      | direct parent; NULL for top-level                           |
| `thread_root_id`      | `UUID NULL FK messages.id ON DELETE CASCADE`                                      | root of the subtree this message belongs to                 |
| `depth`               | `SMALLINT NOT NULL DEFAULT 0`                                                     | service enforces `<= 8`                                     |
| `path`                | `LTREE NOT NULL`                                                                  | e.g. `root_uuid.child1_uuid.child2_uuid` (UUIDs with `-`→`_`) |
| `author_id`           | `UUID NOT NULL FK users.id`                                                       |                                                             |
| `content`             | `JSONB NOT NULL`                                                                  |                                                             |
| `content_text`        | `TEXT NOT NULL DEFAULT ''`                                                        |                                                             |
| `content_tsv`         | `TSVECTOR GENERATED ALWAYS AS (to_tsvector('russian', coalesce(content_text,''))) STORED` |                                                             |
| `reply_to_selection`  | `JSONB NULL`                                                                      | structured `ReplySelection`                                 |
| `status`              | `message_status NOT NULL DEFAULT 'visible'`                                       | `visible` / `edited` / `hidden_by_mod` / `deleted_by_author`|
| `mentioned_user_ids`  | `UUID[] NOT NULL DEFAULT '{}'`                                                    |                                                             |
| `reaction_counts`     | `JSONB NOT NULL DEFAULT '{}'`                                                     |                                                             |
| `created_at`          | `TIMESTAMPTZ NOT NULL DEFAULT now()`                                              |                                                             |
| `updated_at`          | `TIMESTAMPTZ NOT NULL DEFAULT now()`                                              |                                                             |

Indexes:

- `ix_messages_article_created_at(article_id, created_at)` — article feed
- `ix_messages_parent_created_at(parent_id, created_at)` — children fetch
- `ix_messages_author_created_at(author_id, created_at DESC)`
- `ix_messages_path_gist` — `GIST(path)` — subtree queries (`path <@ ...`)
- `ix_messages_content_tsv` — `GIN(content_tsv)`
- `ix_messages_mentioned_user_ids` — `GIN(mentioned_user_ids)`

Service constraint: when inserting a child, `depth = parent.depth + 1`
and the service rejects `depth > 8` with HTTP 422. Enforced in code, not
DB — easier to relax later.

### `message_revisions`

Mirrors `article_revisions`: `id`, `message_id FK CASCADE`, `revision`,
`editor_id`, `editor_role_at_edit`, `content JSONB`, `edit_reason`,
`created_at`. `UNIQUE(message_id, revision)`.

---

## Module: `reactions`

ENUM `reaction_kind` (fixed neuro-themed set):

| Value         | Glyph |
| ------------- | ----- |
| `brain`       | 🧠    |
| `synapse`     | ⚡    |
| `neuron`      | 🪩    |
| `microscope`  | 🔬    |
| `dna`         | 🧬    |
| `mindblown`   | 🤯    |
| `petri`       | 🧫    |
| `lightbulb`   | 💡    |

Separate tables per parent (no polymorphic association — denormalized for
FK integrity and index efficiency):

### `article_reactions`

| Column       | Type                                              |
| ------------ | ------------------------------------------------- |
| `user_id`    | `UUID NOT NULL FK users.id ON DELETE CASCADE`     |
| `article_id` | `UUID NOT NULL FK articles.id ON DELETE CASCADE`  |
| `kind`       | `reaction_kind NOT NULL`                          |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()`              |

PK: `(user_id, article_id, kind)` — same user can leave multiple
different reactions on one article.

### `message_reactions`

Same shape, `message_id` instead of `article_id`. PK
`(user_id, message_id, kind)`.

On insert/delete, a service hook (or trigger) updates
`articles.reaction_counts` / `messages.reaction_counts` JSONB so feeds
don't need to aggregate at read time.

---

## Module: `saved`

### `saved_articles`

| Column       | Type                                              |
| ------------ | ------------------------------------------------- |
| `user_id`    | `UUID NOT NULL FK users.id ON DELETE CASCADE`     |
| `article_id` | `UUID NOT NULL FK articles.id ON DELETE CASCADE`  |
| `saved_at`   | `TIMESTAMPTZ NOT NULL DEFAULT now()`              |

PK: `(user_id, article_id)`. Index: `ix_saved_articles_user_saved_at(user_id, saved_at DESC)`.

---

## Module: `mentions`

### `mentions`

| Column               | Type                                          | Notes                                       |
| -------------------- | --------------------------------------------- | ------------------------------------------- |
| `id`                 | `UUID PK`                                     |                                             |
| `source_type`        | `mention_source_type NOT NULL`                | `article` / `message` / `direct_message`    |
| `source_id`          | `UUID NOT NULL`                               | logical FK — no DB FK due to polymorphism   |
| `mentioned_user_id`  | `UUID NOT NULL FK users.id ON DELETE CASCADE` |                                             |
| `author_id`          | `UUID NOT NULL FK users.id`                   | who wrote the mention                       |
| `notified_at`        | `TIMESTAMPTZ NULL`                            | set by notification worker                  |
| `created_at`         | `TIMESTAMPTZ NOT NULL DEFAULT now()`          |                                             |

Indexes:

- `ix_mentions_mentioned_created(mentioned_user_id, created_at DESC)` — "my mentions" feed
- `ix_mentions_source(source_type, source_id)` — backfill on edit

A trigger on `mentions` enqueues a Dramatiq notification job (or the
service layer does this explicitly — TBD per-module).

---

## Module: `notifications`

### `notifications`

| Column      | Type                                          | Notes                              |
| ----------- | --------------------------------------------- | ---------------------------------- |
| `id`        | `UUID PK`                                     |                                    |
| `user_id`   | `UUID NOT NULL FK users.id ON DELETE CASCADE` | recipient                          |
| `type`      | `VARCHAR(50) NOT NULL`                        | `mention` / `reply` / `reaction` / `mod_action` / ... |
| `payload`   | `JSONB NOT NULL DEFAULT '{}'`                 | type-dependent                     |
| `is_read`   | `BOOL NOT NULL DEFAULT FALSE`                 |                                    |
| `created_at`| `TIMESTAMPTZ NOT NULL DEFAULT now()`          |                                    |

Index: `ix_notifications_user_unread_created(user_id, is_read, created_at DESC)`.

---

## Module: `search` (no tables)

See `docs/adr/0003-postgres-tsvector-with-opensearch-stub.md`.

```python
class SearchEngine(Protocol):
    async def index_article(self, article_id: UUID) -> None: ...
    async def index_message(self, message_id: UUID) -> None: ...
    async def search(
        self, q: str, *, kind: Literal["article", "message", "user"],
        limit: int = 20, offset: int = 0,
    ) -> SearchResults: ...
```

Two implementations:

- `PostgresSearchEngine` — uses `content_tsv` columns + `ts_rank_cd`,
  `pg_trgm` for usernames. Live now.
- `OpenSearchSearchEngine` — stub that raises `NotImplementedError`. To
  be filled in when scale demands it.

DI picks one based on `SEARCH_BACKEND` env (`postgres` | `opensearch`).

---

## Module: `moderation`

### `audit_log`

| Column        | Type                                  | Notes                              |
| ------------- | ------------------------------------- | ---------------------------------- |
| `id`          | `BIGSERIAL PK`                        | append-only, time-ordered          |
| `actor_id`    | `UUID NOT NULL FK users.id`           |                                    |
| `action`      | `VARCHAR(50) NOT NULL`                | `ban_user`, `edit_article`, ...    |
| `target_type` | `VARCHAR(50) NOT NULL`                | `user` / `article` / `message` / ... |
| `target_id`   | `UUID NOT NULL`                       | logical FK                         |
| `payload`     | `JSONB NOT NULL DEFAULT '{}'`         | before/after, reason, etc.         |
| `ip`          | `INET`                                |                                    |
| `user_agent`  | `VARCHAR(500)`                        |                                    |
| `created_at`  | `TIMESTAMPTZ NOT NULL DEFAULT now()`  |                                    |

Indexes:

- `ix_audit_log_actor_created(actor_id, created_at DESC)`
- `ix_audit_log_target(target_type, target_id)`
- `ix_audit_log_action_created(action, created_at DESC)`

Audit log is **never** soft-deleted, never edited, only inserted.

---

## Deferred modules (next iteration)

These are designed but not in the first migration. Documented here so
module agents know the shape before implementing.

### Module: `attachments` (deferred)

- `attachments`: id, owner_id FK users, kind ∈ {`image`, `video`, `gif`,
  `file`}, mime, size_bytes, original_filename, s3_bucket, s3_key,
  processing_status ENUM(`pending`, `processing`, `ready`, `failed`),
  thumbnail_s3_key, width, height, duration_ms, metadata JSONB,
  created_at.
- `attachment_usages`: attachment_id FK CASCADE, source_type, source_id,
  PK(attachment_id, source_type, source_id). Used to garbage-collect
  unreferenced uploads.
- Video upload pipeline: client uploads to MinIO → row inserted with
  `processing_status='pending'` → Dramatiq actor (`attachments.workers.
  process_video`) runs ffmpeg, generates thumbnail + h264 mp4, updates
  status.

### Module: `dm` (deferred — direct messages)

- `conversations`: id, kind `conversation_kind` ∈ {`dm`, `group`},
  title (group only), created_by, dm_key VARCHAR NULL UNIQUE
  (computed as `"{min_uuid}:{max_uuid}"` for `kind='dm'`, NULL for groups
  — guarantees one DM thread per pair), created_at.
- `conversation_participants`: conversation_id FK CASCADE, user_id FK
  CASCADE, role ENUM(`owner`, `member`), joined_at, last_read_at,
  PK(conversation_id, user_id).
- `direct_messages`: id, conversation_id FK CASCADE, author_id, content
  JSONB (ProseMirror), content_text, reply_to_id FK self NULL,
  mentioned_user_ids UUID[], created_at, edited_at, status.
- `direct_message_reads`: message_id FK CASCADE, user_id FK CASCADE,
  read_at, PK(message_id, user_id). For read receipts.

### Module: `agents` (deferred — LLM bots)

- `agent_credentials`: id, owner_id FK users, provider `llm_provider`
  ∈ {`openrouter`, `cloud_ru`, `anthropic`, `openai`, ...}, label,
  encrypted_api_key BYTEA (Fernet ciphertext under `ENCRYPTION_KEY`),
  created_at, last_used_at, is_active.
- `agents`: id (also FK to `users.id` — every agent IS a user with
  `role='agent'`), credential_id FK agent_credentials, model_id VARCHAR
  (e.g. `openrouter/anthropic/claude-3.5-sonnet`), system_prompt TEXT,
  mcp_tools JSONB (which tools the agent may call), rate_limit JSONB
  (per-minute / per-day token caps), is_active, created_at.
- `llm_usage_log`: id BIGSERIAL, agent_id FK agents, credential_id FK,
  request_id UUID, model VARCHAR, prompt_tokens INT, completion_tokens
  INT, cost_usd NUMERIC(10,6), duration_ms INT, status `llm_status`
  ∈ {`ok`, `error`, `timeout`, `rate_limited`}, error_message TEXT NULL,
  created_at. Indexes on (agent_id, created_at DESC), (credential_id,
  created_at DESC).

### Module: `ai_proposals` (deferred)

- `article_ai_proposals`: id, article_id FK CASCADE, agent_id FK agents,
  action `ai_proposal_action` ∈ {`fix_typos`, `improve_clarity`,
  `add_summary`, `translate`, `extend_section`}, proposed_content JSONB,
  diff JSONB (RFC 6902 or similar), reasoning TEXT, status
  `ai_proposal_status` ∈ {`pending`, `accepted`, `rejected`, `expired`},
  decided_by FK users NULL, decided_at NULL, expires_at TIMESTAMPTZ NOT
  NULL (= created_at + 3 days), created_at. A Dramatiq cron actor flips
  `pending` → `expired` when `expires_at < now()`.

### Module: `embeds` (deferred)

- `embeds`: provider, url_hash (SHA-256), url, metadata JSONB (title,
  thumbnail, author, html snippet), fetched_at, expires_at, PK(provider,
  url_hash). Cache for embed parsers.

---

## Indexes summary

| Table                | Index                                              | Type                       |
| -------------------- | -------------------------------------------------- | -------------------------- |
| `users`              | `uq_users_username`                                | B-tree UNIQUE              |
| `users`              | `uq_users_email`                                   | B-tree UNIQUE              |
| `users`              | `ix_users_username_trgm`                           | GIN `gin_trgm_ops`         |
| `users`              | `ix_users_role`                                    | B-tree                     |
| `user_profiles`      | `ix_user_profiles_display_name_trgm`               | GIN `gin_trgm_ops`         |
| `refresh_tokens`     | `uq_refresh_tokens_token_hash`                     | B-tree UNIQUE              |
| `refresh_tokens`     | `ix_refresh_tokens_user_id_expires_at`             | B-tree                     |
| `user_bans`          | `ix_user_bans_user_id_expires_at`                  | B-tree                     |
| `sections`           | `uq_sections_slug`                                 | B-tree UNIQUE              |
| `topics`             | `uq_topics_section_id_slug`                        | B-tree UNIQUE              |
| `topics`             | `ix_topics_section_id_is_pinned_updated_at`        | B-tree                     |
| `articles`           | `uq_articles_topic_id_slug`                        | B-tree UNIQUE              |
| `articles`           | `ix_articles_topic_status_published_at`            | B-tree                     |
| `articles`           | `ix_articles_author_id_created_at`                 | B-tree                     |
| `articles`           | `ix_articles_content_gin`                          | GIN `jsonb_path_ops`       |
| `articles`           | `ix_articles_content_tsv`                          | GIN                        |
| `articles`           | `ix_articles_mentioned_user_ids`                   | GIN                        |
| `article_revisions`  | `uq_article_revisions_article_id_revision`         | B-tree UNIQUE              |
| `messages`           | `ix_messages_article_created_at`                   | B-tree                     |
| `messages`           | `ix_messages_parent_created_at`                    | B-tree                     |
| `messages`           | `ix_messages_author_created_at`                    | B-tree                     |
| `messages`           | `ix_messages_path_gist`                            | GiST                       |
| `messages`           | `ix_messages_content_tsv`                          | GIN                        |
| `messages`           | `ix_messages_mentioned_user_ids`                   | GIN                        |
| `message_revisions`  | `uq_message_revisions_message_id_revision`         | B-tree UNIQUE              |
| `article_reactions`  | (PK only)                                          | B-tree                     |
| `message_reactions`  | (PK only)                                          | B-tree                     |
| `saved_articles`     | `ix_saved_articles_user_saved_at`                  | B-tree                     |
| `mentions`           | `ix_mentions_mentioned_created`                    | B-tree                     |
| `mentions`           | `ix_mentions_source`                               | B-tree                     |
| `notifications`      | `ix_notifications_user_unread_created`             | B-tree                     |
| `audit_log`          | `ix_audit_log_actor_created`                       | B-tree                     |
| `audit_log`          | `ix_audit_log_target`                              | B-tree                     |
| `audit_log`          | `ix_audit_log_action_created`                      | B-tree                     |

---

## Enum types

All enums are Postgres-native (`CREATE TYPE ... AS ENUM(...)`), declared
in the first migration of their owning module. SQLAlchemy uses
`sa.Enum(..., name="<name>", create_type=False)` to reference them.

| Name                   | Values                                                                            | Owning module        |
| ---------------------- | --------------------------------------------------------------------------------- | -------------------- |
| `user_role`            | `user`, `moderator`, `admin`, `agent`                                             | `users`              |
| `ban_scope`            | `global`, `section`, `topic`                                                      | `rbac`               |
| `article_status`       | `draft`, `published`, `archived`, `hidden`                                        | `articles`           |
| `message_status`       | `visible`, `edited`, `hidden_by_mod`, `deleted_by_author`                         | `messages`           |
| `reaction_kind`        | `brain`, `synapse`, `neuron`, `microscope`, `dna`, `mindblown`, `petri`, `lightbulb` | `reactions`       |
| `mention_source_type`  | `article`, `message`, `direct_message`                                            | `mentions`           |
| `conversation_kind`    | `dm`, `group`                                                                     | `dm` (deferred)      |
| `ai_proposal_action`   | `fix_typos`, `improve_clarity`, `add_summary`, `translate`, `extend_section`      | `ai_proposals` (def) |
| `ai_proposal_status`   | `pending`, `accepted`, `rejected`, `expired`                                      | `ai_proposals` (def) |
| `llm_provider`         | `openrouter`, `cloud_ru`, `anthropic`, `openai`, `local`                          | `agents` (deferred)  |
| `llm_status`           | `ok`, `error`, `timeout`, `rate_limited`                                          | `agents` (deferred)  |
