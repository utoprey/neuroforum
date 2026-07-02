import { expect, test } from '@playwright/test'

/**
 * E2E for the dedicated "🤖 AI обзоры" section.
 *
 * Flow:
 *   1. Log in as alice_neuro (article author).
 *   2. Cleanup any pending proposals on her first article so the panel is
 *      deterministic across reruns.
 *   3. Create a fresh proposal via API, then immediately accept it via API
 *      (the accept-side UI is exercised elsewhere — here we only assert that
 *      an accepted proposal renders in the dedicated section with Markdown
 *      treated as Markdown, not as literal text).
 *   4. Open the article page; expect the AI обзоры section + content block.
 *
 * Auth is bootstrapped the same way as `ai-review.spec.ts` — by writing the
 * `neuroforum-auth` localStorage entry the zustand store reads on first load.
 */

const BACKEND = process.env.E2E_API_URL ?? 'http://localhost:8000'
const FRONTEND = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000'

test('accepted AI proposal appears in dedicated AI обзоры section with markdown rendering', async ({
  page,
  request,
}) => {
  const loginResp = await request.post(`${BACKEND}/api/v1/auth/login`, {
    data: { username_or_email: 'alice_neuro', password: 'password123' },
    failOnStatusCode: false,
  })
  if (!loginResp.ok()) {
    throw new Error(
      `login failed (HTTP ${loginResp.status()}): ${await loginResp.text()}`,
    )
  }
  const { access_token, refresh_token } = await loginResp.json()
  const auth = { Authorization: `Bearer ${access_token}` }

  const artsResp = await request.get(
    `${BACKEND}/api/v1/users/alice_neuro/articles?limit=1`,
  )
  expect(artsResp.ok()).toBeTruthy()
  const arts = (await artsResp.json()) as { id: string }[]
  if (!Array.isArray(arts) || arts.length === 0) {
    throw new Error('no articles for alice — re-run demo seed')
  }
  const aid = arts[0].id

  // Cleanup any existing pending proposals so we get a deterministic count.
  const pendingResp = await request.get(
    `${BACKEND}/api/v1/articles/${aid}/ai-proposals?status=pending`,
    { headers: auth },
  )
  if (pendingResp.ok()) {
    const pending = (await pendingResp.json()) as { id: string }[]
    for (const p of pending) {
      await request.post(`${BACKEND}/api/v1/ai-proposals/${p.id}/reject`, {
        headers: { ...auth, 'content-type': 'application/json' },
        data: { action: 'reject', reason: 'e2e cleanup' },
        failOnStatusCode: false,
      })
    }
  }

  // Create a proposal (stubbed LLM when no active credential, otherwise real).
  const propResp = await request.post(
    `${BACKEND}/api/v1/articles/${aid}/ai-proposals`,
    {
      headers: { ...auth, 'content-type': 'application/json' },
      data: { action: 'summarize', prompt: 'короткое резюме' },
    },
  )
  expect(propResp.ok()).toBeTruthy()
  const proposal = (await propResp.json()) as { id: string }

  // Accept it so it lands in the new "AI обзоры" section.
  const acceptResp = await request.post(
    `${BACKEND}/api/v1/ai-proposals/${proposal.id}/accept`,
    { headers: auth },
  )
  expect(acceptResp.ok()).toBeTruthy()

  await page.addInitScript(
    ({ at, rt }) => {
      window.localStorage.setItem(
        'neuroforum-auth',
        JSON.stringify({
          state: { accessToken: at, refreshToken: rt },
          version: 0,
        }),
      )
    },
    { at: access_token, rt: refresh_token },
  )

  await page.goto(`${FRONTEND}/articles/${aid}`, {
    waitUntil: 'networkidle',
  })
  // Give React Query a beat to refetch after auth bootstrap.
  await page.waitForTimeout(2500)

  // Section heading is visible.
  await expect(page.locator('text=AI обзоры').first()).toBeVisible({
    timeout: 10_000,
  })

  // The content area should exist.
  const content = page.locator('[data-testid="ai-review-content"]').first()
  await expect(content).toBeVisible()

  // Crude check that markdown was rendered, not left as literal:
  // no leading "## " heading marker, no inline "**word**" bold marker on RU/EN.
  const text = (await content.textContent()) ?? ''
  expect(text).not.toMatch(/^##\s/m)
  expect(text).not.toMatch(/\*\*[\wа-яА-Я]/i)
})
