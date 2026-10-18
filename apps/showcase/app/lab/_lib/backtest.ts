// The backtest panel's computation: a closed rule scored on every library clip by the in-browser evaluator, grouped by
// class, and cross-checked against the engine's own scores (the recorded backtest of a recorded rule, or closed.json).
import { compileRule } from '../../../lib/dsl/index.ts'
import type { ClipCard, ClipClass, TraceJson } from '../../../lib/data/types.ts'
import { asTrace, parseCached, prep } from '../../../components/lab/core/rules.ts'

export type BacktestRow = { alias: string; title: string; cls: ClipClass; score: number; matched: boolean }
export type ClassTally = { cls: ClipClass; label: string; matched: number; total: number }

export const CLASS_LABEL: Record<ClipClass, string> = {
  pg_package: 'Playground recordings: package',
  pg_vehicle: 'Playground recordings: vehicle',
  pg_bird: 'Playground recordings: birds',
  frollard: 'Doorstep video windows',
  meva: 'Parking-lot clips',
  ringtv_fox: 'Fox clips',
}
const CLASS_ORDER: ClipClass[] = ['pg_package', 'pg_vehicle', 'pg_bird', 'frollard', 'meva', 'ringtv_fox']

/** Score a closed rule (its DSL text) on every library clip; `matched` is score > tau. */
export function backtest(dslText: string, library: readonly ClipCard[], traces: Record<string, TraceJson>, tau = 0): BacktestRow[] {
  const cr = compileRule(parseCached(dslText))
  const rows: BacktestRow[] = []
  for (const c of library) {
    const t = traces[c.alias]
    if (!t) continue
    const score = cr.score(prep(t))
    rows.push({ alias: c.alias, title: c.title, cls: c.class, score, matched: score > tau })
  }
  return rows
}

export function tally(rows: readonly BacktestRow[]): ClassTally[] {
  return CLASS_ORDER.map((cls) => {
    const of = rows.filter((r) => r.cls === cls)
    return { cls, label: CLASS_LABEL[cls], matched: of.filter((r) => r.matched).length, total: of.length }
  }).filter((t) => t.total > 0)
}

export type CrossCheck = { checked: number; identical: number; differences: { alias: string; mine: number; engine: number }[] }

/** Compare my scores with the engine's (by clip alias). Exact equality: both sides are IEEE doubles from the same operations. */
export function crossCheck(rows: readonly BacktestRow[], engine: ReadonlyMap<string, number>): CrossCheck {
  let checked = 0
  let identical = 0
  const differences: CrossCheck['differences'] = []
  for (const r of rows) {
    const e = engine.get(r.alias)
    if (e === undefined) continue
    checked++
    if (e === r.score) identical++
    else differences.push({ alias: r.alias, mine: r.score, engine: e })
  }
  return { checked, identical, differences }
}

/** The witness input a clip detail needs. */
export const traceOf = (traces: Record<string, TraceJson>, alias: string) => asTrace(traces[alias] as TraceJson)
