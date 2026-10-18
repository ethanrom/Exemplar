// Copies the cost-versus-rules table from the repository's docs/eval/cost_vs_rules.md into data/cost_vs_rules.json, so
// the site builds from apps/showcase alone (Vercel's root directory). Run from apps/showcase after the table changes:
//   node scripts/sync-cost-table.mjs
// components/evidence/paths.test.ts fails when the committed JSON differs from the markdown.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { COST_DOC, COST_SCRIPT, COST_SVG, costTableDoc, parseCostTable } from '../components/evidence/cost-table.ts'

const here = dirname(fileURLToPath(import.meta.url))
const markdown = readFileSync(join(here, '..', '..', '..', COST_DOC), 'utf-8')
const doc = costTableDoc(parseCostTable(markdown))
writeFileSync(join(here, '..', 'data', 'cost_vs_rules.json'), JSON.stringify(doc, null, 1) + '\n', 'utf-8')
console.log(`data/cost_vs_rules.json: ${doc.rows.length} rows copied from ${COST_DOC} (chart ${COST_SVG}, script ${COST_SCRIPT})`)
