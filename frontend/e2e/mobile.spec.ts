import { test } from '@playwright/test'

// iPhone 13 viewport + UA, but run on chromium (webkit not installed locally)
test.use({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
  userAgent:
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
})

const SITE = process.env.E2E_SITE ?? 'http://localhost:3000'
const API = process.env.E2E_API ?? 'http://localhost:8000'

test('mobile snapshots', async ({ page, request }) => {
  // Login as a seed admin so we can see logged-in state
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
  await page.screenshot({ path: '/tmp/mobile-home.png', fullPage: false })

  // Open burger menu
  await page.locator('[data-testid="mobile-menu-button"]').click()
  await page.waitForTimeout(800)
  const asideClass = await page.locator('aside[aria-label="Меню"]').getAttribute('class')
  const computedBg = await page.locator('aside[aria-label="Меню"]').evaluate((el) => {
    return getComputedStyle(el).backgroundColor
  })
  console.log('aside class:', asideClass)
  console.log('aside computed bg:', computedBg)
  await page.screenshot({ path: '/tmp/mobile-burger.png', fullPage: false })

  // Section overview (4 tabs)
  await page.goto(`${SITE}/sections/computational-neuroscience/topics`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: '/tmp/mobile-section.png', fullPage: false })

  // Article view
  const arts = await (await request.get(`${API}/api/v1/users/alice_neuro/articles?limit=1`)).json()
  const aid = arts[0].id
  await page.goto(`${SITE}/articles/${aid}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(2500)
  await page.screenshot({ path: '/tmp/mobile-article.png', fullPage: false })

  // Profile
  await page.goto(`${SITE}/profile`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: '/tmp/mobile-profile.png', fullPage: false })
})
