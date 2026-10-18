import type { Conf, TraceJson } from '@/lib/data/types.ts'
import { factText } from './format.ts'

// Grouping of a trace's per-frame facts into rows (pure, so Node can test it).

export const CONF_RANK: Record<Conf, number> = { high: 3, med: 2, low: 1 }

export type FactRow = { key: string; text: string; cells: (Conf | null)[]; seen: number; levels: Conf[]; first: number }

/** Group a trace's per-frame facts into one row per distinct fact (predicate and arguments). */
export function factRows(trace: TraceJson): FactRow[] {
  const rows = new Map<string, FactRow>()
  trace.frames.forEach((frame, i) => {
    for (const fact of frame.facts) {
      const key = factText(fact.pred, fact.args)
      let row = rows.get(key)
      if (!row) {
        row = { key, text: key, cells: trace.frames.map(() => null), seen: 0, levels: [], first: i }
        rows.set(key, row)
      }
      const had = row.cells[i]
      // Duplicates inside a frame keep the strongest confidence (the evaluator takes the max as well).
      if (!had || CONF_RANK[fact.conf] > CONF_RANK[had]) row.cells[i] = fact.conf
      if (!had) row.seen += 1
      if (!row.levels.includes(fact.conf)) row.levels.push(fact.conf)
    }
  })
  return Array.from(rows.values())
    .map((r) => ({ ...r, levels: r.levels.sort((a, b) => CONF_RANK[b] - CONF_RANK[a]) }))
    .sort((a, b) => b.seen - a.seen || a.first - b.first)
}

