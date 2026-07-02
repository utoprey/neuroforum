import { expect, test } from '@playwright/test'

/**
 * E2E for the editable "AI обзоры" section.
 *
 * Flow:
 *   1. Log in as alice_neuro (article author).
 *   2. Cleanup pending proposals so the new one stays first in the list.
 *   3. Create + accept a fresh proposal via API so it appears in "AI обзоры".
 *   4. Open the article page, hit "Редактировать" on the new card, fill the
 *      textarea with custom markdown, hit "Сохранить".
 *   5. After save: card returns to read-mode and renders the new heading.
 *   6. Re-fetch via API: `proposed_content` JSONB contains the edited text.
 */

const BACKEND = process.env.E2E_API_URL ?? 'http://localhost:8000'
const FRONTEND = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000'

test('alice can edit her accepted AI обзор content via PATCH', async ({
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

  // Cleanup pending so the panel is deterministic.
  const pendingResp = await request.get(
    `${BACKEND}/api/v1/articles/${aid}/ai-proposals?status=pending`,
    { headers: auth },
  )
  if (pendingResp.ok()) {
    const pending = (await pendingResp.json()) as { id: string }[]
    for (const p of pending) {
      await request.post(`${BACKEND}/api/v1/ai-proposals/${p.id}/reject`, {
        headers: { ...auth, 'content-type': 'application/json' },
        data: { action: 'reject', reason: 'edit-spec cleanup' },
        failOnStatusCode: false,
      })
    }
  }

  // Create + accept a fresh proposal — the new one is ORDER BY created_at DESC,
  // so it will be the first card in the section.
  const propResp = await request.post(
    `${BACKEND}/api/v1/articles/${aid}/ai-proposals`,
    {
      headers: { ...auth, 'content-type': 'application/json' },
      data: { action: 'summarize', prompt: 'тест на редактирование' },
    },
  )
  expect(propResp.ok()).toBeTruthy()
  const proposal = (await propResp.json()) as { id: string }
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
  await page.waitForTimeout(2500)

  const section = page.locator('[data-testid="ai-reviews-section"]')
  await expect(section).toBeVisible({ timeout: 10_000 })

  // The freshly created accepted proposal is the first card (created_at DESC).
  const card = section
    .locator(`[data-testid="ai-review-item"][data-proposal-id="${proposal.id}"]`)
    .first()
  await card.scrollIntoViewIfNeeded()
  await expect(card).toBeVisible({ timeout: 10_000 })

  // Enter edit mode.
  await card
    .locator('[data-testid="ai-review-edit"]')
    .first()
    .click()

  const ta = card.locator('[data-testid="ai-review-edit-textarea"]')
  await expect(ta).toBeVisible({ timeout: 5_000 })

  const customText = `# Отредактированное резюме\n\nЭтот текст ввёл человек в Playwright тесте.\n\n- пункт 1\n- пункт 2`
  await ta.fill(customText)

  await card.locator('[data-testid="ai-review-edit-save"]').click()
  // Wait for save → React Query invalidation → card re-render in read mode.
  await page.waitForTimeout(2500)

  // After save: card shows the edited markdown rendered. The H1 heading we
  // just typed should now be a real <h1>.
  await expect(
    card.locator('h1', { hasText: 'Отредактированное резюме' }),
  ).toBeVisible({ timeout: 10_000 })

  // Backend confirms via API.
  const refetch = await request.get(
    `${BACKEND}/api/v1/articles/${aid}/ai-proposals?status=accepted`,
    { headers: auth },
  )
  expect(refetch.ok()).toBeTruthy()
  const list = (await refetch.json()) as Array<{
    id: string
    proposed_content: unknown
  }>
  const updated = list.find((p) => p.id === proposal.id)
  expect(updated).toBeDefined()
  const flat = JSON.stringify(updated?.proposed_content ?? {})
  expect(flat).toContain('Отредактированное резюме')
})
