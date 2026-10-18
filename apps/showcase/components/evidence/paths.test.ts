// Checks that everything the Evidence and Platform pages point at exists in the repository: files, heading anchors,
// and the line each published claim was copied from. Run from apps/showcase:  node --test components/evidence/paths.test.ts
// (included in `npm test`).
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'
import { claim } from './claims.ts'
import { EXTRA_CLAIMS } from './extra-claims.ts'
import { FEEDBACK, HIGHLIGHTS, LOG } from './feedback-data.ts'
import { loadCostTable, parseCostTable } from './cost-table.ts'
import { ROWS } from '../../app/evidence/rows.ts'
import { API_ITEMS } from '../../app/platform/apis.ts'
import { ADDED, EXTENDED, KEPT } from '../../app/platform/sample.ts'
import { loadClaims } from '../../lib/data/load.ts'

const ROOT = join(fileURLToPath(new URL('.', import.meta.url)), '..', '..', '..', '..')
const read = (p: string) => readFileSync(join(ROOT, p), 'utf-8')

// GitHub's heading slug: lower case, drop punctuation, spaces to hyphens.
const slug = (h: string) => h.toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, '').trim().replace(/\s/g, '-')
const slugs = (p: string) => new Set(read(p).split(/\r?\n/).map((l) => /^#{1,6}\s+(.*)$/.exec(l)?.[1]).filter((h): h is string => !!h).map(slug))
const plain = (s: string) => s.replace(/[*`"\s]/g, '').replace(/[’‘]/g, "'")

test('every repository path the pages link to exists', () => {
  const paths = new Set<string>()
  for (const r of ROWS) for (const f of r.files) paths.add(f.path)
  for (const i of API_ITEMS) for (const p of [...i.code, ...i.tests]) paths.add(p)
  for (const c of [...KEPT, ...EXTENDED, ...ADDED]) for (const p of c.where) paths.add(p)
  for (const extra of ['README.md', 'docs/DSL.md', 'docs/eval/cost_vs_rules.md', 'docs/eval/cost_vs_rules.svg', 'eval/plots/cost_vs_rules.py',
    'eval/harness/budget.py', 'apps/web/UPSTREAM.md', 'apps/web/LICENSE', LOG, FEEDBACK]) paths.add(extra)
  const missing = [...paths].filter((p) => !existsSync(join(ROOT, p)))
  assert.deepEqual(missing, [])
})

test('heading anchors exist', () => {
  const log = slugs(LOG)
  for (const h of HIGHLIGHTS) assert.ok(log.has(h.anchor), `${h.id}: no heading with anchor ${h.anchor}`)
  for (const i of API_ITEMS) for (const l of i.log ?? []) assert.ok(log.has(l.anchor), `${l.id}: no heading with anchor ${l.anchor}`)
  assert.ok(slugs('README.md').has('tests-and-verification'))
  assert.ok(slugs('README.md').has('responsible-by-design'))
  assert.ok(slugs(FEEDBACK).has('10-feature-requests'))
})

test('every published claim quotes the line it cites', () => {
  const all = [...loadClaims().claims, ...EXTRA_CLAIMS]
  for (const c of all) {
    const line = c.source.line
    assert.ok(line, `${c.id} has no line`)
    const text = read(c.source.path).split(/\r?\n/)[line - 1] ?? ''
    assert.ok(plain(text).includes(plain(c.source.quote)) || plain(c.source.quote).includes(plain(text)), `${c.id}: line ${line} of ${c.source.path} does not contain the quote`)
  }
})

test('rows only use claims that exist, and each row has a command and a file', () => {
  for (const r of ROWS) {
    for (const id of [...r.claims, ...(r.also ?? [])]) claim(id)
    assert.ok(r.commands.length > 0 && r.files.length > 0, r.id)
  }
  for (const id of ['friction.entries', 'calibration.alpha_default', 'cost.per_event_live', 'cost.per_event_mean', 'cost.rule_eval', 'cost.zero_shot_per_rule',
    'cost.exemplar_flat', 'a11y.axe', 'rule.example_published']) claim(id)
})

test('the cost table parses as ten rows, and the copy this site builds from equals it', () => {
  const rows = parseCostTable(read('docs/eval/cost_vs_rules.md'))
  assert.equal(rows.length, 10)
  assert.deepEqual(loadCostTable(), rows, 'data/cost_vs_rules.json is stale: run node scripts/sync-cost-table.mjs')
})

test('API item ids are unique and each item has code and tests', () => {
  const ids = API_ITEMS.map((i) => i.id)
  assert.equal(new Set(ids).size, ids.length)
  for (const i of API_ITEMS) assert.ok(i.code.length > 0 && i.tests.length > 0, i.id)
})
