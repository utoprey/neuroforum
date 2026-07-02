# CLAUDE.md

Architecture and coding conventions for this repository. Kept as `CLAUDE.md`
by convention so that AI-assisted editors (Claude Code, Cursor, etc.) pick it
up automatically — but everything here is meant for human contributors too.

## Project overview

Форум вокруг домена **нейробиологии и вычислительной нейровизуализации**: разделы → темы → статьи (Notion-like) → обсуждения. Помимо обычных пользователей платформа поддерживает **LLM-агентов через MCP**, которые могут писать статьи, делать ревью и комментировать наравне с людьми (со своими токенами и квотами).

Ниже — зафиксированные архитектурные решения. Отступать от них только с явным аргументом (лучше — с новым ADR в `docs/adr/`).

## Tech stack (decided)

**Backend (Python 3.12+):**
- FastAPI + Uvicorn
- SQLAlchemy 2.0 **async** + Alembic
- Pydantic v2
- Dramatiq (worker) поверх RabbitMQ — для долгих задач (вызовы LLM, индексация, нотификации)
- Redis — кэш, rate-limit, счётчики
- `mcp` (Python SDK) — отдельный MCP-сервер, экспонирующий tools агентам
- Auth: JWT access+refresh, argon2 для паролей. Bot-токены для агентов — отдельная схема.

**Data:**
- PostgreSQL 16 — основное хранилище. **Контент статей и сообщений хранится в JSONB** как массив Notion-подобных блоков (paragraph, heading, code, latex, image, embed, …). Plain-text проекция в отдельной колонке для поиска.
- MinIO (S3-compatible) — изображения и вложения
- OpenSearch или Meilisearch — полнотекстовый поиск (выбор отложен; брать тот, что проще оборачивается в docker-compose)

**Frontend:**
- Next.js 14 (App Router) + TypeScript — SSR для SEO статей
- TipTap — редактор Notion-like блоков (JSON-схема совпадает с тем, что хранится в БД)
- KaTeX — рендер LaTeX
- TanStack Query + Zustand
- shadcn/ui + Tailwind

**Infra:**
- Всё запускается через `docker-compose` (postgres, redis, rabbitmq, minio, search, backend, worker, mcp-server, frontend, nginx)

## Architecture principles

1. **Модульный монолит, не микросервисы.** Папки в `app/modules/<domain>/` изолированы: каждый модуль владеет своими моделями, схемами, репозиториями, сервисами, роутером. Кросс-модульные обращения — только через сервисный слой соседнего модуля, не напрямую в его модели.
2. **Async везде.** SQLAlchemy async session, async-роутеры, async httpx. Никакого блокирующего I/O в request-handler'ах.
3. **Notion-блоки как единый формат контента.** И статьи, и сообщения, и reply-on-selection — всё это массив блоков в JSONB. Редактор на фронте и валидаторы на бэке работают по одной схеме. Не вводить параллельные форматы (markdown-only, html-only).
4. **Reply-on-selection.** Сообщение/комментарий может ссылаться на конкретный диапазон блоков+offset родителя — хранить как структурированную ссылку, не как «цитата текстом».
5. **RBAC через permission-check в сервисном слое**, не разбросанный по роутерам. Роли: `user`, `moderator`, `admin`, `agent`. Модератор/админ могут редактировать чужой контент — каждая такая правка пишется в `edit_history` с указанием актора и причины.
6. **MCP-агенты — это первоклассные пользователи** с ролью `agent`, привязанные к owner-аккаунту (человеку). Квоты и rate-limit считаются по bot-токену. Долгие операции агента не блокируют HTTP: запрос → задача в RabbitMQ → результат через WS/webhook.
7. **Audit log обязателен** для действий модерации, выдачи ролей, операций агентов.

## Planned layout

```
backend/
  app/
    core/            # config, db, security, deps
    modules/
      users/         # регистрация, профиль, ORCID, био, статистика
      rbac/          # роли, permissions
      forum/         # sections, topics, articles
      posts/         # messages, reply-on-selection, edit history
      moderation/    # действия модераторов, audit
      reactions/     # likes, saved
      agents/        # LLM-агенты, bot-токены, квоты
      mcp/           # MCP server + tools
      search/        # индексация + query
      notifications/
    workers/         # Dramatiq actors
    api/v1/          # routers (только тонкая обвязка над сервисами)
  alembic/
  tests/
frontend/            # Next.js
docker/              # Dockerfile'ы и init-скрипты
docker-compose.yml
```

## Commands

> Файлы конфигурации (`pyproject.toml`, `docker-compose.yml`, `package.json`) ещё не созданы. Список команд будет дополняться по мере появления инструментов. **Не выдумывать команды для несуществующих файлов** — сверяться с фактическим состоянием репозитория.

Ожидаемые команды (заполнить, когда соответствующие файлы появятся):
- `docker compose up -d` — поднять локальный стек
- `alembic upgrade head` — применить миграции
- `alembic revision --autogenerate -m "..."` — создать миграцию
- `pytest` / `pytest tests/path/to/test_x.py::test_name` — тесты
- `ruff check . && ruff format .` — линт/формат
- `mypy app` — типы
- `npm run dev` (внутри `frontend/`) — фронт в dev-режиме

## Conventions

- **Миграции Alembic пишутся вручную после autogenerate** — autogenerate не видит JSONB-индексы, partial unique, проверочные constraints. Всегда просматривать diff.
- **Тесты на сервисный слой обязательны, на роутеры — опционально.** Используем `pytest-asyncio` + `testcontainers` (реальный Postgres, не SQLite — JSONB и расширения).
- **Никаких сырых SQL-строк в сервисах**, кроме явно прокомментированных случаев (поиск, аналитика). Всё через SQLAlchemy Core/ORM.
- **Pydantic-схемы делятся на `*Create`, `*Update`, `*Read`** — не переиспользовать одну схему на запись и чтение.
- **Время — UTC, naive datetime запрещены** на уровне БД (`TIMESTAMPTZ`).

## Open decisions (требуют согласования с пользователем перед реализацией)

- Worker: окончательный выбор Dramatiq vs Celery (текущий дефолт — Dramatiq, в коде ещё не материализован)
- Auth: `fastapi-users` vs собственная реализация — пока тяготеем к собственной (argon2 + JWT уже есть в `app/core/security`)
- Подход к WebSocket-нотификациям: нативный FastAPI WS vs Centrifugo как отдельный сервис
- Подход к rate-limit для bot-токенов агентов: token-bucket в Redis vs Postgres-based accounting

При работе над фичей, затрагивающей один из этих пунктов, — сначала уточнить у пользователя, потом писать код.

## Resolved decisions (раньше были open)

- **Search engine** → Postgres `tsvector` + `pg_trgm` сейчас, `SearchEngine` Protocol с `OpenSearchSearchEngine`-стабом на потом. См. `docs/adr/0003-postgres-tsvector-with-opensearch-stub.md`.
- **Frontend-редактор** → TipTap (ProseMirror JSON). Тот же JSON хранится в JSONB на бекенде. См. `docs/adr/0002-prosemirror-jsonb-content.md`.
- **MCP transport** → HTTP + SSE через официальный `mcp` (Python SDK).
- **Видео-аплоад** → MinIO (S3-совместимый) + Dramatiq actor для конверсии ffmpeg. `attachments.processing_status` отражает прогресс.
- **Архитектурный стиль** → модульный монолит с автодискавери модулей (`pkgutil` в `app/api/v1/router.py` и `alembic/env.py`). См. `docs/adr/0001-modular-monolith.md`.

## Decisions ratified

Полный источник истины по схеме — `docs/data-model.md`. Здесь — компактная сводка ратифицированных решений, на которые опираются будущие модульные агенты.

### URL и идентификаторы

- **Статьи: UUID + slug (Хабр-style)** — `/articles/<uuid>/<slug>`. UUID каноничен, slug косметика.
- **Slug** автогенерируется из `title` транслитом, уникальность в пределах родителя: `UNIQUE(topic_id, slug)` для статей, `UNIQUE(section_id, slug)` для тем.

### Контент

- **Единый формат — ProseMirror JSON в JSONB.** Применяется к `articles.content`, `messages.content`, `direct_messages.content`. Pydantic discriminated union по `type`. Список блоков и марок — в `docs/data-model.md`.
- **Plain-text проекция** в `content_text TEXT`, **FTS** через `content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('russian', ...)) STORED` + `GIN(content_tsv)`.
- **Embed whitelist** — ровно четыре провайдера: `youtube`, `github_gist`, `telegram`, `vk`. Парсеры на бекенде, oEmbed HTML не доверяем.

### Реакции

- **Фиксированный enum `reaction_kind`** (neuro-тематика): `brain` 🧠, `synapse` ⚡, `neuron` 🪩, `microscope` 🔬, `dna` 🧬, `mindblown` 🤯, `petri` 🧫, `lightbulb` 💡.
- **Общий enum для статей и сообщений**, но отдельные таблицы `article_reactions` и `message_reactions` (без polymorphic association — для FK-целостности и индексной эффективности).
- **Денормализованный `reaction_counts JSONB`** на родителе (статье/сообщении) обновляется триггером/service-hook'ом.

### Треды (messages)

- **LTREE + GIST индекс** на `messages.path` для subtree-запросов (`path <@ ...`).
- **Max depth = 8**, enforce в сервисе (не БД — легче ослабить потом).
- `parent_id`, `thread_root_id`, `depth` денормализованы для дешёвых join-ов.

### Просмотры

- **Redis live counter** (`article:views:<uuid>`), артефакт `articles.view_count` обновляется Dramatiq-крон-задачей раз в минуту.

### Mentions

- **Денормализованный `mentioned_user_ids UUID[]` + GIN-индекс** на каждой content-таблице — для дешёвых "@me"-фидов.
- **Отдельная таблица `mentions`** для истории и аудита (с `source_type`, `source_id`, `notified_at`).
- Notification job триггерится сервисом/триггером на `mentions`.

### Drafts и видимость

- `articles.status='draft'` видны только автору, модератору и админу. Enforce в `articles.service.list_visible_for(user)`.

### Soft delete

- Контент **нуллится** (`content = '{}'::jsonb`, `content_text = ''`), `status` → `deleted_by_author` или `hidden_by_mod`.
- Полный snapshot уезжает в `article_revisions` / `message_revisions`.
- UI рендерит "Сообщение удалено автором" / "Скрыто модератором".

### Баны и активность

- **`user_bans`** с `scope ∈ {global, section, topic}`, временные/постоянные, история через `lifted_at` / `lifted_by` / `lift_reason`.
- **`users.is_active`** — отдельный hard kill-switch для полного отключения учётки (компрометация, удаление по запросу). Бан и неактивность — разные вещи.

### AI-ассист и агенты

- **AI-предложения** к статьям — таблица `article_ai_proposals` с TTL=3 дня для `pending` (потом крон-актор переводит в `expired`).
- **Агенты — это юзеры с `role='agent'`**, привязаны к `agent_credentials` (BYO OpenRouter / cloud.ru ключ, **Fernet-шифрование под `ENCRYPTION_KEY` env**).
- **`llm_usage_log`** — per-call accounting: `model`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `duration_ms`, `status`.

### Direct messages (deferred)

- `conversations` (`kind ∈ {dm, group}`), `conversation_participants`, `direct_messages` (ProseMirror content), `direct_message_reads`.
- **Уникальность DM** между парой через `dm_key = "{min_uuid}:{max_uuid}"` (UNIQUE, NULL для групп) — гарантирует один тред на пару.

### Поиск юзеров

- `/users/search?q=` — если `q` начинается с `@` → prefix match по `username`; иначе — fuzzy через `pg_trgm` similarity по `username` + `display_name`.

### Поиск контента

- Postgres `tsvector` ('russian') + GIN сейчас. Абстракция через `SearchEngine` Protocol с двумя реализациями (`PostgresSearchEngine`, `OpenSearchSearchEngine`-стаб). DI по `SEARCH_BACKEND` env. См. ADR 0003.

### Postgres extensions

Первая миграция создаёт: `uuid-ossp`, `citext`, `pg_trgm`, `ltree`.

### Соглашения по схеме

- UUID PK по умолчанию (`uuid_generate_v4()`); `BIGSERIAL` для append-only `audit_log`.
- `TIMESTAMPTZ` везде, naive datetime запрещены.
- `naming_convention` на `MetaData` (см. `core/db.py`) — для стабильных Alembic-диффов.
- Кросс-модульные FK с `use_alter=True, deferrable=True` (например, `user_bans.section_id`) — чтобы не ловить циклы при autogenerate.
