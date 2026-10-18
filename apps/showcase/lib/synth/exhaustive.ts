// The exhaustive hole solver: the TypeScript counterpart of engine/exemplar/synth/solve.py (`solve_sketch`, `hole_box`).
//
// Where the engine asks Z3 (MaxSMT, then the margin levels, then min/max of every hole), this solver enumerates every
// hole equivalence class (classes.ts), scores each with the evaluator semantics (scorer.ts) and reads the same three
// answers off the table:
//
//   1. w*  = the least violated example weight at the lowest margin level (= sign-correctness);
//   2. m*  = the highest margin level whose least violated weight is still w* (levels 0.1, 0.3, 0.45, 0.5);
//   3. the optimal satisfied sets: the distinct sets of examples that hold at margin m* among the points with weight
//      w*. If there is exactly one, the engine's answer is that set; if there are several, the engine's choice
//      depends on Z3's model and is verified separately (tie-verified, SPEC 6.4).
//
// Then the engine's temporal-slack placement (solve.py `_place`): the box of every hole over the feasible points of
// the chosen set, lower window bounds to 0 when feasible, every other hole to the centre of its interval, snapped to
// the 0.5 s grid (hours: integers), verified with the evaluator, stepped back towards a model point when it fails.
// The engine's model point is Z3's; here it is the first feasible class representative, so the step-back placements
// can differ from the engine's (the comparator treats those as engine-supplied).
//
// Everything is pure; a request can be cancelled at the check-points (every 1,000 points and between sketches).

import { holesOf, isHole } from "../dsl/ast.ts";
import { compileRule, prepare } from "../dsl/evaluator.ts";
import type { PreparedTrace, Rule } from "../dsl/index.ts";
import { fillHoles } from "../dsl/util.ts";
import { typecheck } from "../dsl/typecheck.ts";
import { pyRound } from "../dsl/pycompat.ts";
import { pyRound3 } from "./conformal.ts";
import { exampleGeometry, holeClasses, holeKinds, lowerBoundHoles, windowsWithHoles } from "./classes.ts";
import type { ExampleGeometry, HoleClasses } from "./classes.ts";
import { PointScorer } from "./scorer.ts";
import { Cancelled, SketchError } from "./types.ts";
import type { Example, SolveResult } from "./types.ts";

/** margin_levels() of z3enc.py for the default ontology: abs(s - 0.5) of the confidence values, and C. */
export const MARGIN_LEVELS: readonly number[] = [0.1, 0.3, 0.45, 0.5];
export const EPS = 1e-9; // tolerance of the satisfaction test
const EPS_FINAL = 1e-6; // tolerance of the mandatory check on the returned rule (solve.py EPS)
const GRID_STEP = 0.5; // temporal-slack grid (seconds)

/** Budget: raw hole-class product above this is `budget_exceeded` (SPEC 7.4). */
export const MAX_CLASSES = 50_000;

export interface SolveOptions {
  maxClasses?: number;
  /** Polled every 1,000 points and between sketches; return true to abandon the solve (throws `Cancelled`). */
  isCancelled?: () => boolean;
}

/** The per-example-set precomputation every sketch of a request shares. */
export interface ExampleContext {
  readonly examples: readonly Example[];
  readonly preps: readonly PreparedTrace[];
  readonly geo: ExampleGeometry;
}

export function makeExampleContext(examples: readonly Example[]): ExampleContext {
  const preps = examples.map((e) => prepare(e.trace));
  return { examples, preps, geo: exampleGeometry(preps) };
}

function asContext(x: readonly Example[] | ExampleContext): ExampleContext {
  return "preps" in x ? x : makeExampleContext(x);
}

const holds = (positive: boolean, score: number, m: number, eps: number): boolean =>
  positive ? score >= m - eps : score <= -m + eps;
const labelOk = (positive: boolean, score: number): boolean => score > 0 === positive;

/** Everything the table of hole points gives: scores per point and example, the class indices of each point. */
export interface Analysis {
  readonly names: readonly string[];
  readonly classes: HoleClasses;
  readonly nPts: number;
  readonly nEx: number;
  /** Class index per point and hole: [p * nHoles + h]. */
  readonly idx: Int32Array;
  /** Representative hole values: [p * nHoles + h]. */
  readonly vals: Float64Array;
  /** Score per point and example: [p * nEx + k]. */
  readonly scores: Float64Array;
}

export function analyze(sketch: Rule, ctx: ExampleContext, opts: SolveOptions = {}): Analysis | "budget" {
  const errs = typecheck(sketch);
  if (errs.length > 0) throw new SketchError("sketch does not typecheck: " + errs.join("; "));
  const names = holesOf(sketch);
  const classes = holeClasses(sketch, names, ctx.geo);
  const maxClasses = opts.maxClasses ?? MAX_CLASSES;
  if (!classes.supported || classes.product > maxClasses) return "budget";
  const nH = names.length;
  const nEx = ctx.examples.length;
  const counts = classes.reps.map((r) => r.length);
  const scorer = new PointScorer(sketch, ctx.preps, names, counts);
  const wins = windowsWithHoles(sketch);
  const holeIdx = new Map(names.map((n, i) => [n, i] as const));
  const winSpec = wins.map(([a, b]) => ({
    ah: isHole(a) ? (holeIdx.get(a.name) as number) : -1, ac: isHole(a) ? 0 : (a as number),
    bh: isHole(b) ? (holeIdx.get(b.name) as number) : -1, bc: isHole(b) ? 0 : (b as number),
  }));

  const cap = Math.min(classes.product, 1 << 20);
  let idxBuf = new Int32Array(Math.max(1, cap) * Math.max(1, nH));
  let valBuf = new Float64Array(Math.max(1, cap) * Math.max(1, nH));
  let scBuf = new Float64Array(Math.max(1, cap) * Math.max(1, nEx));
  const cur = new Int32Array(nH);
  const curV = new Float64Array(nH);
  for (let h = 0; h < nH; h++) curV[h] = (classes.reps[h] as Float64Array)[0] as number;
  let nPts = 0;
  let visited = 0;
  // odometer over the per-hole class lists, rightmost fastest (itertools.product order)
  for (;;) {
    visited += 1;
    if (visited % 1000 === 0 && opts.isCancelled?.()) throw new Cancelled();
    let ok = true;
    for (const w of winSpec) {
      const lo = w.ah >= 0 ? (curV[w.ah] as number) : w.ac;
      const hi = w.bh >= 0 ? (curV[w.bh] as number) : w.bc;
      if (lo > hi) {
        ok = false;
        break;
      }
    }
    if (ok) {
      if ((nPts + 1) * Math.max(1, nH) > idxBuf.length) {
        const grow = (a: Int32Array | Float64Array, n: number): any => {
          const b = new (a.constructor as any)(n);
          b.set(a);
          return b;
        };
        idxBuf = grow(idxBuf, idxBuf.length * 2);
        valBuf = grow(valBuf, valBuf.length * 2);
        scBuf = grow(scBuf, (scBuf.length / Math.max(1, nEx)) * 2 * Math.max(1, nEx));
      }
      scorer.setPoint(cur, curV);
      for (let h = 0; h < nH; h++) {
        idxBuf[nPts * nH + h] = cur[h] as number;
        valBuf[nPts * nH + h] = curV[h] as number;
      }
      for (let k = 0; k < nEx; k++) scBuf[nPts * nEx + k] = scorer.score(k);
      nPts += 1;
    }
    // advance
    let h = nH - 1;
    for (; h >= 0; h--) {
      const n = (classes.reps[h] as Float64Array).length;
      if ((cur[h] as number) + 1 < n) {
        cur[h] = (cur[h] as number) + 1;
        curV[h] = (classes.reps[h] as Float64Array)[cur[h] as number] as number;
        break;
      }
      cur[h] = 0;
      curV[h] = (classes.reps[h] as Float64Array)[0] as number;
    }
    if (h < 0) break;
  }
  return { names, classes, nPts, nEx, idx: idxBuf, vals: valBuf, scores: scBuf };
}

interface Outcome {
  readonly kind: "sat" | "unsat" | "empty";
  readonly wStar: number;
  readonly mIdx: number;
  /** Distinct optimal satisfied sets as bitmasks over the examples (bit k = example k), first-seen order. */
  readonly sets: number[];
  /** For each set the first point (in enumeration order) that realises it. */
  readonly firstPoint: number[];
}

function outcomeOf(a: Analysis, ex: readonly Example[]): Outcome {
  const { nPts, nEx, scores } = a;
  if (nPts === 0) return { kind: "empty", wStar: Infinity, mIdx: 0, sets: [], firstPoint: [] };
  const weightAt = (p: number, m: number): number => {
    let w = 0;
    for (let k = 0; k < nEx; k++) {
      if (!holds((ex[k] as Example).positive, scores[p * nEx + k] as number, m, EPS)) w += (ex[k] as Example).weight;
    }
    return w;
  };
  const minAt = (m: number): number => {
    let best = Infinity;
    for (let p = 0; p < nPts; p++) {
      const w = weightAt(p, m);
      if (w < best) best = w;
    }
    return best;
  };
  const wStar = minAt(MARGIN_LEVELS[0] as number);
  let mIdx = 0;
  for (let i = 1; i < MARGIN_LEVELS.length; i++) {
    if (minAt(MARGIN_LEVELS[i] as number) <= wStar + EPS) mIdx = i;
    else break;
  }
  const hasPos = ex.some((e) => e.positive);
  const neverFires = ex.reduce((s, e) => (hasPos ? (e.positive ? s + e.weight : s) : s + e.weight), 0);
  const unsat = wStar >= neverFires - EPS;
  const level = unsat ? 0 : mIdx; // the engine returns the stage-1 witness (lowest level) for unsat
  const m = MARGIN_LEVELS[level] as number;
  const sets: number[] = [];
  const firstPoint: number[] = [];
  const seen = new Set<number>();
  for (let p = 0; p < nPts; p++) {
    if (weightAt(p, m) <= wStar + EPS) {
      let mask = 0;
      for (let k = 0; k < nEx; k++) if (holds((ex[k] as Example).positive, scores[p * nEx + k] as number, m, EPS)) mask |= 1 << k;
      if (!seen.has(mask)) {
        seen.add(mask);
        sets.push(mask);
        firstPoint.push(p);
      }
    }
  }
  return { kind: unsat ? "unsat" : "sat", wStar, mIdx: level, sets, firstPoint };
}

const maskIds = (mask: number, ex: readonly Example[], want: boolean): string[] =>
  ex.filter((_, k) => ((mask >> k) & 1) === (want ? 1 : 0)).map((e) => e.clip_id);

/** [lo, hi] of every hole over the feasible points (closure of the feasible region). */
function boxOver(a: Analysis, feasible: (p: number) => boolean): Map<string, [number, number]> | null {
  const nH = a.names.length;
  const lo = new Array<number>(nH).fill(Infinity);
  const hi = new Array<number>(nH).fill(-Infinity);
  let any = false;
  for (let p = 0; p < a.nPts; p++) {
    if (!feasible(p)) continue;
    any = true;
    for (let h = 0; h < nH; h++) {
      const c = a.idx[p * nH + h] as number;
      const l = (a.classes.lo[h] as Float64Array)[c] as number;
      const u = (a.classes.hi[h] as Float64Array)[c] as number;
      if (l < (lo[h] as number)) lo[h] = l;
      if (u > (hi[h] as number)) hi[h] = u;
    }
  }
  if (!any) return null;
  const out = new Map<string, [number, number]>();
  a.names.forEach((n, h) => out.set(n, [lo[h] as number, hi[h] as number]));
  return out;
}

function snap(kind: "time" | "hour", x: number, lo: number, hi: number): number {
  if (kind === "hour") {
    const v = Math.min(Math.max(pyRound(x), Math.ceil(lo - 1e-9)), Math.floor(hi + 1e-9));
    return v + 0;
  }
  const first = Math.ceil(lo / GRID_STEP - 1e-12);
  const last = Math.floor(hi / GRID_STEP + 1e-12);
  let best: number | null = null;
  for (let k = first; k <= last; k++) {
    const g = k * GRID_STEP;
    if (best === null) best = g;
    else {
      const dg = Math.abs(g - x);
      const db = Math.abs(best - x);
      if (dg < db || (dg === db && g < best)) best = g;
    }
  }
  if (best !== null) return best + 0;
  return pyRound3(Math.min(Math.max(x, lo), hi)) + 0;
}

/** Temporal-slack placement for the satisfied set `mask` at margin level `mIdx` (solve.py `_place`). */
function place(
  sketch: Rule, a: Analysis, ctx: ExampleContext, mask: number, mIdx: number, p0Point: number,
): { holes: Record<string, number>; how: string } {
  const names = a.names;
  const nH = names.length;
  if (nH === 0) return { holes: {}, how: "no holes" };
  const ex = ctx.examples;
  const m = MARGIN_LEVELS[mIdx] as number;
  const kinds = holeKinds(sketch);
  const lowerH = lowerBoundHoles(sketch);
  const satIdx: number[] = [];
  for (let k = 0; k < ex.length; k++) if ((mask >> k) & 1) satIdx.push(k);
  const feasible = (p: number): boolean => {
    for (const k of satIdx) if (!holds((ex[k] as Example).positive, a.scores[p * a.nEx + k] as number, m, EPS)) return false;
    return true;
  };
  const box = boxOver(a, feasible) ?? new Map(names.map((n, h) => [n, [a.vals[p0Point * nH + h] as number, a.vals[p0Point * nH + h] as number] as [number, number]]));
  const p0: Record<string, number> = {};
  names.forEach((n, h) => (p0[n] = a.vals[p0Point * nH + h] as number));
  const target: Record<string, number> = {};
  for (const n of names) {
    const [lo, hi] = box.get(n) as [number, number];
    target[n] = lowerH.has(n) && lo <= 0.0 && 0.0 <= hi ? 0.0 : (lo + hi) / 2;
  }
  const cr = compileRule(sketch);
  const verify = (pt: Record<string, number>): boolean => {
    for (const k of satIdx) {
      const e = ex[k] as Example;
      const s = cr.score(ctx.preps[k] as PreparedTrace, pt);
      if (!(holds(e.positive, s, m, EPS) && labelOk(e.positive, s))) return false;
    }
    return true;
  };
  const snapped = (pt: Record<string, number>): Record<string, number> => {
    const o: Record<string, number> = {};
    for (const n of names) {
      const [lo, hi] = box.get(n) as [number, number];
      o[n] = snap(kinds.get(n) as "time" | "hour", pt[n] as number, lo, hi);
    }
    return o;
  };
  const rounded = (pt: Record<string, number>): Record<string, number> => {
    const o: Record<string, number> = {};
    for (const n of names) o[n] = (kinds.get(n) === "hour" ? pyRound(pt[n] as number) : pyRound3(pt[n] as number)) + 0;
    return o;
  };
  const cand = snapped(target);
  if (verify(cand)) return { holes: cand, how: "slack-centre" };
  for (const s of [0.75, 0.5, 0.25, 0.125]) {
    const pt: Record<string, number> = {};
    for (const n of names) pt[n] = (p0[n] as number) + s * ((target[n] as number) - (p0[n] as number));
    const variants: [Record<string, number>, string][] = [[snapped(pt), "slack-stepback-grid"], [rounded(pt), "slack-stepback"]];
    for (const [v, name] of variants) if (verify(v)) return { holes: v, how: `${name}(${s})` };
  }
  const tail: [Record<string, number>, string][] = [[snapped(p0), "model-grid"], [rounded(p0), "model-rounded"]];
  for (const [v, name] of tail) if (verify(v)) return { holes: v, how: name };
  return { holes: { ...p0 }, how: "model" };
}

function finish(
  sketch: Rule, a: Analysis, ctx: ExampleContext, oc: Outcome, setIdx: number, t0: number,
): SolveResult {
  const ex = ctx.examples;
  const cls = { classes: a.nPts, classProduct: a.classes.product };
  const ms = (): number => Math.max(0, Math.round(performance.now() - t0));
  const optimal = oc.sets.map((mk) => maskIds(mk, ex, true));
  if (oc.kind === "empty") {
    return {
      status: "unsat", sketch, rule: null, holes: {}, margin: 0, violated: ex.filter((e) => e.positive).map((e) => e.clip_id),
      satisfied: [], ...cls, alternatives: 0, optimalSets: [], placement: "", solveMs: ms(),
      note: "no hole assignment is admissible for this sketch on these clips",
    };
  }
  const mask = oc.sets[setIdx] as number;
  if (oc.kind === "unsat") {
    return {
      status: "unsat", sketch, rule: null, holes: {}, margin: 0, violated: maskIds(mask, ex, false), satisfied: maskIds(mask, ex, true),
      ...cls, alternatives: oc.sets.length, optimalSets: optimal, placement: "", solveMs: ms(),
      note: "the best assignment is no better than a rule that never fires",
    };
  }
  const m = MARGIN_LEVELS[oc.mIdx] as number;
  const { holes, how } = place(sketch, a, ctx, mask, oc.mIdx, oc.firstPoint[setIdx] as number);
  // the mandatory check on the returned rule
  const cr = compileRule(sketch);
  const scores = ctx.preps.map((p) => cr.score(p, holes));
  for (let k = 0; k < ex.length; k++) {
    if (!((mask >> k) & 1)) continue;
    const e = ex[k] as Example;
    const s = scores[k] as number;
    if (!labelOk(e.positive, s) || !holds(e.positive, s, m, EPS_FINAL)) {
      throw new Error(`placed rule fails on clip ${e.clip_id}: evaluator score ${s}, expected ${e.positive ? ">=" : "<="} ${e.positive ? m : -m}`);
    }
  }
  const ok = ex.map((e, k) => labelOk(e.positive, scores[k] as number));
  return {
    status: "sat", sketch, rule: fillHoles(sketch, holes), holes, margin: m,
    violated: ex.filter((_, k) => !ok[k]).map((e) => e.clip_id), satisfied: ex.filter((_, k) => ok[k]).map((e) => e.clip_id),
    ...cls, alternatives: oc.sets.length, optimalSets: optimal, placement: how, solveMs: ms(),
    note: `placement: ${how}`,
  };
}

function budgetResult(sketch: Rule, ctx: ExampleContext, product: number, t0: number, why: string): SolveResult {
  return {
    status: "budget_exceeded", sketch, rule: null, holes: {}, margin: 0, violated: [], satisfied: [],
    classes: 0, classProduct: product, alternatives: 0, optimalSets: [], placement: "",
    solveMs: Math.round(performance.now() - t0), note: why,
  };
}

/**
 * Fill the holes of `sketch` so that it matches the positive examples and none of the negative ones: minimise the
 * violated example weight, then maximise the margin, then place the holes with temporal slack. Throws `SketchError`
 * for an ill-typed sketch and `Cancelled` when `opts.isCancelled()` turns true at a check-point.
 */
export function solveSketchExhaustive(sketch: Rule, examples: readonly Example[] | ExampleContext, opts: SolveOptions = {}): SolveResult {
  const t0 = performance.now();
  const ctx = asContext(examples);
  const a = analyze(sketch, ctx, opts);
  if (a === "budget") {
    const names = holesOf(sketch);
    const cl = holeClasses(sketch, names, ctx.geo);
    return budgetResult(sketch, ctx, cl.product, t0, cl.supported
      ? `${cl.product} hole classes exceed the in-browser budget of ${opts.maxClasses ?? MAX_CLASSES}`
      : "a window bound is not a whole number of milliseconds");
  }
  const oc = outcomeOf(a, ctx.examples);
  return finish(sketch, a, ctx, oc, 0, t0);
}

/**
 * The result the solver would return if it chose the optimal satisfied set `satisfied` (clip ids), for the tie check
 * (SPEC 6.4): null when that set is not one of the optimal sets of this sketch on these examples.
 */
export function solveForSatisfiedSet(
  sketch: Rule, examples: readonly Example[] | ExampleContext, satisfied: readonly string[], opts: SolveOptions = {},
): SolveResult | null {
  const t0 = performance.now();
  const ctx = asContext(examples);
  const a = analyze(sketch, ctx, opts);
  if (a === "budget") return null;
  const oc = outcomeOf(a, ctx.examples);
  if (oc.kind === "empty") return null;
  const want = new Set(satisfied);
  const idx = oc.sets.findIndex((mk) => {
    const ids = maskIds(mk, ctx.examples, true);
    return ids.length === want.size && ids.every((i) => want.has(i));
  });
  if (idx < 0) return null;
  return finish(sketch, a, ctx, oc, idx, t0);
}

export class InfeasibleBox extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InfeasibleBox";
  }
}

/**
 * Feasible interval (lo, hi) of every hole when the `satisfied` examples (clip ids) must hold at `margin` and every
 * other example is unconstrained (solve.py `hole_box`). Throws `InfeasibleBox` when no hole assignment achieves it.
 */
export function holeBox(
  sketch: Rule, examples: readonly Example[] | ExampleContext, opts: { satisfied: readonly string[]; margin: number } & SolveOptions,
): Record<string, [number, number]> {
  const ctx = asContext(examples);
  const a = analyze(sketch, ctx, opts);
  if (a === "budget") throw new InfeasibleBox("hole space exceeds the in-browser budget");
  const m = Math.min(Math.max(opts.margin, 0), MARGIN_LEVELS[MARGIN_LEVELS.length - 1] as number);
  const sat = new Set(opts.satisfied);
  const idx: number[] = [];
  ctx.examples.forEach((e, k) => {
    if (sat.has(e.clip_id)) idx.push(k);
  });
  const box = boxOver(a, (p) => idx.every((k) => holds((ctx.examples[k] as Example).positive, a.scores[p * a.nEx + k] as number, m, EPS)));
  if (box === null) throw new InfeasibleBox("no hole assignment satisfies the given examples at the given margin");
  const out: Record<string, [number, number]> = {};
  const kinds = holeKinds(sketch);
  for (const [n, [lo, hi]] of box) out[n] = kinds.get(n) === "hour" ? [Math.trunc(lo), Math.trunc(hi)] : [lo, hi];
  return out;
}

