import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright config for Neuroforum e2e tests.
 *
 * Tests assume:
 *   - Backend at  http://localhost:8000  (FastAPI app, /api/v1 prefix)
 *   - Frontend at http://localhost:3000  (`pnpm dev` or `pnpm start`)
 *   - Postgres / Redis migrated (alembic upgrade head)
 *
 * Bring the stack up via `docker compose up -d` (see project root) before
 * running. Tests are NOT yet wired to start the stack themselves.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    trace: 'on-first-retry',
    locale: 'ru-RU',
    timezoneId: 'UTC',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
