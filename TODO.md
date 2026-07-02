# Roadmap / known limitations

Honest list of what's incomplete or would be redone in a v2. Kept here (rather than in issues) so a first-time reader can size the project at a glance.

## Missing features

### Editor
- [ ] Slash-menu (`/` to insert block) — TipTap `Suggestion` extension, not wired
- [ ] Real image upload to MinIO from editor (backend is ready; frontend hook still uses external URLs for seed data)
- [ ] Mention autocomplete (`@` picks a user) — parser + backend `mentions` module exist, UI trigger doesn't
- [ ] Reply-on-selection UI — schema stores `{block_path, from, to}` but frontend can't produce it yet

### Real-time
- [ ] WebSocket notifications and DM delivery — currently polling (30s for DM, 60s for notifications)
- [ ] Presence beyond `last_seen_at` heuristic (green dot on 5-min bump)

### Media
- [ ] Video processing worker (`process_video` is a Dramatiq stub — no ffmpeg wired)
- [ ] GIF-specific renderer (currently rendered as `<img>` via a dedicated node — animates natively but no autoplay control)

### Search
- [ ] Swap `PostgresSearchEngine` for OpenSearch when the FTS ranking gets thin (`SearchEngine` protocol + stubbed `OpenSearchSearchEngine` are already there)
- [ ] Frontend search UX: type-ahead for users, filter chips, "did-you-mean" suggestions

### Agents / MCP
- [ ] Per-token rate limit (Redis token-bucket keyed on `agent_tokens.id`)
- [ ] Bot-token TTL / `expires_at` (currently manual `revoked_at` only)
- [ ] cloud.ru LLM provider (`llm_proxy.py` — only OpenRouter is implemented)
- [ ] UI page `/me/agents` to manage bots and their tokens (currently `/me/credentials` covers only the API keys)

### Deferred modules
None left from the original spec — `attachments`, `dm`, `agents`, `ai_proposals`, `embeds`, `imports` are all shipped. The list above is v2 polish, not scope debt.

## Infra / DX

- [ ] HTTPS in production (currently plain HTTP on VPS ports 3000/8000 — needs Caddy + Let's Encrypt or a reverse proxy)
- [ ] CI matrix for backend + frontend (only smoke lint/typecheck wired via `.github/workflows/ci.yml`)
- [ ] Frontend Docker build under QEMU is painfully slow — needs a self-hosted runner or a `linux/amd64` builder cache
- [ ] Health checks for the `worker` and `mcp-server` containers (they inherit the `backend`'s `/healthz` curl, which those processes don't serve)
- [ ] Backup strategy for Postgres + MinIO
- [ ] Structured log shipping (Loki / OpenObserve / etc.)
- [ ] Sentry for error tracking

## Testing gaps

- [x] Backend unit + integration (~335 tests, 2 xfail documented, testcontainers Postgres)
- [x] Playwright e2e for AI review + toolbar + smoke happy path
- [ ] Load testing (Locust / k6) — never run
- [ ] Chaos scenarios (killing a container mid-request) — never tried
- [ ] Backend tests currently need `TESTS_USE_ALEMBIC=1` to catch GENERATED tsvector regressions; default runs use `create_all`

## Security hardening for a real deploy

If this were to actually host public content it would need:

- [ ] Rate limit on `/auth/login` and `/users` (registration) — currently open, brute-forceable
- [ ] Email verification loop (registration allows any address today)
- [ ] Password strength requirements (min 8 chars is loose; no complexity check)
- [ ] CSRF for cookie-based flows (currently we're JWT-in-header so it's moot, but if a cookie flow gets added…)
- [ ] Actual secret rotation for `SECRET_KEY` and `ENCRYPTION_KEY` (Fernet mater-key rotation isn't implemented — you'd have to re-encrypt every credential row)
- [ ] Content moderation queue (right now anything published is live immediately)

## Deferred UX

- [ ] "Восстановить пароль" (password reset over email)
- [ ] Public profile customization: cover image, pinned articles
- [ ] Diff view for article revisions (currently expand/collapse full snapshot)
- [ ] Draft autosave with local storage
- [ ] Keyboard shortcuts (`?` overlay)
- [ ] i18n — hardcoded Russian throughout the frontend
