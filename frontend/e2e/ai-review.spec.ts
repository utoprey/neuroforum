import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * E2E for the AI review flow.
 *
 * Validates the new "standalone annotation" semantics:
 *
 *   - Author requests an AI review → a proposal card appears.
 *   - Clicking "Полезно" flips the proposal status to ``accepted``.
 *   - The original article.content is UNCHANGED (no new revision either).
 *
 * Plus a smaller test for the "Скопировать в редактор" flow that hands the
 * proposed_content off to the edit page via sessionStorage.
 *
 * Assumes the docker stack is up and the demo seed (with `alice_neuro`,
 * password `password123`) has been applied:
 *
 *     docker compose run --rm backend python -m backend.scripts.seed
 *
 * Auth is bootstrapped by writing the zustand `neuroforum-auth` localStorage
 * entry directly (see `seedAuth`), which mirrors what the AuthBootstrap
 * component reads on first load.
 */

const BACKEND = process.env.E2E_API_URL ?? 'http://localhost:8000'
const FRONTEND = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000'

const ALICE = {
  username: 'alice_neuro',
  password: 'password123',
}

async function loginAlice(request: APIRequestContext): Promise<string> {
  const resp = await request.post(`${BACKEND}/api/v1/auth/login`, {
    data: {
      username_or_email: ALICE.username,
      password: ALICE.password,
    },
    failOnStatusCode: false,
  })
  if (!resp.ok()) {
    throw new Error(
      `login as ${ALICE.username} failed (HTTP ${resp.status()}): ${await resp.text()} — ensure demo seed is applied`,
    )
  }
  const json = await resp.json()
  return json.access_token as string
}

async function seedAuth(page: Page, accessToken: string): Promise<void> {
  // Matches the shape persisted by `useAuthStore` (zustand persist middleware
  // with key `neuroforum-auth`, only `accessToken` + `refreshToken` saved).
  await page.addInitScript(
    ({ token, key }) => {
      window.localStorage.setItem(
        key,
        JSON.stringify({
          state: { accessToken: token, refreshToken: null },
          version: 0,
        }),
      )
    },
    { token: accessToken, key: 'neuroforum-auth' },
  )
}

async function pickAliceArticle(
  request: APIRequestContext,
): Promise<{ id: string; title: string; slug: string }> {
  const resp = await request.get(
    `${BACKEND}/api/v1/users/${ALICE.username}/articles?limit=1`,
  )
  if (!resp.ok()) {
    throw new Error(
      `listing alice's articles failed (HTTP ${resp.status()}): ${await resp.text()}`,
    )
  }
  const rows = await resp.json()
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error(
      'alice has no published articles — re-run the demo seed before this e2e',
    )
  }
  return rows[0]
}

test.describe('AI review flow', () => {
  test('accept proposal marks "Полезно" without touching article.content', async ({
    page,
    request,
  }) => {
    const accessToken = await loginAlice(request)
    const articleSummary = await pickAliceArticle(request)
    const articleId = articleSummary.id

    // Clean slate: reject every pending proposal left over from prior runs
    // so the panel only shows the one we're about to create.
    const pendingResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}/ai-proposals?status=pending`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
    if (pendingResp.ok()) {
      const pending = (await pendingResp.json()) as { id: string }[]
      for (const p of pending) {
        await request.post(
          `${BACKEND}/api/v1/ai-proposals/${p.id}/reject`,
          {
            headers: {
              Authorization: `Bearer ${accessToken}`,
              'content-type': 'application/json',
            },
            data: { action: 'reject', reason: 'e2e cleanup' },
            failOnStatusCode: false,
          },
        )
      }
    }

    // Capture the ORIGINAL article state — content + revision count — so we
    // can assert nothing changed after the accept.
    const beforeArticleResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}`,
    )
    expect(beforeArticleResp.ok()).toBeTruthy()
    const beforeArticle = await beforeArticleResp.json()
    const originalContent = JSON.stringify(beforeArticle.content)

    const beforeRevisionsResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}/revisions`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
    const beforeRevisions = beforeRevisionsResp.ok()
      ? await beforeRevisionsResp.json()
      : []
    const beforeRevisionsCount = Array.isArray(beforeRevisions)
      ? beforeRevisions.length
      : 0

    await seedAuth(page, accessToken)

    // Open the article page.
    await page.goto(`${FRONTEND}/articles/${articleId}`)
    await expect(
      page.getByRole('heading', { level: 1, name: beforeArticle.title }),
    ).toBeVisible({ timeout: 15_000 })

    // Open the AI review dialog and submit a request.
    await page.getByTestId('ai-review-button').click()
    await page.getByTestId('ai-action-trigger').click()
    await page
      .getByRole('option', { name: /Проверить ссылки.цитаты/i })
      .click()
    await page
      .locator('#ai-prompt')
      .fill('test prompt from playwright e2e')
    await page.getByTestId('ai-review-submit').click()

    // The new proposal card should appear in the panel.
    const proposalCard = page.getByTestId('ai-proposal-card').first()
    await expect(proposalCard).toBeVisible({ timeout: 15_000 })
    await expect(proposalCard).toContainText(/Проверить ссылки/i)

    // Click "Полезно" (the old "Принять", renamed). After the mutation
    // resolves the active filter should hide the now-accepted card.
    await proposalCard.getByTestId('ai-proposal-accept').click()
    await expect(
      page.locator('[data-testid="ai-proposal-card"]'),
    ).toHaveCount(0, { timeout: 10_000 })

    // Verify via API that the proposal status is now `accepted`.
    const acceptedResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}/ai-proposals?status=accepted`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
    expect(acceptedResp.ok()).toBeTruthy()
    const acceptedList = await acceptedResp.json()
    expect(Array.isArray(acceptedList)).toBeTruthy()
    expect(acceptedList.length).toBeGreaterThan(0)

    // CRITICAL: original article.content is unchanged.
    const afterArticleResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}`,
    )
    const afterArticle = await afterArticleResp.json()
    expect(JSON.stringify(afterArticle.content)).toBe(originalContent)

    // CRITICAL: no new ArticleRevision was created from the accept.
    const afterRevisionsResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}/revisions`,
      { headers: { Authorization: `Bearer ${accessToken}` } },
    )
    const afterRevisions = afterRevisionsResp.ok()
      ? await afterRevisionsResp.json()
      : []
    expect(Array.isArray(afterRevisions) ? afterRevisions.length : 0).toBe(
      beforeRevisionsCount,
    )
    const aiRevisions = (afterRevisions as { edit_reason?: string | null }[])
      .filter((r) => (r.edit_reason ?? '').includes('AI proposal'))
    expect(aiRevisions.length).toBe(0)
  })

  test('"Скопировать в редактор" navigates with a sessionStorage prefill banner', async ({
    page,
    request,
  }) => {
    const accessToken = await loginAlice(request)
    const articleSummary = await pickAliceArticle(request)
    const articleId = articleSummary.id

    // Create a fresh pending proposal via API — faster than the dialog.
    const createResp = await request.post(
      `${BACKEND}/api/v1/articles/${articleId}/ai-proposals`,
      {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          'content-type': 'application/json',
        },
        data: { action: 'rephrase', prompt: 'rephrase for clarity' },
      },
    )
    if (!createResp.ok()) {
      throw new Error(
        `creating proposal failed (HTTP ${createResp.status()}): ${await createResp.text()}`,
      )
    }

    await seedAuth(page, accessToken)
    await page.goto(`${FRONTEND}/articles/${articleId}`)

    const proposalCard = page.getByTestId('ai-proposal-card').first()
    await expect(proposalCard).toBeVisible({ timeout: 15_000 })

    // Click "Скопировать в редактор".
    await proposalCard.getByTestId('ai-proposal-copy-to-editor').click()

    // Should navigate to the edit page with the proposal query param.
    await page.waitForURL(
      new RegExp(`/articles/${articleId}/edit\\?proposal=`),
      { timeout: 10_000 },
    )

    // Banner should be visible.
    const banner = page.getByTestId('ai-prefill-banner')
    await expect(banner).toBeVisible({ timeout: 10_000 })

    // Apply the prefill and confirm the banner disappears.
    await page.getByTestId('ai-prefill-apply').click()
    await expect(banner).not.toBeVisible()

    // sessionStorage key should be cleared.
    const remaining = await page.evaluate(
      (key) => sessionStorage.getItem(key),
      `ai-proposal-prefill:${articleId}`,
    )
    expect(remaining).toBeNull()
  })
})
