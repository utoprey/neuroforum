import { test } from '@playwright/test'

const SITE = 'http://193.180.210.78:3000'
const API = 'http://193.180.210.78:8000'

test.describe('Showcase screenshots for README', () => {
  // Fixed viewport height keeps every desktop screenshot symmetric on GitHub.
  // We take viewport-based screenshots (no `clip`) so scroll actually shifts
  // what's visible in the captured PNG.
  test.use({ viewport: { width: 1280, height: 540 } })

  test('desktop shots', async ({ page, request }) => {
    const r = await request.post(`${API}/api/v1/auth/login`, {
      data: { username_or_email: 'alice_neuro', password: 'password123' },
    })
    const { access_token, refresh_token } = await r.json()
    await page.addInitScript(({ at, rt }) => {
      window.localStorage.setItem(
        'neuroforum-auth',
        JSON.stringify({ state: { accessToken: at, refreshToken: rt }, version: 0 }),
      )
    }, { at: access_token, rt: refresh_token })

    // Home
    await page.goto(SITE, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: '/tmp/shot-home.png' })

    // Sections page (all 6 section cards visible in 540px viewport)
    await page.goto(`${SITE}/sections`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-sections.png' })

    // Section with 4 tabs + first two topics visible
    await page.goto(`${SITE}/sections/computational-neuroscience/topics?kind=news`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-section.png' })

    // Article top — title + first paragraph + first formula.
    // We pick an article that ALSO has accepted AI reviews so the next
    // shot below (ai-review.png) shows the AI обзоры block with real
    // Markdown+KaTeX content.
    const artByAlice = await (await request.get(
      `${API}/api/v1/users/alice_neuro/articles?limit=5`,
    )).json()
    const art = artByAlice[0]
    await page.goto(`${SITE}/articles/${art.id}-${art.slug}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-article.png' })

    // AI обзоры — scroll the section header into view, then screenshot
    // the viewport (now shows the AI reviews block with markdown +
    // KaTeX rendered).
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="ai-reviews-section"]') as HTMLElement | null
      if (el) {
        const y = el.getBoundingClientRect().top + window.scrollY - 20
        window.scrollTo({ top: y, behavior: 'instant' as ScrollBehavior })
      }
    })
    await page.waitForTimeout(700)
    await page.screenshot({ path: '/tmp/shot-ai-review.png' })

    // Profile
    await page.goto(`${SITE}/profile`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-profile.png' })

    // Credentials management
    await page.goto(`${SITE}/me/credentials`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-credentials.png' })
  })

  test('mobile shots', async ({ browser, request }) => {
    const mobile = await browser.newContext({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
    })
    const mp = await mobile.newPage()

    const r = await request.post(`${API}/api/v1/auth/login`, {
      data: { username_or_email: 'alice_neuro', password: 'password123' },
    })
    const { access_token, refresh_token } = await r.json()
    await mp.addInitScript(({ at, rt }) => {
      window.localStorage.setItem(
        'neuroforum-auth',
        JSON.stringify({ state: { accessToken: at, refreshToken: rt }, version: 0 }),
      )
    }, { at: access_token, rt: refresh_token })

    await mp.goto(SITE, { waitUntil: 'networkidle' })
    await mp.waitForTimeout(1500)
    await mp.screenshot({ path: '/tmp/shot-mobile-home.png' })

    const topicsR = await request.get(`${API}/api/v1/sections/computational-neuroscience/topics?kind=news`)
    const topics = await topicsR.json()
    const topic = topics.find((t: any) => t.slug === 'recurrent-network-models') ?? topics[0]
    const artsR = await request.get(`${API}/api/v1/topics/${topic.id}/articles`)
    const [art] = await artsR.json()
    await mp.goto(`${SITE}/articles/${art.id}-${art.slug}`, { waitUntil: 'networkidle' })
    await mp.waitForTimeout(2000)
    await mp.screenshot({ path: '/tmp/shot-mobile-article.png' })

    await mobile.close()
  })
})
