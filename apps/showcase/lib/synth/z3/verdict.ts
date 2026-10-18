// What "Z3 agrees" means (SPEC 6.4 applied to the Z3 path): Z3's answer for a sketch against the result the Lab shows for
// it - the in-browser exhaustive solve, or the engine's answer where the exhaustive solver is over its budget.
//
//   agree           same status, margin, violated clips and hole values: "Z3 agrees"
//   agree_outcome   same status, margin and violated clips, but the holes differ because the placement of at least one of
//                   the two stepped back from the slack centre; that point depends on the solver's model, and both are
//                   verified against the evaluator. Shown with the exact hole values, never as a bare "agrees"
//   equal_optimum   same status and margin, a different violated set that is another optimal choice: either one of the
//                   exhaustive solver's enumerated optimal sets (`optimalSets`), or the same violated weight (both solvers
//                   are exact, so equal weight and margin mean a tie between optimal sets)
//   differs         anything else; `differences` lists exactly what is different
//   not_comparable  the shown result has no status Z3 can be compared with
//
// Pure. It reads only what the caller passes in (no grid, no recorded file), so it can run on the main thread after a
// Z3 run finishes for the current request.

import type { Z3SolveResult } from "./solve.ts";

/** The result the page shows for a sketch. */
export interface Reference {
  /** Where it came from: computed in this browser, or supplied by the engine. */
  readonly source: "browser" | "engine";
  readonly status: string;
  readonly holes: Readonly<Record<string, number>> | null;
  readonly margin: number | null;
  readonly violated: readonly string[] | null;
  /** Total example weight of the violated clips (lets a tied optimum be recognised when `optimalSets` is unknown). */
  readonly violatedWeight?: number | null;
  /** The placement note ("slack-centre", "slack-stepback(0.75)", ...); null or "" when unknown. */
  readonly placement?: string | null;
  /** Every optimal satisfied set (clip ids), when known: the exhaustive solver enumerates them. */
  readonly optimalSets?: readonly (readonly string[])[];
}

export type VerdictKind = "agree" | "agree_outcome" | "equal_optimum" | "differs" | "not_comparable";

export interface Verdict {
  readonly kind: VerdictKind;
  /** One line for people ("Z3 agrees", "Z3 differs: ..."). */
  readonly summary: string;
  /** The exact differences, one per line (empty for `agree`). */
  readonly differences: readonly string[];
}

const sameSet = (a: readonly string[], b: readonly string[]): boolean => {
  const sb = new Set(b);
  return a.length === b.length && a.every((x) => sb.has(x));
};

const isStepback = (p: string | null | undefined): boolean => p != null && p !== "" && p !== "slack-centre" && p !== "no holes";

const list = (ids: readonly string[]): string => (ids.length === 0 ? "none" : ids.join(", "));

/** Hole differences, one line per hole that is not identical (names from both sides). */
export function holeDifferences(z: Readonly<Record<string, number>>, ref: Readonly<Record<string, number>> | null): string[] {
  const out: string[] = [];
  const r = ref ?? {};
  for (const h of new Set([...Object.keys(z), ...Object.keys(r)])) {
    const a = Object.hasOwn(z, h) ? z[h] : undefined;
    const b = Object.hasOwn(r, h) ? r[h] : undefined;
    if (a === undefined || b === undefined || a !== b) out.push(`?${h}: Z3 ${a ?? "missing"}, shown ${b ?? "missing"}`);
  }
  return out;
}

/** Compare a finished Z3 solve with the result shown for the same sketch and examples. */
export function compareWithReference(z: Z3SolveResult, ref: Reference): Verdict {
  if (z.status === "timeout") {
    return { kind: "not_comparable", summary: "Z3 did not finish within its time budget", differences: [] };
  }
  if (ref.status !== "sat" && ref.status !== "unsat") {
    return { kind: "not_comparable", summary: `no Z3-comparable result to check against (shown status: ${ref.status})`, differences: [] };
  }
  const differs = (differences: string[]): Verdict => ({ kind: "differs", summary: `Z3 differs: ${differences.join("; ")}`, differences });
  if (z.status !== ref.status) return differs([`status: Z3 ${z.status}, shown ${ref.status}`]);

  const refViolated = ref.violated ?? [];
  const sameViolated = sameSet(z.violated, refViolated);
  const marginDiff = z.status === "sat" && z.margin !== ref.margin ? [`margin: Z3 ${z.margin}, shown ${ref.margin}`] : [];
  const holeDiff = z.status === "sat" ? holeDifferences(z.holes, ref.holes) : [];

  if (sameViolated && marginDiff.length === 0 && holeDiff.length === 0) return { kind: "agree", summary: "Z3 agrees", differences: [] };

  if (marginDiff.length > 0) {
    const d = [...marginDiff];
    if (!sameViolated) d.push(`violated: Z3 ${list(z.violated)}, shown ${list(refViolated)}`);
    return differs(d);
  }
  if (sameViolated) {
    // only the holes differ
    if (z.placementDegraded) {
      return {
        kind: "agree_outcome",
        summary: "Z3 agrees on the outcome; the hole values differ because Z3's placement was cut short by a time limit",
        differences: holeDiff,
      };
    }
    if (isStepback(ref.placement) || isStepback(z.placement)) {
      return {
        kind: "agree_outcome",
        summary: "Z3 agrees on the outcome; the hole values differ because the placement depends on the solver's model point",
        differences: holeDiff,
      };
    }
    if (z.referenceVerified === true) {
      return {
        kind: "agree_outcome",
        summary: "Z3 agrees on the outcome; the hole values differ, and the evaluator confirms both placements are equally good",
        differences: holeDiff,
      };
    }
    return differs(holeDiff);
  }
  // a different violated set
  const sets = ref.optimalSets;
  const violatedLine = `violated: Z3 ${list(z.violated)}, shown ${list(refViolated)}`;
  if (sets !== undefined && sets.some((s) => sameSet(s, z.satisfied))) {
    return { kind: "equal_optimum", summary: `Z3 chose another of the ${sets.length} equally optimal rules`, differences: [violatedLine, ...holeDiff] };
  }
  if (ref.violatedWeight != null && z.violatedWeight === ref.violatedWeight) {
    return { kind: "equal_optimum", summary: "Z3 chose another rule with the same violated weight and margin (tied optimum)", differences: [violatedLine, ...holeDiff] };
  }
  return differs([`violated: Z3 ${list(z.violated)}, shown ${list(refViolated)}`, ...holeDiff]);
}
