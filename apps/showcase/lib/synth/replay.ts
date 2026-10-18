// The counterexample-guided synthesis loop with a replay proposer.
// Port of engine/exemplar/agent/cegis.py (`run_cegis`), with the proposer replaced by the recorded sketch texts:
//
//   for round in 1..max_rounds:
//       proposals = the recorded texts of that round         (the LLM agent, in the recorded session)
//       submit each (typecheck, canonicalise, deduplicate), solve the first K accepted
//       stop when K consistent candidates exist, or the round added nothing new
//   if fewer than K are consistent: the recorded template back-fill round, solved the same way
//   rank by MDL ascending then margin descending; emit `candidates`, `done`.
//
// The loop is synchronous; the caller (the worker session) runs it in slices through `step` generators or checks
// `isCancelled` between sketches.

import { RunState } from "./state.ts";
import type { RunEvent } from "./state.ts";
import { Cancelled } from "./types.ts";
import type { Candidate, Example } from "./types.ts";

/** One round of recorded proposals (`RunDoc.proposals_by_round`). */
export interface RecordedRound {
  round: number;
  backfill: boolean;
  texts: readonly string[];
}

export interface ReplayOptions {
  k?: number;
  maxRounds?: number;
  isCancelled?: () => boolean;
  maxClasses?: number;
}

/** The end state of a replay: the ranked candidates and the state (for per-sketch records). */
export interface ReplayResult {
  candidates: Candidate[];
  state: RunState | null;
}

export function runReplay(
  examples: readonly Example[], rounds: readonly RecordedRound[], emit: (e: RunEvent) => void, opts: ReplayOptions = {},
): ReplayResult {
  const k = opts.k ?? 6;
  const maxRounds = opts.maxRounds ?? 4;
  if (!examples.some((e) => e.positive)) {
    emit({ type: "done", message: "need at least one positive example" });
    return { candidates: [], state: null };
  }
  const state = new RunState(examples, emit, { k, isCancelled: opts.isCancelled, maxClasses: opts.maxClasses });
  const normal = rounds.filter((r) => !r.backfill);
  const backfill = rounds.find((r) => r.backfill);
  const top = (): Candidate[] => state.candidates().slice(0, k);
  try {
    for (let r = 1; r <= maxRounds; r++) {
      state.checkCancel();
      state.startRound(r);
      const before = state.records.size;
      emit({ type: "round_started", round: r, message: "proposer: replay of the recorded session" });
      const rec = normal.find((x) => x.round === r);
      const proposals = rec ? rec.texts : [];
      for (const text of proposals.slice(0, Math.max(k * 2, 1))) state.submit(text);
      const todo = state.acceptedThisRound.slice(0, k);
      for (const canon of todo) state.solve(canon);
      if (state.nConsistent() >= k) break;
      if (state.records.size === before && todo.length === 0) {
        emit({ type: "round_started", round: r, message: "no new sketches proposed; stopping" });
        break;
      }
    }
    if (state.nConsistent() < k && backfill !== undefined) {
      state.checkCancel();
      state.startRound(state.round);
      const extra = backfill.texts;
      if (extra.length > 0) {
        emit({ type: "round_started", round: state.round, message: "template-library back-fill" });
        for (const text of extra) state.submit(text);
        for (const canon of state.acceptedThisRound.slice(0, k)) state.solve(canon);
      }
    }
  } catch (e) {
    if (e instanceof Cancelled) {
      emit({ type: "done", message: "cancelled" });
      return { candidates: top(), state };
    }
    throw e;
  }
  const out = top();
  emit({
    type: "candidates", round: state.round, rule_ids: [],
    message: `${out.length} candidate(s), ${out.filter((c) => c.violated_clip_ids.length === 0).length} consistent with every example`,
  });
  emit({ type: "done", round: state.round, message: `${state.solved().length} sketches solved` });
  return { candidates: out, state };
}
