// Visual check of every screen against the mock engine (headless installed Chrome via playwright-core).
//
//   npm run dev:mock                      # in another terminal (or PORT=3110 MOCK_PORT=8797 npm run dev:mock)
//   NODE_PATH=d:/tmp/pw/node_modules node mock/screenshots.mjs [http://localhost:3000] [outDir]
//
// Writes PNGs to d:/tmp/exemplar-shots/F by default (outside the repo), prints console errors and
// checks that no screen scrolls horizontally on a 390 px wide phone.
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'

const require = createRequire((process.env.NODE_PATH || 'd:/tmp/pw/node_modules') + '/')
const { chromium } = require('playwright-core')

const base = process.argv[2] || 'http://localhost:3000'
const out = process.argv[3] || 'd:/tmp/exemplar-shots/F'
mkdirSync(out, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
const page = await ctx.newPage()
const problems = []
page.on('console', (m) => { if (m.type() === 'error') problems.push(`console: ${m.text().slice(0, 200)}`) })
page.on('pageerror', (e) => problems.push(`pageerror: ${String(e).slice(0, 200)}`))
page.on('response', (r) => { if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`) })

// Lazy thumbnails below the fold must load before a full-page capture.
const settle = async () => {
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 700) { window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 60)) }
    window.scrollTo(0, 0)
  })
  await page.waitForTimeout(400)
}
const shot = async (name, opts = {}) => {
  if (opts.full ?? true) await settle()
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: opts.full ?? true })
  console.log('shot', name)
}
const step = async (label, fn) => {
  try { await fn() } catch (e) { problems.push(`${label}: ${String(e).split('\n')[0]}`); console.log('step failed:', label, String(e).split('\n')[0]) }
}
const go = async (path) => { await page.goto(base + path, { waitUntil: 'networkidle' }); await page.waitForTimeout(400) }
const pickConcept = async (name) => { await page.getByLabel(/^(Label for )?[Cc]oncept$/).first().selectOption({ label: name }); await page.waitForTimeout(900) }

await step('reset', async () => { await fetch(`${new URL(base).origin}/api/engine/__mock/reset`, { method: 'POST' }) })

// ---- home
await go('/')
await shot('01-home')

// ---- connect: a 3 minute token shows the warning state, a fresh one the calm state
await go('/connect')
const paste = async (value) => {
  await page.getByLabel('Playground access token').fill(value)
  await page.getByRole('button', { name: /Save token|Replace token/ }).click()
  await page.getByText(/Token saved/).waitFor()
  await page.waitForTimeout(500)
}
await step('connect: expiring', async () => { await paste('short-lived-demo-token'); await shot('02a-connect-expiring') })
await step('connect: ok', async () => { await paste('ava.v1.demo-token-0123456789'); await shot('02b-connect-ok') })

// ---- library
await go('/library')
await page.getByRole('button', { name: /View details/ }).first().waitFor()
await page.waitForTimeout(700)
await shot('03a-library', { full: false })
// ---- teach
await go('/teach')
await step('teach: select theft', async () => { await pickConcept('Package theft') })
await shot('04a-teach-empty', { full: false })
await step('teach: run', async () => {
  await page.getByRole('button', { name: /^Teach$/ }).click()
  await page.waitForTimeout(3000)
  await shot('04b-teach-running', { full: false })
  await page.getByText('Candidate rules ready').waitFor({ timeout: 15000 })
  await page.getByText('Should this one count?').waitFor({ timeout: 15000 })
  await page.waitForTimeout(1500)
  await shot('04c-teach-done')
})

// ---- rule for the freshly taught theft concept: only 4 random negatives, so no guarantee yet
await go('/rule')
await step('rule: theft, no guarantee', async () => { await pickConcept('Package theft'); await shot('05a-rule-no-guarantee') })

await go('/library')
await step('library: calibration flow', async () => {
  await pickConcept('Package theft')
  await page.getByRole('button', { name: /Label 10 random/ }).click()
  await page.getByRole('heading', { name: /Calibration labels/ }).waitFor()
  await page.waitForTimeout(600)
  await shot('03b-library-calibration', { full: false })
  await page.getByRole('button', { name: /Mark all unanswered as not matching/ }).click()
  await page.waitForTimeout(700)
  await shot('03c-library-calibration-done', { full: false })
  await page.getByRole('button', { name: 'Done' }).click()
})
await step('library: dialog', async () => {
  await page.getByRole('button', { name: /View details: .*package/i }).first().click()
  await page.waitForTimeout(900)
  await page.screenshot({ path: `${out}/03d-library-dialog.png` })
  console.log('shot 03d-library-dialog')
  await page.keyboard.press('Escape')
})
await step('library: upload dialog', async () => {
  await page.getByRole('button', { name: /Upload footage/ }).click()
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${out}/03e-library-upload.png` })
  console.log('shot 03e-library-upload')
  await page.keyboard.press('Escape')
})

// ---- same rule after the calibration labels: the guarantee appears
await go('/rule')
await step('rule: theft, with guarantee', async () => { await pickConcept('Package theft'); await shot('05c-rule-theft-guarantee') })

// ---- rule with guarantee
await go('/rule')
await step('rule: unattended', async () => {
  await pickConcept('Package left on the steps')
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /^Why/ }).first().click()
  await page.waitForTimeout(500)
  await shot('05b-rule-guarantee')
})

// ---- live
await go('/live')
await step('live: wait for firings', async () => {
  await page.getByText('Monitor connected').waitFor({ timeout: 10000 })
  await page.waitForTimeout(9000)
  await shot('06a-live', { full: false })
  await page.waitForTimeout(9000)
  await shot('06b-live-later')
})

// ---- eval
await go('/eval')
await page.waitForTimeout(500)
await shot('07a-eval')
await step('eval: tables', async () => {
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: /Show as table/ }).first().click()
  await page.waitForTimeout(300)
  await shot('07b-eval-tables')
})

// ---- phone: screenshots + horizontal overflow check
await page.setViewportSize({ width: 390, height: 844 })
for (const [name, path] of [
  ['08a-mobile-home', '/'], ['08b-mobile-connect', '/connect'], ['08c-mobile-library', '/library'], ['08d-mobile-teach', '/teach'],
  ['08e-mobile-rule', '/rule'], ['08f-mobile-live', '/live'], ['08g-mobile-eval', '/eval'],
]) {
  await go(path)
  await page.waitForTimeout(1200)
  const over = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }))
  if (over.sw > over.cw + 1) {
    const who = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth
      return Array.from(document.querySelectorAll('body *'))
        .filter((el) => el.getBoundingClientRect().right > vw + 1 && !el.closest('.sr-only'))
        .slice(0, 4).map((el) => `${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)}`)
    })
    problems.push(`horizontal overflow at 390px on ${path}: scrollWidth ${over.sw} (${who.join(' | ')})`)
  }
  await shot(name, { full: name !== '08c-mobile-library' })
}

console.log(problems.length ? `PROBLEMS (${problems.length}):\n${problems.join('\n')}` : 'no console errors, no horizontal overflow')
await browser.close()
