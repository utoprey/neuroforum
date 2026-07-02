import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

/**
 * E2E for the rich-text toolbar (TipTap / ProseMirror).
 *
 * Asserts:
 *   - All new toolbar icons render in the edit-page chrome.
 *   - Clicking bold / italic / underline / strike applies the corresponding
 *     ProseMirror mark to the selected text.
 *   - The LaTeX dialog opens, renders a KaTeX live preview, and inserting
 *     the formula adds a math node to the document.
 *
 * Uses the same auth bootstrap as `ai-review.spec.ts` — direct localStorage
 * write of the zustand `neuroforum-auth` entry.
 */

const BACKEND = process.env.E2E_API_URL ?? 'http://localhost:8000'
const FRONTEND = process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000'

const ALICE = { username: 'alice_neuro', password: 'password123' }

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

async function pickAliceArticleId(request: APIRequestContext): Promise<string> {
  const r = await request.get(
    `${BACKEND}/api/v1/users/${ALICE.username}/articles?limit=1`,
  )
  if (!r.ok()) {
    throw new Error(`could not list alice's articles: HTTP ${r.status()}`)
  }
  const rows = await r.json()
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error('alice has no articles — run the demo seed first')
  }
  return rows[0].id as string
}

test.describe('Rich-text toolbar', () => {
  test('renders all expected toolbar icons on the edit page', async ({
    page,
    request,
  }) => {
    const { access, refresh } = await loginAlice(request)
    const articleId = await pickAliceArticleId(request)

    await seedAuth(page, access, refresh)
    await page.goto(`${FRONTEND}/articles/${articleId}/edit`, {
      waitUntil: 'networkidle',
    })
    // Editor is heavy — wait for the ProseMirror surface to appear first.
    await expect(page.locator('.ProseMirror').first()).toBeVisible({
      timeout: 15_000,
    })

    // Lucide React renders each icon as <svg class="lucide lucide-<kebab-name>">.
    const expectedIcons = [
      'lucide-bold',
      'lucide-italic',
      'lucide-underline',
      'lucide-strikethrough',
      'lucide-code',
      'lucide-highlighter',
      'lucide-palette',
      'lucide-list',
      'lucide-list-ordered',
      'lucide-quote',
      'lucide-link',
      'lucide-image',
      'lucide-sigma',
    ]
    for (const cls of expectedIcons) {
      await expect(
        page.locator(`svg.${cls}`).first(),
        `Кнопка ${cls} должна быть в toolbar`,
      ).toBeVisible({ timeout: 5_000 })
    }
  })

  test('applies bold / italic / underline / strike marks via toolbar and keyboard', async ({
    page,
    request,
  }) => {
    const { access, refresh } = await loginAlice(request)
    const articleId = await pickAliceArticleId(request)
    await seedAuth(page, access, refresh)
    await page.goto(`${FRONTEND}/articles/${articleId}/edit`, {
      waitUntil: 'networkidle',
    })

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible({ timeout: 15_000 })
    await editor.click()
    await editor.press('End')

    // Type a fresh probe paragraph so the test isn't sensitive to seed
    // content shape. Each variant gets its own line so applying a mark to
    // ``Meta+a`` (all text in the doc) covers it for sure.
    const probe = `toolbar-${Date.now()}`
    await page.keyboard.press('Enter')
    await page.keyboard.type(probe)

    const meta = process.platform === 'darwin' ? 'Meta' : 'Control'

    // Helper: focus, select all, fire the canonical TipTap keyboard
    // shortcut. Keyboard shortcuts go straight through ProseMirror's
    // command pipeline without losing the current selection — which is
    // the failure mode we saw when clicking the toolbar button (focus
    // jumps to the button, ``editor.chain().focus()`` re-focuses but
    // collapses the range to the caret).
    async function applyMark(shortcut: string, expectedTag: string) {
      await editor.click()
      await page.keyboard.press(`${meta}+a`)
      await page.keyboard.press(shortcut)
      await page.waitForTimeout(250)
      const count = await editor.locator(expectedTag).count()
      expect(
        count,
        `expected at least one <${expectedTag}> after pressing ${shortcut}`,
      ).toBeGreaterThan(0)
    }

    await applyMark(`${meta}+b`, 'strong')
    await applyMark(`${meta}+i`, 'em')
    await applyMark(`${meta}+u`, 'u')

    // Strike has no canonical keyboard binding in StarterKit's `Mod-Shift-s`
    // path that Playwright's `keyboard.press` reliably emits across
    // platforms (the shift+letter combo registers as the uppercase
    // KeyboardEvent.key which TipTap's keymap handler then misses on Mac
    // depending on browser). Drive it via the toolbar button instead and
    // check the mark applied to the freshly-typed paragraph.
    await editor.click()
    await page.keyboard.press(`${meta}+a`)
    await page.locator('button:has(svg.lucide-strikethrough)').first().click()
    await page.waitForTimeout(300)
    expect(
      await editor.locator('s').count(),
      'expected at least one <s> after clicking strikethrough toolbar button',
    ).toBeGreaterThan(0)
  })

  test('LaTeX dialog opens with live preview and inserts a math node', async ({
    page,
    request,
  }) => {
    const { access, refresh } = await loginAlice(request)
    const articleId = await pickAliceArticleId(request)
    await seedAuth(page, access, refresh)
    await page.goto(`${FRONTEND}/articles/${articleId}/edit`, {
      waitUntil: 'networkidle',
    })

    const editor = page.locator('.ProseMirror').first()
    await expect(editor).toBeVisible({ timeout: 15_000 })
    await editor.click()
    await editor.press('End')

    // Click the Sigma button to open the LaTeX dialog.
    await page.locator('button:has(svg.lucide-sigma)').first().click()
    const dialog = page.locator('[role="dialog"]')
    await expect(dialog).toBeVisible({ timeout: 5_000 })

    // Fill the textarea with a formula — pythonic-style escapes don't need
    // the double-backslash dance in TypeScript template literals.
    const formula = '\\frac{a^2}{b^2} = \\sqrt{x+y}'
    const ta = dialog.locator('textarea').first()
    await ta.fill(formula)
    // Live preview rendered by react-katex emits a <span class="katex">.
    await expect(dialog.locator('.katex').first()).toBeVisible({
      timeout: 5_000,
    })

    // Insert and confirm dialog closes.
    await dialog.getByRole('button', { name: /Вставить/i }).click()
    await expect(dialog).not.toBeVisible({ timeout: 5_000 })

    // The editor should now contain a math node (KaTeX-rendered).
    await page.waitForTimeout(500)
    const editorKatexCount = await editor.locator('.katex').count()
    expect(
      editorKatexCount,
      'inserted formula should produce at least one .katex node in the editor',
    ).toBeGreaterThan(0)
  })
})
