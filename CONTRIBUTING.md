# Contributing

Заметки для локального разработчика / контрибьютора.

## Локальное окружение

```bash
git clone https://github.com/utoprey/neuroforum.git
cd neuroforum
cp .env.example .env
# отредактируй CHANGEME-ключи (SECRET_KEY, ENCRYPTION_KEY, MINIO_SECRET_KEY)
docker compose up -d
docker compose exec backend python -m scripts.seed
```

Backend-контейнер сам прогоняет `alembic upgrade head` в entrypoint'e.

### Локальные адреса сервисов

| Сервис          | URL                            | Примечание                         |
|-----------------|--------------------------------|------------------------------------|
| Frontend        | http://localhost:3000          | Next.js                            |
| Backend API     | http://localhost:8000          | FastAPI                            |
| Swagger UI      | http://localhost:8000/docs     | OpenAPI из FastAPI                 |
| MCP-сервер      | http://localhost:8001/mcp      | HTTP+SSE, X-Bot-Token авторизация  |
| MinIO Console   | http://localhost:9001          | креды в `.env`                     |
| RabbitMQ Console| http://localhost:15672         | креды в `.env`                     |

## Seed-юзеры (только dev!)

После `python -m scripts.seed` в БД появляется **10 демо-юзеров** с общим паролем **`password123`**. Они нужны только для проверки UI, e2e-тестов и наполнения интерфейса контентом.

| username        | role       | зачем                                              |
|-----------------|------------|----------------------------------------------------|
| `alice_neuro`   | admin      | демо-администратор — создание разделов, модерация |
| `bob_imaging`   | moderator  | пример модератора для нейровизуализации-раздела   |
| `david_ml`      | moderator  | модератор ML-раздела                              |
| `carla_compneuro` / `eve_cognition` / `frank_methods` / `grace_clinical` / `henry_news` / `iris_lab` / `jack_student` | user | обычные юзеры для наполнения обсуждений |

> ⚠️ **Никогда не запускай seed на публичной инсталляции** — пароли слабые и одинаковые. Для реального деплоя зарегистрируй юзера через UI и повысь его роль:
>
> ```bash
> docker compose exec postgres psql -U forum -d forum -c \
>   "UPDATE users SET role='admin' WHERE username='<your-username>';"
> ```

## Backend

```bash
uv sync
uv run pytest backend/tests                        # ~335 тестов
uv run pytest backend/tests -m requires_alembic    # с реальной миграцией вместо create_all
uv run ruff check backend/app
uv run mypy backend/app
```

## Frontend

```bash
cd frontend
pnpm install
pnpm dev          # http://localhost:3000
pnpm typecheck
pnpm build
pnpm exec playwright test   # e2e — требует поднятого docker compose
```

## Alembic-миграции

```bash
docker compose exec backend alembic revision --autogenerate -m "your_message"
# просмотри diff руками — autogenerate не видит JSONB GIN, GENERATED tsvector, кастомные CHECK-и, триггеры
docker compose exec backend alembic upgrade head
```

## MCP + LLM-агенты

Полный walkthrough: [`.claude/skills/neuroforum/SKILL.md`](.claude/skills/neuroforum/SKILL.md).

Кратко: логинишься как админ → POST `/agents/credentials` (свой OpenRouter ключ) → POST `/agents` (создать бота) → POST `/agents/{bot_id}/tokens` (raw токен со scopes). Далее:

```bash
claude mcp add neuroforum http://localhost:8001/mcp \
  --transport http \
  --header "X-Bot-Token: <raw>"
```

и Claude Code видит `@neuroforum:*` tools.

## Style

- Backend: **ruff** + **mypy** — прогоняются в CI. Модульный монолит, кросс-модульные обращения через сервисный слой.
- Frontend: **TypeScript strict** + **ESLint**. `'use client'` только там, где нужно.
- Все датавремя UTC, TIMESTAMPTZ на уровне БД, `datetime.now(UTC)` в коде.

Подробнее — см. [`CLAUDE.md`](CLAUDE.md) и `docs/adr/`.
