// SPEC 6.4: the category of one engine entry against the solver's answer for the same sketch and examples.
//
//   identical        same status, holes, margin and violated set, computed without reading the engine's answer
//   tie_verified     same status, violated weight and margin; the engine's satisfied set is one of the solver's
//                    optimal alternatives (enumerated independently) and the solver's placement for that set
//                    reproduces the engine's holes exactly
//   engine_supplied  beyond the in-browser budget, an operational status (timeout / grid fallback / error), or a
//                    placement that depends on the engine's Z3 model point
//   mismatch         anything else (a release blocker)
//
// This file is the comparator side: it reads the engine's answer, so the solver (everything outside
// lib/synth/compare) must never import it (SPEC 6.5; lib/synth/architecture.test.ts).

import type { Rule } from "../../dsl/index.ts";
import { solveForSatisfiedSet } from "../exhaustive.ts";
import type { ExampleContext } from "../exhaustive.ts";
import type { SolveResult } from "../types.ts";

export type Category = "identical" | "tie_verified" | "engine_supplied" | "mismatch";

/** What the engine (or a recorded run) says about one sketch on one example set. */
export interface EngineEntry {
  status: "sat" | "unsat" | "rejected" | "timeout" | "grid_fallback" | "error";
  /** Hole values by name (sat only). */
  holes: Readonly<Record<string, number>> | null;
  margin: number | null;
  /** Clip ids the engine's answer gets wrong. */
  violated: readonly string[] | null;
  /** The engine's placement note ("slack-centre", "slack-stepback-grid(0.5)", ...); null when unknown / no holes. */
  placement: string | null;
}

export interface Verdict {
  category: Category;
  reason: string;
}

const sameHoles = (a: Readonly<Record<string, number>>, b: Readonly<Record<string, number>>): boolean => {
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  return ka.length === kb.length && ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && a[k] === b[k]);
};
const sameSet = (a: readonly string[], b: readonly string[]): boolean => {
  const sb = new Set(b);
  return a.length === b.length && a.every((x) => sb.has(x));
};
const isCentre = (p: string | null): boolean => p === null || p === "slack-centre" || p === "no holes";

export function categorize(sketch: Rule, ctx: ExampleContext, ts: SolveResult, engine: EngineEntry): Verdict {
  if (engine.status === "timeout" || engine.status === "grid_fallback" || engine.status === "error") {
    return { category: "engine_supplied", reason: `engine status ${engine.status}` };
  }
  if (engine.status === "rejected") return { category: "mismatch", reason: "rejected entries are compared on error class elsewhere" };
  if (ts.status === "budget_exceeded") return { category: "engine_supplied", reason: ts.note };
  if (ts.status !== engine.status) return { category: "mismatch", reason: `status ${ts.status} vs engine ${engine.status}` };
  const engViolated = engine.violated ?? [];
  const engSatisfied = ctx.examples.map((e) => e.clip_id).filter((c) => !engViolated.includes(c));
  if (ts.status === "unsat") {
    if (sameSet(ts.violated, engViolated)) return { category: "identical", reason: "" };
    if (ts.optimalSets.some((s) => sameSet(s, engSatisfied))) return { category: "tie_verified", reason: "unsat witness is another optimal set" };
    return { category: "mismatch", reason: `unsat witness ${JSON.stringify(engViolated)} is not an optimal set` };
  }
  // sat
  if (ts.margin !== engine.margin) return { category: "mismatch", reason: `margin ${ts.margin} vs ${engine.margin}` };
  const tsSameSet = sameSet(ts.violated, engViolated);
  if (tsSameSet && sameHoles(ts.holes, engine.holes ?? {})) return { category: "identical", reason: "" };
  if (!ts.optimalSets.some((s) => sameSet(s, engSatisfied))) {
    return { category: "mismatch", reason: `engine satisfied set ${JSON.stringify(engSatisfied)} is not optimal for the solver` };
  }
  if (!isCentre(engine.placement)) return { category: "engine_supplied", reason: `engine placement ${engine.placement} depends on its model point` };
  if (tsSameSet) return { category: "mismatch", reason: `holes ${JSON.stringify(ts.holes)} vs ${JSON.stringify(engine.holes)}` };
  // another of the tied alternatives: ask the solver to place that set
  const alt = solveForSatisfiedSet(sketch, ctx, engSatisfied);
  if (alt !== null && alt.status === "sat" && sameHoles(alt.holes, engine.holes ?? {}) && sameSet(alt.violated, engViolated)) {
    return { category: "tie_verified", reason: `one of ${ts.alternatives} tied alternatives` };
  }
  return { category: "mismatch", reason: `tied alternative placed at ${JSON.stringify(alt?.holes)} vs engine ${JSON.stringify(engine.holes)}` };
}
