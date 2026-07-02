import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * Full AI-review flow against a real OpenRouter credential.
 *
 * Skipped unless ``OPENROUTER_KEY`` is set in the environment (we never
 * commit the key — it lives in ``.env.local`` which is gitignored). Load
 * the var into the shell before running Playwright:
 *
 *     set -a; . frontend/.env.local; set +a
 *     pnpm exec playwright test e2e/ai-review-real-llm.spec.ts
 */

const BACKEND = process.env.E2E_API_URL ?? 'http://localhost:8000'
const FRONTEND = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000'
const OPENROUTER_KEY = process.env.OPENROUTER_KEY

const ALICE = { username: 'alice_neuro', password: 'password123' }
// Unique per-run display name — DELETE on agent_credentials is blocked by
// the llm_usage_log FK, so we can't reliably reuse the same name across
// runs without postgres-level surgery. A timestamp suffix keeps each run
// isolated.
const CRED_NAME = `pw-openrouter-${Date.now()}`

async function loginAlice(
  request: APIRequestContext,
): Promise<{ access: string; refresh: string | null }> {
  const resp = await request.post(`${BACKEND}/api/v1/auth/login`, {
    data: { username_or_email: ALICE.username, password: ALICE.password },
    failOnStatusCode: false,
  })
  if (!resp.ok()) {
    throw new Error(
      `login as ${ALICE.username} failed (HTTP ${resp.status()}): ${await resp.text()}`,
    )
  }
  const json = await resp.json()
  return {
    access: json.access_token as string,
    refresh: (json.refresh_token as string | null) ?? null,
  }
}

async function seedAuth(page: Page, access: string, refresh: string | null) {
  await page.addInitScript(
    ({ a, r }) => {
      window.localStorage.setItem(
        'neuroforum-auth',
        JSON.stringify({
          state: { accessToken: a, refreshToken: r },
          version: 0,
        }),
      )
    },
    { a: access, r: refresh },
  )
}

test.describe('AI review with real LLM (OpenRouter)', () => {
  test.skip(!OPENROUTER_KEY, 'OPENROUTER_KEY env var not set')

  test('alice configures credential, AI review returns real LLM text, original article stays untouched', async ({
    page,
    request,
  }) => {
    // Generous timeout — OpenRouter cold-starts can take 30s+.
    test.setTimeout(120_000)

    const { access, refresh } = await loginAlice(request)
    const auth = { Authorization: `Bearer ${access}` }

    // 1. Deactivate any leftover pw-openrouter-* credentials. We can't
    //    DELETE them (the llm_usage_log FK keeps them around) but flipping
    //    ``is_active=false`` makes the proposals service skip them and
    //    pick our fresh one instead.
    const credsResp = await request.get(
      `${BACKEND}/api/v1/agents/credentials`,
      { headers: auth },
    )
    if (credsResp.ok()) {
      const creds = (await credsResp.json()) as {
        id: string
        display_name: string
        is_active: boolean
      }[]
      for (const c of creds) {
        if (c.display_name.startsWith('pw-openrouter') && c.is_active) {
          await request.patch(
            `${BACKEND}/api/v1/agents/credentials/${c.id}`,
            {
              headers: { ...auth, 'content-type': 'application/json' },
              data: { is_active: false },
              failOnStatusCode: false,
            },
          )
        }
      }
    }

    // 2. Add a fresh OpenRouter credential.
    const credResp = await request.post(
      `${BACKEND}/api/v1/agents/credentials`,
      {
        headers: { ...auth, 'content-type': 'application/json' },
        data: {
          provider: 'openrouter',
          display_name: CRED_NAME,
          api_key: OPENROUTER_KEY,
          default_model: 'anthropic/claude-haiku-4.5',
        },
      },
    )
    expect(
      credResp.ok(),
      `credential POST failed: HTTP ${credResp.status()} ${await credResp.text()}`,
    ).toBeTruthy()
    const credential = await credResp.json()

    // 3. Pick an article authored by alice.
    const artsResp = await request.get(
      `${BACKEND}/api/v1/users/${ALICE.username}/articles?limit=1`,
    )
    expect(artsResp.ok()).toBeTruthy()
    const arts = (await artsResp.json()) as { id: string; title: string }[]
    expect(
      arts.length,
      'alice has no published articles — run the demo seed first',
    ).toBeGreaterThan(0)
    const articleId = arts[0].id

    // Capture original content + revision count so we can later assert the
    // article wasn't mutated by accepting the proposal.
    const beforeArticleResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}`,
    )
    expect(beforeArticleResp.ok()).toBeTruthy()
    const beforeArticle = await beforeArticleResp.json()
    const originalContent = JSON.stringify(beforeArticle.content)
    const originalRevisionsResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}/revisions`,
      { headers: auth },
    )
    const originalRevisions = originalRevisionsResp.ok()
      ? ((await originalRevisionsResp.json()) as unknown[])
      : []
    const originalRevisionsCount = originalRevisions.length

    // 4. Reject every pending proposal so the new card is unambiguous.
    const pendingResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}/ai-proposals?status=pending`,
      { headers: auth },
    )
    if (pendingResp.ok()) {
      const pending = (await pendingResp.json()) as { id: string }[]
      for (const p of pending) {
        await request.post(
          `${BACKEND}/api/v1/ai-proposals/${p.id}/reject`,
          {
            headers: { ...auth, 'content-type': 'application/json' },
            data: { action: 'reject', reason: 'pw cleanup' },
            failOnStatusCode: false,
          },
        )
      }
    }

    // 5. Create a real proposal — backend should hit OpenRouter.
    const propResp = await request.post(
      `${BACKEND}/api/v1/articles/${articleId}/ai-proposals`,
      {
        headers: { ...auth, 'content-type': 'application/json' },
        data: { action: 'summarize', prompt: 'Будь краток, 3-4 предложения.' },
        timeout: 90_000,
      },
    )
    expect(
      propResp.ok(),
      `ai-proposals POST failed: HTTP ${propResp.status()} ${await propResp.text()}`,
    ).toBeTruthy()
    const proposal = await propResp.json()

    const contentStr = JSON.stringify(proposal.proposed_content)
    // eslint-disable-next-line no-console
    console.log(
      'LLM response (first 500 chars):',
      contentStr.substring(0, 500),
    )
    // Reject the stub markers — if backend fell back to stub, the text
    // would contain ``"[AI proposal stub for action=..."``.
    expect(contentStr.toLowerCase()).not.toContain('ai proposal stub')
    // A real model summary is at least ~80 chars of JSON-encoded text.
    expect(contentStr.length).toBeGreaterThan(100)
    // llm_meta should be present and identify the model.
    expect(proposal.llm_meta).toBeTruthy()
    expect(proposal.llm_meta?.model).toBe('anthropic/claude-haiku-4.5')

    // 6. Open the article page and confirm the proposal renders.
    await seedAuth(page, access, refresh)
    await page.goto(`${FRONTEND}/articles/${articleId}`, {
      waitUntil: 'networkidle',
    })
    const card = page.getByTestId('ai-proposal-card').first()
    await expect(card).toBeVisible({ timeout: 15_000 })

    // 7. Mark "Полезно" — flips proposal to accepted.
    await card.getByTestId('ai-proposal-accept').click()
    // Accepted proposals disappear from the default-pending filter.
    await expect(
      page.locator('[data-testid="ai-proposal-card"]'),
    ).toHaveCount(0, { timeout: 10_000 })

    // 8. Confirm the article content + revision history were not touched
    //    by the accept (per the "accept = annotation only" semantics).
    const afterArticleResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}`,
    )
    const afterArticle = await afterArticleResp.json()
    expect(JSON.stringify(afterArticle.content)).toBe(originalContent)
    const afterRevisionsResp = await request.get(
      `${BACKEND}/api/v1/articles/${articleId}/revisions`,
      { headers: auth },
    )
    const afterRevisions = afterRevisionsResp.ok()
      ? ((await afterRevisionsResp.json()) as unknown[])
      : []
    expect(afterRevisions.length).toBe(originalRevisionsCount)

    // 9. Cleanup — try DELETE (often blocked by FK from llm_usage_log,
    //    that's fine), otherwise deactivate.
    const del = await request.delete(
      `${BACKEND}/api/v1/agents/credentials/${credential.id}`,
      { headers: auth, failOnStatusCode: false },
    )
    if (!del.ok()) {
      await request.patch(
        `${BACKEND}/api/v1/agents/credentials/${credential.id}`,
        {
          headers: { ...auth, 'content-type': 'application/json' },
          data: { is_active: false },
          failOnStatusCode: false,
        },
      )
    }
  })
})
