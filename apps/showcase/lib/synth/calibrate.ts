// Calibrating a closed rule on random-labelled clips. Port of engine/exemplar/calibrate/rule.py (`calibrate`): score
// the rule on every labelled clip with the evaluator, take tau from the negatives (conformal.ts) and the recall with
// its Clopper-Pearson interval from the positives.
//
// The caller is responsible for the provenance rule (docs/DSL.md "Label provenance"): only `random` labels, held out
// from synthesis, may be passed. Every clip may appear once.

import type { PreparedTrace, Rule, Trace } from "../dsl/index.ts";
import { robustness } from "../dsl/evaluator.ts";
import { calibrateScores } from "./conformal.ts";
import type { Calibration } from "./conformal.ts";

export interface RandomLabelled {
  readonly clip_id: string;
  readonly trace: Trace | PreparedTrace;
  readonly positive: boolean;
}

/** The scores of the rule on the labelled clips (pos / neg) and the resulting calibration. */
export function calibrate(
  rule: Rule, labelled: readonly RandomLabelled[], alpha: number,
): { calibration: Calibration; pos: number[]; neg: number[] } {
  const seen = new Set<string>();
  for (const l of labelled) {
    if (seen.has(l.clip_id)) throw new Error(`clip ${l.clip_id} appears twice in the calibration set`);
    seen.add(l.clip_id);
  }
  const pos: number[] = [];
  const neg: number[] = [];
  for (const l of labelled) (l.positive ? pos : neg).push(robustness(rule, l.trace));
  return { calibration: calibrateScores(pos, neg, alpha), pos, neg };
}
