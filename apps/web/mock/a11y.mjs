// Automated WCAG 2.2 AA scan of every screen with axe-core (run against the mock engine).
//
//   node mock/a11y.mjs [http://localhost:3000]
//
// playwright-core and axe-core are not dependencies of the app. By default they are looked up in the gitignored
// mock/.cache/ folder:
//   npm i --prefix mock/.cache/pw playwright-core
//   npm i --prefix mock/.cache/axe axe-core
// Override with NODE_PATH (a node_modules folder containing playwright-core) and AXE_PATH (path to axe.min.js).
// Prints violations per page; exit code 1 when any are found.
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const cache = path.join(path.dirname(fileURLToPath(import.meta.url)), '.cache')
const require = createRequire(path.resolve(process.env.NODE_PATH || path.join(cache, 'pw', 'node_modules')) + path.sep)
const { chromium } = require('playwright-core')
const axeSource = readFileSync(process.env.AXE_PATH || path.join(cache, 'axe', 'node_modules', 'axe-core', 'axe.min.js'), 'utf8')
const base = process.argv[2] || 'http://localhost:3000'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
let failures = 0

async function scan(label, path, prep) {
  await page.goto(base + path, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  if (prep) await prep()
  await page.evaluate(axeSource)
  const res = await page.evaluate(() =>
    // eslint-disable-next-line no-undef
    axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] } }),
  )
  const v = res.violations
  failures += v.length
  console.log(`${v.length ? 'FAIL' : 'ok  '} ${label}: ${v.length} violation(s), ${res.passes.length} rules passed`)
  for (const x of v) {
    console.log(`   - [${x.impact}] ${x.id}: ${x.help} (${x.nodes.length} node(s))`)
    for (const n of x.nodes.slice(0, 3)) console.log(`       ${n.target.join(' ')}  ${(n.failureSummary || '').split('\n')[1] || ''}`)
  }
}

await scan('home', '/')
await scan('connect', '/connect')
await scan('library', '/library')
await scan('library + calibration panel', '/library?concept=cn_theft&calibrate=1', async () => { await page.waitForTimeout(800) })
await scan('library + event dialog', '/library', async () => {
  await page.getByRole('button', { name: /View details/ }).first().click()
  await page.waitForTimeout(800)
})
await scan('teach', '/teach')
await scan('teach after a run', '/teach', async () => {
  await page.getByLabel('Concept').first().selectOption({ label: 'Package theft' })
  await page.getByRole('button', { name: /^Teach/ }).first().click()
  await page.getByText('Should this one count?').waitFor({ timeout: 20000 })
  await page.waitForTimeout(500)
})
await scan('rule', '/rule?rule=r_unatt_steps24', async () => {
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /^Why/ }).first().click()
})
await scan('live', '/live', async () => { await page.waitForTimeout(9000) })
await scan('evidence', '/eval')
await scan('evidence as a table', '/eval', async () => { await page.getByRole('button', { name: /Show as table/ }).click() })

await browser.close()
process.exit(failures ? 1 : 0)
