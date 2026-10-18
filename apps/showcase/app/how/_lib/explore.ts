// Chapter 4's computation, kept apart from the component so a node test can pin it to the recorded witnesses.
import { holesOf, rho as rhoAt, witness } from '../../../lib/dsl/index.ts'
import type { Phi, Rule, Witness } from '../../../lib/dsl/index.ts'
import type { LiveDecision, TraceJson, WitnessJson } from '../../../lib/data/types.ts'
import { asTrace } from '../../../components/lab/core/rules.ts'

export type Exploration = {
  witness: Witness
  /** Robustness of the part of the rule that has to hold, at each sampled frame, for the bound entities. */
  rho: number[]
  /** The window the rule asked about, in ms (a holds_for / eventually / always window), or null for a single moment. */
  window: { startMs: number; endMs: number } | null
  /** The moment of the first piece of evidence, in ms, or null. */
  evidenceMs: number | null
}

/** The part of the body the strip plots: the argument of holds_for / eventually / always, else the body itself. */
function plotted(body: Phi): Phi {
  return body.op === 'holds_for' || body.op === 'eventually' || body.op === 'always' ? body.arg : body
}

/** Run the DSL evaluator and the witness extractor on one clip with the rule's blank (if any) set to `value`. */
export function explore(sketch: Rule, trace: TraceJson, hole: string | null, value: number | null): Exploration {
  const holes = hole !== null && value !== null ? { [hole]: value } : {}
  const t = asTrace(trace)
  const w = witness(sketch, t, holes)
  const T = trace.frames.length
  let rho: number[] = new Array<number>(T).fill(-0.5)
  if (Object.keys(w.bindings).length > 0) rho = rhoAt(plotted(sketch.body), t, w.bindings, holes)
  const root = w.spans.find((s) => s.path === 'body')
  const window = root && root.t_end_ms > root.t_start_ms && root.op !== 'and' && root.op !== 'or'
    ? { startMs: root.t_start_ms, endMs: root.t_end_ms } : null
  const atom = w.spans.find((s) => s.op === 'atom')
  return { witness: w, rho, window, evidenceMs: atom ? atom.t_start_ms : (root ? root.t_start_ms : null) }
}

/** The single blank of a sketch, or null when it has none (or several: the explorer drags one blank). */
export function singleHole(sketch: Rule): string | null {
  const hs = holesOf(sketch)
  return hs.length === 1 ? (hs[0] as string) : null
}

/** Does a computed witness equal a recorded one exactly (score, bindings and every span's path, op, text, times, rho)? */
export function sameWitness(a: Witness, b: WitnessJson): boolean {
  if (a.score !== b.score || a.spans.length !== b.spans.length) return false
  const ka = Object.keys(a.bindings)
  if (ka.length !== Object.keys(b.bindings).length || ka.some((k) => a.bindings[k] !== b.bindings[k])) return false
  return a.spans.every((s, i) => {
    const r = b.spans[i] as WitnessJson['spans'][number]
    return s.path === r.path && s.op === r.op && s.text === r.text && s.t_start_ms === r.t_start_ms && s.t_end_ms === r.t_end_ms && s.rho === r.rho
  })
}

/** Compare a recomputation with the recorded decision: the full witness when the rule fired, else the score alone. */
export function matchesRecorded(w: Witness, decision: LiveDecision): boolean {
  return decision.witness ? sameWitness(w, decision.witness) : w.score === decision.score
}
