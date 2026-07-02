# Neuroforum — frontend

Next.js 15 (App Router) + TypeScript frontend для форума по нейробиологии и нейровизуализации. TipTap-редактор для Notion-подобных блоков, KaTeX для формул, TanStack Query + Zustand для состояния, shadcn/ui + Tailwind для UI. Бэкенд: FastAPI на `http://localhost:8000/api/v1`.

## Commands

```bash
pnpm install          # установить зависимости
pnpm dev              # dev-сервер на http://localhost:3000
pnpm build            # production build
pnpm start            # запустить production build
pnpm lint             # ESLint
pnpm typecheck        # tsc --noEmit
pnpm format           # Prettier
```

Скопируй `.env.example` в `.env.local` и при необходимости поправь `NEXT_PUBLIC_API_URL`.

## E2E (Playwright)

```bash
pnpm e2e:install      # один раз: скачать chromium (нужен сетевой доступ)
pnpm e2e              # запустить все тесты из ./e2e
```

Тесты ожидают, что:

- Бэкенд поднят на `http://localhost:8000` (FastAPI, prefix `/api/v1`).
- Фронт на `http://localhost:3000` (`pnpm dev` / `pnpm start`).
- Postgres мигрирован (`alembic upgrade head`).
- Для сценария создания раздела и темы существует пользователь `admin` с
  ролью `admin` (см. инструкции в `e2e/smoke.spec.ts`).

Сейчас тесты не запускаются автоматически — это делает финальный smoke-агент.

## Структура

- `src/app/` — App Router-страницы (`/`, `/login`, `/register`, `/profile`, `/sections`, `/sections/[slug]/topics`, `/topics/[id]/articles`, `/topics/[id]/articles/new`, `/articles/[id]`).
- `src/components/editor/` — TipTap-обвязка + `math` node (KaTeX).
- `src/components/comments/` — рекурсивный thread под статьёй.
- `src/components/reactions/` — кнопки-реакции (8 нейро-emoji).
- `src/components/search/` — debounced search-bar в шапке.
- `src/components/notifications/` — bell с unread-count.
- `src/lib/api.ts` — `ky`-инстанс с auth-хедером + парсингом ошибок FastAPI.
- `src/lib/auth-store.ts` — Zustand-стор для access/refresh токенов и cached user.
- `src/lib/types.ts` — TS-аналоги Pydantic-схем бэкенда.
