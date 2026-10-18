// The cost-versus-rules table. The numbers are published in docs/eval/cost_vs_rules.md in the repository; this site keeps
// a copy in data/cost_vs_rules.json (written by `node scripts/sync-cost-table.mjs`, checked against the markdown by
// paths.test.ts) so a build from apps/showcase alone has them. Server-side only (uses fs). Strings stay exactly as published.
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { dataRoot } from '../../lib/data/load.ts'
import type { CostRow } from './cost-types.ts'

export const COST_DOC = 'docs/eval/cost_vs_rules.md'
export const COST_SVG = 'docs/eval/cost_vs_rules.svg'
export const COST_SCRIPT = 'eval/plots/cost_vs_rules.py'

export type CostTableDoc = { source: string; note: string; rows: CostRow[] }

/** Parse the markdown table. Throws unless it finds exactly rules 1 to 10 in order. */
export function parseCostTable(markdown: string): CostRow[] {
  const rows: CostRow[] = []
  for (const line of markdown.split(/\r?\n/)) {
    const m = /^\|\s*(\d+)\s*\|\s*(\$[\d.]+)\s*\|\s*(\$[\d.]+)\s*\|\s*(\d+x)\s*\|\s*$/.exec(line)
    if (m) rows.push({ rules: Number(m[1]), exemplar: m[2] as string, zeroShot: m[3] as string, ratio: m[4] as string })
  }
  return checkRows(rows)
}

function checkRows(rows: CostRow[]): CostRow[] {
  if (rows.length !== 10 || rows.some((r, i) => r.rules !== i + 1)) {
    throw new Error(`${COST_DOC}: expected the 10-row cost table (rules 1 to 10), found ${rows.length} rows`)
  }
  return rows
}

/** The file written to data/cost_vs_rules.json. */
export const costTableDoc = (rows: CostRow[]): CostTableDoc => ({
  source: COST_DOC,
  note: 'Copied from the table in the source file, strings unchanged, so the site builds without the rest of the repository.',
  rows,
})

/** Reads the copy in data/cost_vs_rules.json. */
export function loadCostTable(): CostRow[] {
  const doc = JSON.parse(readFileSync(join(dataRoot(), 'cost_vs_rules.json'), 'utf-8')) as CostTableDoc
  return checkRows(doc.rows)
}
