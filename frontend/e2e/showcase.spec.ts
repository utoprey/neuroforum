import { test } from '@playwright/test'

const SITE = 'http://193.180.210.78:3000'
const API = 'http://193.180.210.78:8000'
// Content-height clip — keeps README grid symmetric across pages that
// have different amounts of content. 540px covers the header + first
// row of cards / tabs / hero on every showcase page.
const CLIP = { x: 0, y: 0, width: 1280, height: 540 }

test.describe('Showcase screenshots for README', () => {
  test.use({ viewport: { width: 1280, height: 800 } })

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
    await page.screenshot({ path: '/tmp/shot-home.png', clip: CLIP })

    // Sections page — force scroll to top and wait for grid
    await page.goto(`${SITE}/sections`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-sections.png', clip: CLIP })

    // Section with 4 tabs
    await page.goto(`${SITE}/sections/computational-neuroscience/topics?kind=news`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-section.png', clip: CLIP })

    // Article with math + images
    const topicsR = await request.get(`${API}/api/v1/sections/computational-neuroscience/topics?kind=news`)
    const topics = await topicsR.json()
    const topic = topics.find((t: any) => t.slug === 'recurrent-network-models') ?? topics[0]
    const artsR = await request.get(`${API}/api/v1/topics/${topic.id}/articles`)
    const [art] = await artsR.json()
    await page.goto(`${SITE}/articles/${art.id}-${art.slug}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-article.png', clip: CLIP })

    // AI review section — scroll into view
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="ai-reviews-section"]')
      if (el) {
        el.scrollIntoView({ block: 'start' })
        window.scrollBy(0, -80) // отступ, чтобы заголовок был виден
      }
    })
    await page.waitForTimeout(700)
    await page.screenshot({ path: '/tmp/shot-ai-review.png', clip: CLIP })

    // Profile
    await page.goto(`${SITE}/profile`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-profile.png', clip: CLIP })

    // Credentials management
    await page.goto(`${SITE}/me/credentials`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: '/tmp/shot-credentials.png', clip: CLIP })
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
