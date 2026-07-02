import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * Smoke test for the AI-proposal markdown renderer.
 *
 * We do not depend on the live LLM here — instead we intercept the
 * `/api/v1/articles/{id}/ai-proposals` GET response and inject a synthetic
 * proposal whose `proposed_content` is the LLM's typical "raw markdown
 * wrapped into a single paragraph" shape. The page should then render
 * proper headings / bold / lists / KaTeX math via `MarkdownContent`
 * instead of literal `#`, `**`, `$$…$$`.
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
      `login as ${ALICE.username} failed (HTTP ${resp.status()}): ${await resp.text()}`,
    )
  }
  const json = await resp.json()
  return json.access_token as string
}

async function seedAuth(page: Page, accessToken: string): Promise<void> {
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
): Promise<{ id: string; title: string }> {
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
    throw new Error('alice has no published articles — re-run the demo seed')
  }
  return rows[0]
}

const MARKDOWN_SAMPLE = [
  '# Heading One',
  '',
  '## Heading Two',
  '',
  '**bold text** and *italic* with $a^2 + b^2 = c^2$ inline math.',
  '',
  '$$\\tau \\frac{dh}{dt} = -h + W h$$',
  '',
  '- item one',
  '- item two',
  '',
  '```python',
  'print("hello")',
  '```',
].join('\n')

test('AI proposal renders markdown headings and KaTeX math', async ({
  page,
  request,
}) => {
  const accessToken = await loginAlice(request)
  const article = await pickAliceArticle(request)
  const articleId = article.id

  await seedAuth(page, accessToken)

  // Intercept the ai-proposals fetch and return a synthetic proposal
  // whose proposed_content is a markdown-wrapped-in-paragraph blob —
  // exactly the shape today's LLM pipeline produces.
  await page.route(
    (url) =>
      url.pathname.endsWith(`/articles/${articleId}/ai-proposals`) ||
      url.pathname.includes(`/articles/${articleId}/ai-proposals`),
    async (route) => {
      if (route.request().method() !== 'GET') {
        await route.continue()
        return
      }
      const fake = [
        {
          id: '00000000-0000-0000-0000-000000000001',
          article_id: articleId,
          requested_by: {
            id: '00000000-0000-0000-0000-0000000000aa',
            username: 'alice_neuro',
            display_name: 'Alice',
            avatar_url: null,
            role: 'user',
          },
          decided_by: null,
          action: 'rephrase',
          prompt: 'sample for markdown test',
          status: 'pending',
          decided_at: null,
          rejection_reason: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          proposed_content: {
            type: 'doc',
            content: [
              {
                type: 'paragraph',
                content: [{ type: 'text', text: MARKDOWN_SAMPLE }],
              },
            ],
          },
          model: 'test-model',
        },
      ]
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fake),
      })
    },
  )

  await page.goto(`${FRONTEND}/articles/${articleId}`, {
    waitUntil: 'domcontentloaded',
  })

  const card = page.locator('[data-testid="ai-proposal-card"]').first()
  await expect(card).toBeVisible({ timeout: 15_000 })

  // The MarkdownContent wrapper should be present (not the NotionEditor
  // fallback) and contain a rendered <h1>/<h2>.
  const md = card.locator('[data-testid="markdown-content"]')
  await expect(md).toBeVisible()

  const innerHTML = await md.innerHTML()
  const hasHeading =
    innerHTML.includes('<h1') ||
    innerHTML.includes('<h2') ||
    innerHTML.includes('<h3')
  const hasKatex = innerHTML.includes('katex')
  expect(hasHeading).toBeTruthy()
  expect(hasKatex).toBeTruthy()

  // Bullet list should be rendered as a real <ul>, not literal `- item`.
  expect(innerHTML).toMatch(/<ul[^>]*>[\s\S]*<li[^>]*>/)

  // No raw `## ` at line-start should leak into the visible text.
  const visibleText = (await md.textContent()) ?? ''
  expect(visibleText).not.toMatch(/^##\s/m)
  // And no double-asterisk for bold.
  expect(visibleText).not.toMatch(/\*\*bold text\*\*/)
})
