# ADR 0003 — Postgres `tsvector` for search now, OpenSearch-shaped Protocol for later

- **Status:** Accepted
- **Date:** 2026-06-21
- **Deciders:** project owner + Claude
- **Supersedes:** —

## Context

We need full-text search across:

- **Articles** — long-form, mostly Russian, occasional English.
- **Messages** — short to medium, same language profile.
- **Users** — search by `@username` (exact / prefix) and by
  `display_name` (fuzzy).

Search demand at MVP is unknown but small (single-digit QPS expected
in the first months). The downside of adding a second datastore on day
one is non-trivial:

- Another container in `docker-compose` to keep healthy.
- A separate indexing pipeline (cron / changefeed / Dramatiq actor).
- Reindex-from-scratch dance on schema changes.
- Operational headache that the team (1–2 humans) doesn't need yet.

But we also don't want to *paint ourselves into a corner*: if scale or
relevance demands a real search engine later, the swap should be a
configuration change, not a rewrite.

## Decision

**Use Postgres for full-text search at MVP, behind a `SearchEngine`
Protocol that already has an OpenSearch stub.**

### Storage shape

Every content-bearing table (`articles`, `messages`, eventually
`direct_messages`) carries:

```sql
content_text  TEXT NOT NULL DEFAULT '',
content_tsv   TSVECTOR
              GENERATED ALWAYS AS (to_tsvector('russian',
                                               coalesce(content_text,'')))
              STORED,
```

Indexed with `GIN(content_tsv)`. The Russian dictionary handles the
majority of forum traffic; mixed Russian/English text is good enough
because Postgres falls back to default token handling for non-Russian
tokens — relevance is mediocre but recall is fine.

For username / display-name search we use the `pg_trgm` extension with
`GIN(... gin_trgm_ops)` indexes:

- `ix_users_username_trgm` — fuzzy `username`
- `ix_user_profiles_display_name_trgm` — fuzzy `display_name`

Plus a `@`-prefix special case (B-tree LIKE) — see
`docs/data-model.md` § users.

### Protocol abstraction

```python
class SearchEngine(Protocol):
    async def index_article(self, article_id: UUID) -> None: ...
    async def index_message(self, message_id: UUID) -> None: ...
    async def remove_article(self, article_id: UUID) -> None: ...
    async def remove_message(self, message_id: UUID) -> None: ...
    async def search(
        self,
        q: str,
        *,
        kind: Literal["article", "message", "user"],
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResults: ...
```

Two implementations live in `app/modules/search/`:

- `PostgresSearchEngine` — actually queries `content_tsv` with
  `plainto_tsquery('russian', :q)` ranked by `ts_rank_cd`. For users,
  combines the `@`-prefix path with trigram `similarity()`. The
  `index_*` / `remove_*` methods are no-ops because the `tsvector`
  column is `GENERATED` — Postgres maintains it automatically.
- `OpenSearchSearchEngine` — every method raises
  `NotImplementedError("OpenSearch backend not yet implemented")`.
  Exists so the Protocol is concretely typed and so DI wiring is
  ready when we flip the switch.

DI picks one based on env:

```python
# app/core/deps.py (sketch)
SEARCH_BACKEND = settings.SEARCH_BACKEND  # "postgres" | "opensearch"

def get_search_engine() -> SearchEngine:
    if SEARCH_BACKEND == "postgres":
        return PostgresSearchEngine(...)
    if SEARCH_BACKEND == "opensearch":
        return OpenSearchSearchEngine(...)
    raise RuntimeError(f"Unknown SEARCH_BACKEND={SEARCH_BACKEND!r}")
```

Callers (services, MCP tools) depend on the Protocol, not the
concrete class.

## Consequences

### Positive

- **One datastore at MVP.** No extra container, no indexing pipeline,
  no reindex-from-scratch ceremony. Schema changes are
  Alembic-and-done.
- **Good enough for the use case.** Russian dictionary + GIN(tsvector)
  comfortably handles thousands of articles and tens of thousands of
  messages with sub-100 ms query latency.
- **Trigram username search is excellent out of the box.** `pg_trgm`
  with GIN beats anything bolted onto OpenSearch for short-string
  fuzzy match.
- **Future swap is a config change.** Because services depend on the
  Protocol and the OpenSearch backend already has a class skeleton,
  introducing OpenSearch is "implement five methods + flip env var"
  rather than "rewrite the search layer".
- **No drift between source of truth and index** at MVP, because the
  `tsvector` is a `GENERATED STORED` column — Postgres updates it
  inside the same transaction as the row, so it's atomically
  consistent.

### Negative

- **Relevance ranking is primitive.** `ts_rank_cd` doesn't do BM25
  properly, doesn't learn from clicks, can't do field boosting beyond
  what we express manually in the tsvector expression. Acceptable
  while corpus is small; if users start complaining about ranking
  quality, that's the signal to swap.
- **Mixed Russian/English text is imperfect.** Postgres can use only
  one dictionary per `to_tsvector` call. We chose `'russian'` because
  most content will be Russian. English-only articles will still be
  found by exact tokens but won't be stemmed correctly.
- **No fuzzy search on long content.** `pg_trgm` works great on short
  strings but is too expensive on full articles. Users searching for
  "neuroplasticity" with a typo will not find an article that contains
  "neuroplastisity". OpenSearch's fuzzy / phonetic analyzers would
  solve this.
- **Aggregations / facets are clunky** in Postgres compared to
  OpenSearch's aggregation framework. We don't need them yet; if we
  add tag clouds or "top sections by hits" later, that's another
  pressure to swap.

### Neutral

- We pay for the abstraction layer (Protocol + DI) upfront. The cost
  is a few dozen lines of code and a thin discipline rule ("services
  depend on the Protocol"). Cheap insurance.

## Alternatives considered

### OpenSearch from day one

Rejected. The operational and code burden (separate indexing pipeline,
reindex tooling, version-skew handling) is not worth it before we have
data showing Postgres FTS is the bottleneck. The Protocol means we
don't lose the option.

### Meilisearch

Rejected as the *default* but kept as an option. Easier to operate
than OpenSearch and has excellent typo tolerance, but has weaker
relevance tuning and a smaller ecosystem. If at swap-time we still
want lightweight tooling, Meilisearch can drop in behind the same
`SearchEngine` Protocol with minimal extra work.

### Elasticsearch

Rejected. Heavyweight; license drama; OpenSearch covers the same use
cases and is the modern open-source path.

### `pgroonga` (Postgres extension for fast FTS)

Rejected. Better relevance than `tsvector` but adds a non-standard
extension that complicates docker-compose, hosted Postgres options
(RDS, Neon, etc.), and DBA tooling. Postgres built-ins suffice at MVP.

## Migration triggers (when to actually swap)

We swap to OpenSearch (or Meilisearch) when **any one** of these is
true:

- p95 search latency > 500 ms with a corpus under 100k articles
- Users repeatedly report bad ranking and we've exhausted reasonable
  `ts_rank_cd` tuning
- We need cross-language search (English + Russian + others) where the
  single-dictionary limitation actually bites
- We need typo-tolerant fuzzy search on long content
- We need rich faceting / aggregations the SQL path can't deliver
  cleanly

Until then: Postgres.

## References

- `docs/data-model.md` § Module: search
- `docs/data-model.md` § Module: users (search semantics)
- Postgres FTS docs: <https://www.postgresql.org/docs/16/textsearch.html>
- `pg_trgm`: <https://www.postgresql.org/docs/16/pgtrgm.html>
