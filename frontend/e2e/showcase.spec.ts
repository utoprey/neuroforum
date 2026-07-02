import { test } from '@playwright/test'

const SITE = 'http://193.180.210.78:3000'
const API = 'http://193.180.210.78:8000'

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
    await page.screenshot({ path: '/tmp/shot-home.png', fullPage: false })

    // Sections page
    await page.goto(`${SITE}/sections`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: '/tmp/shot-sections.png', fullPage: false })

    // Section with tabs
    await page.goto(`${SITE}/sections/computational-neuroscience/topics`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: '/tmp/shot-section.png', fullPage: false })

    // Article with math + images
    const topicsR = await request.get(`${API}/api/v1/sections/computational-neuroscience/topics?kind=news`)
    const [top] = await topicsR.json()
    const artsR = await request.get(`${API}/api/v1/topics/${top.id}/articles`)
    const [art] = await artsR.json()
    await page.goto(`${SITE}/articles/${art.id}-${art.slug}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(2500)
    await page.screenshot({ path: '/tmp/shot-article.png', fullPage: false })

    // AI review section
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="ai-reviews-section"]')
      el?.scrollIntoView({ block: 'start' })
    })
    await page.waitForTimeout(700)
    await page.screenshot({ path: '/tmp/shot-ai-review.png', fullPage: false })

    // Profile
    await page.goto(`${SITE}/profile`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: '/tmp/shot-profile.png', fullPage: false })

    // Credentials management
    await page.goto(`${SITE}/me/credentials`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1500)
    await page.screenshot({ path: '/tmp/shot-credentials.png', fullPage: false })
  })

  test('mobile shot', async ({ page, request, browser }) => {
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
    await mp.screenshot({ path: '/tmp/shot-mobile-home.png', fullPage: false })

    const topicsR = await request.get(`${API}/api/v1/sections/computational-neuroscience/topics?kind=news`)
    const [top] = await topicsR.json()
    const artsR = await request.get(`${API}/api/v1/topics/${top.id}/articles`)
    const [art] = await artsR.json()
    await mp.goto(`${SITE}/articles/${art.id}-${art.slug}`, { waitUntil: 'networkidle' })
    await mp.waitForTimeout(2000)
    await mp.screenshot({ path: '/tmp/shot-mobile-article.png', fullPage: false })

    await mobile.close()
  })
})
