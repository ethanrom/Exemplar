// Value types of the synthesis layer. Port of engine/exemplar/synth/types.py (the Z3-only parts are gone: this
// package solves by exhaustive enumeration of hole equivalence classes).

import type { PreparedTrace, Rule, Trace } from "../dsl/index.ts";

/** One labelled clip given to the solver. */
export interface Example {
  readonly trace: Trace | PreparedTrace;
  readonly positive: boolean;
  /** Label weight (1 bulk, 3 user-confirmed). */
  readonly weight: number;
  /** Defaults to the trace's clip_id. */
  readonly clip_id: string;
}

/** Build an `Example`; weight defaults to 1, clip_id to the trace's. */
export function makeExample(trace: Trace | PreparedTrace, positive: boolean, weight = 1.0, clipId = ""): Example {
  if (!(weight > 0)) throw new RangeError(`example weight must be positive, got ${weight}`);
  const id = clipId !== "" ? clipId : "trace" in trace ? trace.trace.clip_id : trace.clip_id;
  return { trace, positive, weight, clip_id: id };
}

/** The sketch cannot be encoded (ill-typed, or a hole used as both an hour and a time). */
export class SketchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SketchError";
  }
}

/** The solve was abandoned at a check-point because the request was cancelled. */
export class Cancelled extends Error {
  constructor() {
    super("cancelled");
    this.name = "Cancelled";
  }
}

/**
 * Outcome of solving one sketch (engine statuses: sat, unsat, timeout, grid_fallback). The TypeScript solver never
 * reports a budget overrun as `unsat`: it reports `budget_exceeded`, and the caller shows the engine's result.
 *
 *  - `sat`: the best assignment beats the trivial rule that never fires; `rule` is the closed, placed rule.
 *  - `unsat`: the sketch cannot express the concept on these clips (also: the hole domain is empty); `rule` is null.
 *  - `budget_exceeded`: more hole classes than the in-browser budget (or an unsupported constant); nothing computed.
 */
export type SolveStatus = "sat" | "unsat" | "budget_exceeded";

export interface SolveResult {
  readonly status: SolveStatus;
  readonly sketch: Rule;
  readonly rule: Rule | null;
  /** Hole values by name (empty unless sat). */
  readonly holes: Readonly<Record<string, number>>;
  /** The optimal margin level (0 unless sat). */
  readonly margin: number;
  /** Clip ids the returned assignment gets wrong (for unsat: the witness's), in example order. */
  readonly violated: readonly string[];
  readonly satisfied: readonly string[];
  /** Hole-class points enumerated (the raw product size before the ordering filter is `classProduct`). */
  readonly classes: number;
  readonly classProduct: number;
  /**
   * Distinct optimal satisfied sets at the optimal (violated weight, margin) - for unsat at the lowest margin level,
   * the level the engine's witness comes from. 0 when the hole domain is empty or the budget was exceeded.
   */
  readonly alternatives: number;
  /** Those sets as clip-id lists, in enumeration order (the first one is the one reported). */
  readonly optimalSets: readonly (readonly string[])[];
  /** How the holes were placed ("slack-centre", "slack-stepback-grid(0.5)", ... or "no holes"). */
  readonly placement: string;
  readonly note: string;
  readonly solveMs: number;
}

/** A ranked rule: what the run returns (engine `Candidate`). */
export interface Candidate {
  readonly sketch_text: string;
  readonly dsl_text: string;
  readonly english: string;
  readonly rule: Rule;
  readonly holes: Readonly<Record<string, number>>;
  readonly margin: number;
  readonly mdl: number;
  readonly violated_clip_ids: readonly string[];
  readonly sketch: Rule;
}
