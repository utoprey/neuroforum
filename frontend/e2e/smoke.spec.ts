import { expect, test } from '@playwright/test'

/**
 * Smoke e2e for the MVP. Assumes the full docker stack is up and the
 * database has been migrated.
 *
 * Backend API base URL: ``process.env.E2E_API_URL`` (default
 * ``http://localhost:8000``). The frontend is reached via Playwright's
 * ``baseURL`` (default ``http://localhost:3000``).
 *
 * The "admin" scenario requires an admin user. We create it via API; if
 * the resulting account isn't ``role='admin'`` (we can't elevate via the
 * public API), the test is marked skipped with a clear message — bump
 * the role out-of-band and re-run:
 *
 *   docker compose exec postgres \
 *     psql -U forum -d forum -c "UPDATE users SET role='admin' WHERE username='admin'"
 */

const ts = Date.now()
const API_URL = process.env.E2E_API_URL ?? 'http://localhost:8000'

const ALICE = {
  username: `alice_${ts}`,
  email: `alice_${ts}@example.com`,
  password: 'correcthorsebatterystaple',
}

const ADMIN = {
  username: 'admin',
  email: 'admin@example.com',
  password: 'correcthorsebatterystaple',
}

test.describe('auth flow', () => {
  test('register → auto-login → profile is shown', async ({ page }) => {
    await page.goto('/register')
    await page.getByLabel('Имя пользователя').fill(ALICE.username)
    await page.getByLabel('Email').fill(ALICE.email)
    await page.getByLabel('Пароль', { exact: true }).fill(ALICE.password)
    await page.getByLabel('Подтверждение пароля').fill(ALICE.password)
    await page.getByRole('button', { name: /создать аккаунт/i }).click()
    await page.waitForURL('**/profile')
    await expect(page.getByTestId('header-username')).toHaveText(ALICE.username)
  })

  test('logout → login again', async ({ page }) => {
    await page.goto('/register')
    await page.getByLabel('Имя пользователя').fill(ALICE.username + '2')
    await page.getByLabel('Email').fill('2_' + ALICE.email)
    await page.getByLabel('Пароль', { exact: true }).fill(ALICE.password)
    await page.getByLabel('Подтверждение пароля').fill(ALICE.password)
    await page.getByRole('button', { name: /создать аккаунт/i }).click()
    await page.waitForURL('**/profile')

    await page.getByRole('button', { name: /выйти/i }).click()
    await page.waitForLoadState('networkidle')

    await page.goto('/login')
    await page
      .getByLabel('Имя пользователя или email')
      .fill(ALICE.username + '2')
    await page.getByLabel('Пароль').fill(ALICE.password)
    await page.getByRole('button', { name: /войти/i }).click()
    await page.waitForURL('**/profile')
  })
})

test.describe('sections + topics + articles (admin)', () => {
  test('admin creates section → topic → article → publish → comment → react → save', async ({
    page,
    request,
  }) => {
    // 1. Ensure ADMIN exists — try login, register if needed. The role
    //    elevation is out-of-band (see file header). All API calls go
    //    directly to the backend (not via Playwright baseURL=frontend).
    let loginResp = await request.post(`${API_URL}/api/v1/auth/login`, {
      data: {
        username_or_email: ADMIN.username,
        password: ADMIN.password,
      },
      failOnStatusCode: false,
    })
    if (!loginResp.ok()) {
      await request.post(`${API_URL}/api/v1/users/`, {
        data: {
          username: ADMIN.username,
          email: ADMIN.email,
          password: ADMIN.password,
        },
        failOnStatusCode: false,
      })
      loginResp = await request.post(`${API_URL}/api/v1/auth/login`, {
        data: {
          username_or_email: ADMIN.username,
          password: ADMIN.password,
        },
        failOnStatusCode: false,
      })
    }
    if (!loginResp.ok()) {
      test.skip(true, 'admin login failed — bump role to admin first')
      return
    }
    const tokenJson = await loginResp.json()
    const adminToken: string = tokenJson.access_token

    // 2. Check the role is actually admin. We probe by trying to create a
    //    throwaway section; if forbidden, the bump didn't happen yet.
    const probeSlug = `e2e-probe-${ts}`
    const probe = await request.post(`${API_URL}/api/v1/sections`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        title: `Probe ${ts}`,
        slug: probeSlug,
        description: 'role probe',
      },
      failOnStatusCode: false,
    })
    if (probe.status() === 403 || probe.status() === 401) {
      test.skip(
        true,
        'admin user has role=user — run "UPDATE users SET role=\'admin\' WHERE username=\'admin\'" and re-run',
      )
      return
    }

    // 3. Log in via the UI (so the access token lands in localStorage).
    await page.goto('/login')
    await page.getByLabel('Имя пользователя или email').fill(ADMIN.username)
    await page.getByLabel('Пароль').fill(ADMIN.password)
    await page.getByRole('button', { name: /войти/i }).click()
    await page.waitForURL('**/profile')

    // 4. Create the actual section we'll work in (via API).
    const sectionSlug = `e2e-${ts}`
    await request.post(`${API_URL}/api/v1/sections`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        title: `E2E ${ts}`,
        slug: sectionSlug,
        description: 'e2e seed',
      },
      failOnStatusCode: false,
    })

    // 5. Browse to the section, create a topic via UI (mod/admin only).
    await page.goto(`/sections/${sectionSlug}/topics`)
    await page.getByTestId('create-topic-button').click()
    await page.getByLabel('Название').fill(`Topic ${ts}`)
    await page.getByLabel(/описание/i).fill('seed topic')
    await page.getByRole('button', { name: /^создать$/i }).click()
    await page.waitForURL(/\/topics\/[a-f0-9-]+\/articles$/)

    // 6. Write and publish an article.
    await page.getByTestId('new-article-button').click()
    await page.getByTestId('article-title').fill(`Article ${ts}`)
    await page.locator('.ProseMirror').click()
    await page.keyboard.type('Hello from Playwright')
    await page.getByTestId('publish-article-button').click()
    await page.waitForURL(/\/articles\/[a-f0-9-]+$/)

    // 7. Save + react.
    await page.getByTestId('save-article-button').click()
    await page.getByTestId('reaction-brain').click()

    // 8. Leave a top-level comment.
    await page.getByTestId('open-comment-composer').click()
    await page.locator('.ProseMirror').last().click()
    await page.keyboard.type('Nice piece!')
    await page.getByTestId('submit-comment').click()
    await expect(page.getByText('Nice piece!')).toBeVisible()
  })
})

test.describe('home page', () => {
  test('shows section grid (or empty state)', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: /разделы/i })).toBeVisible()
  })
})
