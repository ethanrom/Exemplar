// Builds what the Lab hands to the Z3 check (lib/synth/z3/model.ts Z3Inputs) from the candidates it is showing. Pure.
import type { Trace } from '../../lib/dsl/index.ts'
import { pickItems, wireExamples, type Z3Inputs } from '../../lib/synth/z3/model.ts'
import type { Reference } from '../../lib/synth/z3/verdict.ts'

/** The fields of a Lab candidate view this needs (structurally a `CandidateView`). */
export type CandidateLike = {
  key: string
  sketch_text: string
  holes: Record<string, number>
  margin: number
  /** Aliases of the labelled examples the rule gets wrong. */
  violated: string[]
}

export type LabelledClip = { alias: string; positive: boolean; weight: number; trace: Trace }

/**
 * The selected rule first, then the top candidates (7 at most), each with the result the Lab shows for it:
 * `source` says whether that result was computed in the browser or supplied by the engine. `extra` adds what the Lab knows
 * beyond the view (the placement note, the optimal sets).
 */
export function labInputs(a: {
  requestKey: string
  ready: boolean
  examples: readonly LabelledClip[] | null
  views: readonly CandidateLike[]
  selectedKey: string | null
  source: Reference['source']
  extra?: (v: CandidateLike) => Partial<Reference>
}): Z3Inputs {
  const weight = new Map((a.examples ?? []).map((e) => [e.alias, e.weight] as const))
  const items = pickItems(a.views, a.selectedKey).map((v) => ({
    key: v.key,
    sketch: v.sketch_text,
    reference: {
      source: a.source,
      status: 'sat',
      holes: v.holes,
      margin: v.margin,
      violated: v.violated,
      violatedWeight: v.violated.reduce((w, alias) => w + (weight.get(alias) ?? 0), 0),
      ...a.extra?.(v),
    } satisfies Reference,
  }))
  return { requestKey: a.requestKey, ready: a.ready, examples: a.examples ? wireExamples(a.examples) : null, items }
}

/** The placement note of a recorded solve_result for `sketch` ("slack-centre", "slack-stepback(0.75)", ...), if the run has one. */
export function recordedPlacement(events: readonly { type: string; sketch?: string | null; message?: string | null }[], sketch: string): string | null {
  const e = events.find((x) => x.type === 'solve_result' && x.sketch === sketch)
  return e?.message ? (/placement: ([^;]+)/.exec(e.message)?.[1] ?? null) : null
}
