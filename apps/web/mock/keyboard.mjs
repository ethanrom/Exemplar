// Keyboard-only walk through the main interactions (WCAG 2.1.1 / 2.4.7 / 2.1.2), against the mock engine.
//   NODE_PATH=d:/tmp/pw/node_modules node mock/keyboard.mjs [http://localhost:3000]
import { createRequire } from 'node:module'

const require = createRequire((process.env.NODE_PATH || 'd:/tmp/pw/node_modules') + '/')
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

await browser.close()
process.exit(failed ? 1 : 0)
