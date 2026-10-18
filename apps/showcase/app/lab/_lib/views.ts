// View models of the Lab: the same candidate list shape whether it comes from the recorded run, from the in-browser
// recomputation, or from the engine's grid entry. Pure.
import type { CandidateView } from '../../../components/lab/CandidateList.tsx'
import type { RunDoc, RunEvent } from '../../../lib/data/types.ts'
import type { CandidateItem } from '../../../lib/synth/session.ts'
import type { RunEvent as SynthEvent } from '../../../lib/synth/state.ts'
import type { EngineListItem } from './compare.ts'
import type { LabRule } from './types.ts'

/** The recorded run's candidates in recorded order: rank = position, with each rule's own recorded rank and selection label. */
export function recordedViews(run: Pick<RunDoc, 'candidates'>, rules: Record<string, LabRule>): CandidateView[] {
  return run.candidates.map((slug, i) => {
    const r = rules[slug] as LabRule
    return {
      key: r.dsl_text, rank: i + 1, dsl_text: r.dsl_text, sketch_text: r.sketch_text, english: r.english, holes: r.holes,
      margin: r.margin, mdl: r.mdl, violated: r.violations,
      recorded: r.recorded_rank ? { position: r.recorded_rank.position, of: r.recorded_rank.of } : null,
      selection: r.selection,
    }
  })
}

/** Rules of a run by their closed DSL text, to give a recomputed candidate its recorded rank and selection label. */
export function rulesByText(run: Pick<RunDoc, 'candidates'>, rules: Record<string, LabRule>): Map<string, LabRule> {
  return new Map(run.candidates.map((s) => [(rules[s] as LabRule).dsl_text, rules[s] as LabRule] as const))
}

export function itemViews(items: readonly CandidateItem[], recorded?: ReadonlyMap<string, LabRule>, engine?: readonly EngineListItem[] | null): CandidateView[] {
  return items.map((it) => {
    const r = recorded?.get(it.dsl_text)
    const e = engine?.find((x) => x.dsl_text === it.dsl_text)
    return {
      key: it.dsl_text, rank: it.rank, dsl_text: it.dsl_text, sketch_text: it.sketch_text, english: it.english, holes: it.holes,
      margin: it.margin, mdl: it.mdl, violated: it.violated_clip_ids,
      recorded: r?.recorded_rank ? { position: r.recorded_rank.position, of: r.recorded_rank.of } : null,
      selection: r?.selection ?? null,
      engineRank: engine ? (e ? e.rank : null) : undefined,
    }
  })
}

export function engineViews(list: readonly EngineListItem[]): CandidateView[] {
  return list.map((e) => ({
    key: e.dsl_text, rank: e.rank, dsl_text: e.dsl_text, sketch_text: '', english: e.english, holes: e.holes, margin: e.margin, mdl: e.mdl,
    violated: e.violated_clip_ids,
  }))
}

/** Events from the worker get a sequence number and the time since the request started. */
export function stamp(e: SynthEvent, seq: number, t0: number): RunEvent {
  return {
    seq, t_ms: Math.round(performance.now() - t0), type: e.type as RunEvent['type'], round: e.round, sketch: e.sketch ?? null,
    error: e.error ?? null, result: (e.result ?? null) as RunEvent['result'], holes: e.holes ?? null, margin: e.margin ?? null,
    violated_clip_ids: e.violated_clip_ids, rule_ids: e.rule_ids, message: e.message ?? null,
  }
}

/** The default selection: the rule the run labels as selected, else the first. */
export function defaultSelection(views: readonly CandidateView[]): string | null {
  return (views.find((v) => v.selection) ?? views[0])?.key ?? null
}
