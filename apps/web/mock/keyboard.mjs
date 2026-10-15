// Keyboard-only walk through the main interactions (WCAG 2.1.1 / 2.4.7 / 2.1.2), against the mock engine.
//   node mock/keyboard.mjs [http://localhost:3000]
// playwright-core is not a dependency of the app: install it with `npm i --prefix mock/.cache/pw playwright-core`
// (the default lookup folder, gitignored) or point NODE_PATH at any node_modules folder that contains it.
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const cache = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache')
const require = createRequire(path.resolve(process.env.NODE_PATH || path.join(cache, 'pw', 'node_modules')) + path.sep)
const { chromium } = require('playwright-core')
const base = process.argv[2] || 'http://localhost:3000'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
let failed = 0
const check = (name, ok, extra = '') => { if (!ok) failed++; console.log(`${ok ? 'ok  ' : 'FAIL'} ${name} ${extra}`) }

const focusInfo = () => page.evaluate(() => {
  const el = document.activeElement
  if (!el) return null
  const cs = getComputedStyle(el)
  return { tag: el.tagName, text: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 50), outline: cs.outlineStyle, outlineW: cs.outlineWidth }
})
const tabTo = async (pred, max = 80) => {
  for (let i = 0; i < max; i++) {
    await page.keyboard.press('Tab')
    const f = await focusInfo()
    if (f && pred(f)) return f
  }
  return null
}

await page.goto(base + '/library', { waitUntil: 'networkidle' })
await page.getByRole('button', { name: /View details/ }).first().waitFor()

// 1. skip link is the first stop, visible on focus, and moves focus to <main>
await page.keyboard.press('Tab')
let f = await focusInfo()
check('first Tab stop is the skip link', f?.text === 'Skip to main content', JSON.stringify(f))
await page.keyboard.press('Enter')
check('skip link moves focus to main', (await page.evaluate(() => document.activeElement?.id)) === 'main')

// 2. a visible focus indicator on controls
await page.keyboard.press('Tab')
f = await focusInfo()
check('focused control shows an outline', f && f.outline !== 'none' && parseFloat(f.outlineW) >= 2, JSON.stringify(f))

// 3. label a clip with the keyboard (Space on the "+" toggle)
const plus = page.getByRole('button', { name: /^Mark positive/ }).first()
await plus.focus()
await page.keyboard.press('Space')
await page.waitForTimeout(500)
check('Space toggles the + label (aria-pressed)', (await plus.getAttribute('aria-pressed')) === 'true')
await page.keyboard.press('Shift+Tab')
const minus = page.getByRole('button', { name: /^Clear label/ }).first()
await minus.focus()
await page.keyboard.press('Enter')
await page.waitForTimeout(500)
check('Enter clears the label', (await plus.getAttribute('aria-pressed')) === 'false')

// 4. dialog: opens from the keyboard, traps focus, closes with Escape and returns focus
const trigger = page.getByRole('button', { name: /View details/ }).first()
await trigger.focus()
await page.keyboard.press('Enter')
await page.waitForTimeout(700)
check('dialog opens', await page.locator('dialog[open]').count() === 1)
for (let i = 0; i < 6; i++) await page.keyboard.press('Tab')
check('focus stays inside the dialog', await page.evaluate(() => !!document.activeElement?.closest('dialog')))
await page.keyboard.press('Escape')
await page.waitForTimeout(300)
check('Escape closes the dialog', await page.locator('dialog[open]').count() === 0)
check('focus returns to the trigger', await page.evaluate(() => document.activeElement?.getAttribute('aria-label')?.startsWith('View details')))

// 5. rule screen: the deploy switch is operable with Space
await page.goto(base + '/rule?rule=r_unatt_steps24', { waitUntil: 'networkidle' })
const sw = page.getByRole('switch')
await sw.waitFor()
const before = await sw.getAttribute('aria-checked')
await sw.focus()
await page.keyboard.press('Space')
await page.waitForTimeout(600)
const after = await sw.getAttribute('aria-checked')
check('Space flips the deploy switch', before !== after, `${before} -> ${after}`)
await page.keyboard.press('Space')
await page.waitForTimeout(600)
check('switch restored', (await sw.getAttribute('aria-checked')) === before)

// 6. the backtest "Why" disclosure is a button with aria-expanded
const why = page.getByRole('button', { name: /^Why/ }).first()
await why.focus()
await page.keyboard.press('Enter')
check('Enter expands the witness (aria-expanded)', (await why.getAttribute('aria-expanded')) === 'true')

// 7. evidence screen: the rules slider moves with the arrow keys and the readout follows
await page.goto(base + '/eval', { waitUntil: 'networkidle' })
const slider = page.getByRole('slider', { name: /Rules deployed/ })
await slider.waitFor()
await slider.focus()
const v0 = await slider.inputValue()
await page.keyboard.press('ArrowRight')
const v1 = await slider.inputValue()
check('ArrowRight moves the rules slider', Number(v1) === Number(v0) + 1, `${v0} -> ${v1}`)
check('the readout follows the slider', (await page.getByRole('status').filter({ hasText: /per event and Exemplar/ }).first().innerText()).includes(`${v1}`))

await browser.close()
process.exit(failed ? 1 : 0)
