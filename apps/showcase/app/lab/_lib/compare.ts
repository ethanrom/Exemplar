// The comparator (SPEC 6.4, 6.5): it runs on the main thread after a solve has finished for the current request, and only
// then reads the grid or the recorded run. The solver in the worker never sees either.
import { fillHoles, parse, toEnglish, toText } from '../../../lib/dsl/index.ts'
import type { Rule, Trace } from '../../../lib/dsl/index.ts'
import { makeExampleContext, solveSketchExhaustive } from '../../../lib/synth/exhaustive.ts'
import type { CandidateItem, LabData, SketchOutcome, States } from '../../../lib/synth/session.ts'
import { examplesOf, slotOf } from '../../../lib/synth/session.ts'
import { categorize } from '../../../lib/synth/compare/categorize.ts'
import type { Category, EngineEntry } from '../../../lib/synth/compare/categorize.ts'
import type { Grid } from '../../../lib/synth/compare/grid.ts'
import type { RunEvent, RuleDoc, RunDoc } from '../../../lib/data/types.ts'

const STATUS = ['sat', 'unsat', 'rejected', 'timeout', 'grid_fallback', 'error'] as const

/** A macrotask break, so a long comparison never holds the main thread for more than a few milliseconds. */
export const yieldNow = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

export type EngineListItem = {
  rank: number
  sketch_id: number
  dsl_text: string
  english: string
  holes: Record<string, number>
  margin: number
  mdl: number
  violated_clip_ids: string[]
}

export type FreeCheck = {
  slot: number
  /** One entry per bank sketch the solver answered. */
  total: number
  counts: Record<Category, number> & { rejected: number; missing: number }
  /** Each non-identical entry: the sketch id and why (exact wording of the comparator). */
  notes: { sketch_id: number; category: Category | 'rejected' | 'missing'; reason: string }[]
  top6: 'same' | 'explained' | 'mismatch' | 'missing'
  /** The engine's own list for this slot (to show when the lists differ). */
  engineList: EngineListItem[] | null
  mdlChecked: number
  mdlMismatch: number
  /** Everything that is not a clean match, as sentences. Empty means a clean "matches the engine". */
  problems: string[]
}

function engineList(grid: Grid, data: LabData, slot: number): EngineListItem[] | null {
  const top = grid.top6(slot)
  if (top === null) return null
  const out: EngineListItem[] = []
  top.forEach((id, i) => {
    const e = grid.entry(id, slot)
    if (e === null || e.holes === null || e.margin === null) return
    const names = grid.holeNames(id)
    const holes = Object.fromEntries(names.map((n, k) => [n, e.holes![k] as number]))
    const sketch = parse((data.sketches[id] as { text: string }).text)
    const closed = fillHoles(sketch, holes)
    out.push({
      rank: i + 1, sketch_id: id, dsl_text: toText(closed), english: toEnglish(closed), holes, margin: e.margin, mdl: e.mdl ?? NaN,
      violated_clip_ids: e.violated === null ? [] : grid.violatedIds(e.violated),
    })
  })
  return out
}

/** Compare a finished free-play solve with the grid's entry for the same label combination. */
export async function compareFree(
  grid: Grid, data: LabData, states: States, outcomes: readonly SketchOutcome[], items: readonly CandidateItem[], isCurrent: () => boolean,
): Promise<FreeCheck | null> {
  const slot = slotOf(states)
  const ctx = makeExampleContext(examplesOf(data, states))
  const counts: FreeCheck['counts'] = { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0, rejected: 0, missing: 0 }
  const notes: FreeCheck['notes'] = []
  const problems: string[] = []
  let t0 = performance.now()
  let allIdentical = true
  for (const o of outcomes) {
    const g = grid.entry(o.sketch_id, slot)
    if (g === null) {
      counts.missing++
      allIdentical = false
      notes.push({ sketch_id: o.sketch_id, category: 'missing', reason: 'the grid has no entry for this label combination' })
      continue
    }
    if (o.result === null) {
      if (g.status === 2) counts.rejected++
      else {
        counts.mismatch++
        allIdentical = false
        problems.push(`sketch ${o.sketch_id}: rejected here, engine status ${STATUS[g.status]}`)
        notes.push({ sketch_id: o.sketch_id, category: 'mismatch', reason: `rejected here, engine status ${STATUS[g.status]}` })
      }
      continue
    }
    const names = grid.holeNames(o.sketch_id)
    const engine: EngineEntry = {
      status: STATUS[g.status] as EngineEntry['status'],
      holes: g.holes === null ? null : Object.fromEntries(names.map((n, i) => [n, g.holes![i] as number])),
      margin: g.margin,
      violated: g.violated === null ? null : grid.violatedIds(g.violated),
      placement: g.placement,
    }
    const v = categorize(o.result.sketch as Rule, ctx, o.result, engine)
    counts[v.category]++
    if (v.category !== 'identical') {
      allIdentical = false
      notes.push({ sketch_id: o.sketch_id, category: v.category, reason: v.reason })
      if (v.category === 'mismatch') problems.push(`sketch ${o.sketch_id}: ${v.reason}`)
    }
    if (performance.now() - t0 > 10) {
      await yieldNow()
      if (!isCurrent()) return null
      t0 = performance.now()
    }
  }

  let mdlChecked = 0
  let mdlMismatch = 0
  for (const it of items) {
    const g = grid.entry(it.sketch_id, slot)
    if (g?.mdl == null) continue
    mdlChecked++
    if (Math.abs(it.mdl - g.mdl) > 1e-12 * Math.max(1, Math.abs(g.mdl))) {
      mdlMismatch++
      problems.push(`candidate from sketch ${it.sketch_id}: description length ${it.mdl} vs engine ${g.mdl}`)
    }
  }

  const gridTop = grid.top6(slot)
  const engList = engineList(grid, data, slot)
  let top6: FreeCheck['top6'] = 'missing'
  if (gridTop !== null) {
    const mine = items.map((i) => i.sketch_id)
    // the same sketches in the same order can still print different rules: a tied alternative places its blanks differently
    const sameRules = engList !== null && engList.length === items.length && engList.every((e, i) => e.dsl_text === (items[i] as CandidateItem).dsl_text)
    if (JSON.stringify(mine) === JSON.stringify(gridTop) && sameRules) top6 = 'same'
    else if (!allIdentical) top6 = 'explained'
    else {
      top6 = 'mismatch'
      problems.push(`candidate list ${JSON.stringify(mine)} vs engine ${JSON.stringify(gridTop)}`)
    }
  }
  return {
    slot, total: outcomes.length, counts, notes, top6, engineList: engList, mdlChecked, mdlMismatch, problems,
  }
}

// ---------------------------------------------------------------------------------------------- presets

export type PresetCheck = {
  solves: number
  counts: Record<Category, number>
  notes: { sketch: string; category: Category; reason: string }[]
  /** Solves the recomputation made that the recorded run did not (should be 0). */
  extra: number
  candidates: { same: boolean; mine: string[]; recorded: string[] }
  problems: string[]
}

const sameSet = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x) => b.includes(x))
const sameHoles = (a: Readonly<Record<string, number>> | null | undefined, b: Readonly<Record<string, number>> | null | undefined) => {
  const x = a ?? {}
  const y = b ?? {}
  const kx = Object.keys(x)
  return kx.length === Object.keys(y).length && kx.every((k) => y[k] === x[k])
}

type SolveEvent = Pick<RunEvent, 'sketch' | 'result' | 'holes' | 'margin' | 'violated_clip_ids' | 'message'> & { type: string }

/**
 * Compare the recomputed run with the recorded one: every recorded solve_result against the recomputed event for the same
 * sketch, and the final candidate order against the recorded `candidates`. Entries that differ are classified by the
 * comparator (tie-verified, engine-supplied or mismatch) with the solver asked once for that sketch.
 */
export async function comparePreset(
  run: Pick<RunDoc, 'events'>,
  mine: readonly SolveEvent[],
  mineCandidates: readonly string[],
  recordedCandidates: readonly string[],
  traces: Record<string, Trace>,
  examples: readonly { alias: string; positive: boolean; weight: number }[],
  isCurrent: () => boolean,
): Promise<PresetCheck | null> {
  const recorded = run.events.filter((e) => e.type === 'solve_result' && e.sketch)
  const mineSolves = mine.filter((e) => e.type === 'solve_result' && e.sketch)
  const counts: PresetCheck['counts'] = { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0 }
  const notes: PresetCheck['notes'] = []
  const problems: string[] = []
  let ctx: ReturnType<typeof makeExampleContext> | null = null
  for (const r of recorded) {
    const m = mineSolves.find((x) => x.sketch === r.sketch)
    if (!m) {
      counts.mismatch++
      problems.push(`no recomputed solve for: ${r.sketch}`)
      continue
    }
    const identical = m.result === r.result && m.margin === r.margin && sameHoles(m.holes, r.holes) && sameSet(m.violated_clip_ids ?? [], r.violated_clip_ids ?? [])
    if (identical) {
      counts.identical++
      continue
    }
    if (r.result === 'timeout' || r.result === 'grid_fallback' || (m.result as string | null | undefined) === 'budget_exceeded') {
      counts.engine_supplied++
      notes.push({ sketch: r.sketch as string, category: 'engine_supplied', reason: `engine status ${r.result}` })
      continue
    }
    // classify with the solver, asked once for this sketch
    const exs = examples.map((e) => ({ trace: traces[e.alias] as Trace, positive: e.positive, weight: e.weight, clip_id: e.alias }))
    ctx ??= makeExampleContext(exs)
    const sketch = parse(r.sketch as string)
    const ts = solveSketchExhaustive(sketch, ctx)
    const placement = /placement: ([^;]+)/.exec(r.message ?? '')?.[1] ?? null
    const v = categorize(sketch, ctx, ts, {
      status: (r.result ?? 'unsat') as EngineEntry['status'], holes: r.holes ?? null, margin: r.margin ?? null, violated: r.violated_clip_ids ?? [], placement,
    })
    counts[v.category]++
    notes.push({ sketch: r.sketch as string, category: v.category, reason: v.reason })
    if (v.category === 'mismatch') problems.push(`${r.sketch}: ${v.reason}`)
    await yieldNow()
    if (!isCurrent()) return null
  }
  const extra = mineSolves.filter((m) => !recorded.some((r) => r.sketch === m.sketch)).length
  if (extra > 0) problems.push(`${extra} recomputed solve(s) the recorded run did not make`)
  const same = JSON.stringify(mineCandidates) === JSON.stringify(recordedCandidates)
  if (!same) problems.push('the candidate order differs from the recorded run')
  return { solves: recorded.length, counts, notes, extra, candidates: { same, mine: [...mineCandidates], recorded: [...recordedCandidates] }, problems }
}

/** The recorded run's candidates as rule texts, in recorded order (rank = index + 1). */
export const recordedCandidateTexts = (rules: Record<string, Pick<RuleDoc, 'dsl_text'>>, run: Pick<RunDoc, 'candidates'>): string[] =>
  run.candidates.map((s) => (rules[s] as { dsl_text: string }).dsl_text)
