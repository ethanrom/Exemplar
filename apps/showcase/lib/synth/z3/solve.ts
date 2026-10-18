// Hole solving on Z3: MaxSMT, then the margin levels, then min / max of every hole, then the engine's temporal-slack
// placement and the mandatory differential check. The TypeScript port of the Z3 path of engine/exemplar/synth/solve.py
// (`solve_sketch`, `hole_box`) on the z3-solver high-level API.
//
// Pipeline for one sketch (docs/DSL.md "Hole placement"):
//   1. z3.Optimize minimises the violated example weight at the lowest margin level;
//   2. the margin levels above are tried in ascending order, each with its own MaxSMT; the highest level that still
//      achieves the minimal weight wins;
//   3. the Z3 model point is differentially checked against the evaluator (lib/dsl), two-sided, per example;
//   4. temporal slack: with the satisfied set and margin fixed, each hole's feasible interval comes from Z3 min / max;
//      lower window bounds go to 0 when feasible, every other hole to its interval centre; values snap to the 0.5 s grid
//      (hours: integers) and are re-verified with the evaluator; a failing point is pulled back along the segment
//      towards the Z3 model point;
//   5. the returned rule is evaluated once more and any disagreement raises `EncoderMismatch`.
//
// Not ported: the engine's grid fallback after a Z3 timeout. A timeout is reported as `timeout`, never as `unsat`.
//
// The Z3 context comes from the caller through `Z3Api` (one shared context per worker, see there).

import type { Bool, Model } from "z3-solver";
import { fillHoles } from "../../dsl/util.ts";
import { compileRule } from "../../dsl/evaluator.ts";
import type { CompiledRule } from "../../dsl/evaluator.ts";
import type { Rule } from "../../dsl/index.ts";
import { pyRound } from "../../dsl/pycompat.ts";
import { pyRound3 } from "../conformal.ts";
import { Cancelled } from "../types.ts";
import type { Example } from "../types.ts";
import { Encoder, marginLevelsMicro } from "./encoder.ts";
import type { Z3Ctx } from "./encoder.ts";
import { parseSexpr } from "./rational.ts";

/**
 * What the solver needs from Z3: the context to build formulas in. Use ONE long-lived context per worker: the engine makes
 * a fresh context per encoder, but z3-solver frees a context only when the JavaScript garbage collector finalises it, and
 * the collector never sees the 2 GB WebAssembly heap fill up (about 25 MB leaked per solve; the heap is exhausted after
 * about 80 solves). A shared context stays flat (about 600 MB over 400 solves).
 */
export interface Z3Api {
  context(): Z3Ctx;
}

export const EPS = 1e-6; // tolerance of the mandatory differential check (spec)
const GRID_STEP = 0.5; // temporal-slack grid (seconds)
// Placement (the hole box): the engine gives each min / max query 5 s / (2 holes) and falls back to the hole's whole domain
// when a query times out. Z3's limit is wall-clock time, so on a busy or slow machine that fallback changes the placed hole
// values. Here every query may use up to QUERY_CAP_MS within one overall budget, and a result whose box was cut short by a
// time limit says so (`placementDegraded`) instead of being reported as a difference.
const PLACEMENT_BUDGET_MS = 7000;
const QUERY_CAP_MS = 3000;
const MICRO = 1_000_000;

/** Z3 and the evaluator disagree: an encoder bug, never a user error. */
export class EncoderMismatch extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EncoderMismatch";
  }
}

/** `hole_box` was asked for a satisfied set / margin no hole assignment achieves. */
export class InfeasibleBox extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InfeasibleBox";
  }
}

export type Z3Status = "sat" | "unsat" | "timeout";

export interface Z3Timings {
  /** Time spent building Z3 formulas (JS side). */
  encodeMs: number;
  /** Time spent inside Z3 `check` calls. */
  z3Ms: number;
  /** Number of Z3 `check` calls. */
  checks: number;
}

/** The answer of the Z3 path for one sketch: the same fields the engine reports (status, holes, margin, violated set). */
export interface Z3SolveResult {
  readonly status: Z3Status;
  /** Hole values by name (empty unless sat). */
  readonly holes: Readonly<Record<string, number>>;
  /** The optimal margin level (0 unless sat). */
  readonly margin: number;
  /** Clip ids the returned assignment gets wrong (for unsat: the stage-1 witness's, as in the engine). */
  readonly violated: readonly string[];
  /** Total example weight of the violated clips. */
  readonly violatedWeight: number;
  readonly satisfied: readonly string[];
  /** How the holes were placed ("slack-centre", "slack-stepback-grid(0.5)", ... or "no holes"). */
  readonly placement: string;
  /** A Z3 query of the hole box hit its time limit, so the placed hole values may differ from an unhurried run's. */
  readonly placementDegraded: boolean;
  /**
   * Set when `referenceHoles` were given: the shown rule, scored by the evaluator, gets the same examples wrong and is at
   * least as good at the optimal margin as Z3's rule - so a difference in hole values is a tie between equally good
   * placements, not a disagreement. null when no reference holes were given or the status is not sat.
   */
  readonly referenceVerified: boolean | null;
  readonly note: string;
  readonly solveMs: number;
  readonly timings: Z3Timings;
}

export interface Z3SolveOptions {
  /** Wall-clock budget of the Z3 work (default 10 s); the placement step may add at most 5 s. */
  timeoutMs?: number;
  /** Polled between Z3 calls; true abandons the solve (throws `Cancelled`). */
  isCancelled?: () => boolean;
  /** The hole values the page shows for this sketch: checked with the evaluator against Z3's answer (`referenceVerified`). */
  referenceHoles?: Readonly<Record<string, number>>;
}

const now = (): number => performance.now();
const holds = (positive: boolean, score: number, m: number, eps: number): boolean => (positive ? score >= m - eps : score <= -m + eps);
const labelOk = (positive: boolean, score: number): boolean => score > 0 === positive;
const lvl = (micro: number): number => micro / MICRO;

/** `f"{w:.6g}"` for a positive example weight (the soft-constraint weight text the engine hands to Z3). */
export function weightText(w: number): string {
  return String(Number(w.toPrecision(6)));
}

class Meter {
  encodeMs = 0;
  z3Ms = 0;
  checks = 0;
  /** A hole-box query ended without an answer (time limit). */
  degraded = false;
  readonly isCancelled: (() => boolean) | undefined;
  constructor(isCancelled: (() => boolean) | undefined) {
    this.isCancelled = isCancelled;
  }
  check(): void {
    if (this.isCancelled?.()) throw new Cancelled();
  }
  snapshot(): Z3Timings {
    return { encodeMs: this.encodeMs, z3Ms: this.z3Ms, checks: this.checks };
  }
}

// ============================================================================ the exact optimum
async function maxsmt(enc: Encoder, timeoutMs: number, m: Meter): Promise<["sat" | "unsat" | "unknown", Model<"main"> | null]> {
  m.check();
  const opt = new enc.z.Optimize();
  opt.set("timeout", Math.max(1, Math.floor(timeoutMs)));
  opt.add(...enc.domain);
  const t0 = now();
  enc.examples.forEach((ex, k) => {
    const g = enc.goal(k);
    if (g === true || g === false) return; // constant outcome: contributes the same to every model
    opt.addSoft(g, weightText(ex.weight), "viol");
  });
  m.encodeMs += now() - t0;
  const t1 = now();
  const res = await opt.check();
  m.z3Ms += now() - t1;
  m.checks += 1;
  if (res === "sat") return ["sat", opt.model()];
  if (res === "unsat") return ["unsat", null];
  return ["unknown", null];
}

const violatedWeight = (enc: Encoder, model: Model<"main">): number =>
  enc.examples.reduce((s, ex, k) => s + (enc.isTrue(model, enc.goal(k)) ? 0 : ex.weight), 0);

function diffCheckPoint(
  enc: Encoder, cr: CompiledRule, holes: Record<string, number>, mStar: number, z3Ok: readonly boolean[],
): number[] {
  const scores = enc.preps.map((p) => cr.score(p, holes));
  enc.examples.forEach((ex, k) => {
    const npOk = holds(ex.positive, scores[k] as number, mStar, 1e-9);
    if (npOk !== z3Ok[k]) {
      throw new EncoderMismatch(
        `Z3 and the evaluator disagree on clip ${ex.clip_id} (${ex.positive ? "positive" : "negative"}) at holes ` +
        `${JSON.stringify(holes)}, margin ${mStar}: Z3 says ${z3Ok[k] ? "satisfied" : "violated"}, evaluator score is ${(scores[k] as number).toFixed(4)}`,
      );
    }
  });
  return scores;
}

/** Infimum / supremum of hole `h` over the models of `hard` (the closure: open bounds are reported at the edge). */
async function extremum(
  enc: Encoder, hard: readonly Bool<"main">[], h: string, dir: "min" | "max", timeoutMs: number, m: Meter,
): Promise<number | null> {
  m.check();
  const opt = new enc.z.Optimize();
  opt.set("timeout", Math.max(1, Math.floor(timeoutMs)));
  opt.add(...hard);
  const handle = dir === "min" ? opt.minimize(enc.hole(h)) : opt.maximize(enc.hole(h));
  const t1 = now();
  const r = await opt.check();
  m.z3Ms += now() - t1;
  m.checks += 1;
  if (r !== "sat") {
    m.degraded = true;
    return null;
  }
  return parseSexpr((dir === "min" ? opt.getLower(handle) : opt.getUpper(handle)).toString()).toNumber();
}

/** The feasible interval of every hole when the examples `idx` must hold at the encoder's margin (solve.py `_box`). */
export async function boxOf(enc: Encoder, idx: readonly number[], timeoutMs: number, m: Meter): Promise<Record<string, [number, number]>> {
  const hard: Bool<"main">[] = [...enc.domain];
  for (const k of idx) {
    const g = enc.goal(k);
    if (g === false) throw new InfeasibleBox(`example ${(enc.examples[k] as Example).clip_id} cannot satisfy the sketch at any hole value`);
    if (g !== true) hard.push(g);
  }
  const deadline = now() + timeoutMs;
  const query = (): number => Math.max(1, Math.min(QUERY_CAP_MS, deadline - now()));
  const probe = new enc.z.Solver();
  probe.set("timeout", Math.max(1, Math.floor(query())));
  probe.add(...hard);
  const t1 = now();
  const pr = await probe.check();
  m.z3Ms += now() - t1;
  m.checks += 1;
  if (pr === "unsat") throw new InfeasibleBox("no hole assignment satisfies the given examples at the given margin");
  if (pr !== "sat") m.degraded = true;
  const out: Record<string, [number, number]> = {};
  for (const h of enc.holeNames) {
    const hour = enc.kindOf(h) === "hour";
    const dom: [number, number] = hour ? [0, 23] : [0, enc.clipLenMs / 1000];
    const lo = await extremum(enc, hard, h, "min", query(), m);
    const hi = await extremum(enc, hard, h, "max", query(), m);
    const l = lo === null ? dom[0] : lo;
    const u = hi === null ? dom[1] : hi;
    out[h] = hour ? [Math.trunc(l), Math.trunc(u)] : [l, u];
  }
  return out;
}

/**
 * Feasible interval (lo, hi) of every hole: Z3 min / max with the `satisfied` examples (clip ids) required to hold at
 * `margin` and every other example unconstrained (solve.py `hole_box`). Throws `InfeasibleBox` if not achievable.
 */
export async function holeBoxZ3(
  api: Z3Api, sketch: Rule, examples: readonly Example[], opts: { satisfied: readonly string[]; margin: number; timeoutMs?: number },
): Promise<Record<string, [number, number]>> {
  const levels = marginLevelsMicro();
  const micro = Math.min(Math.max(Math.round(opts.margin * MICRO), 0), levels[levels.length - 1] as number);
  const enc = new Encoder(api.context(), sketch, examples, micro);
  const sat = new Set(opts.satisfied);
  const idx = examples.map((e, k) => (sat.has(e.clip_id) ? k : -1)).filter((k) => k >= 0);
  return boxOf(enc, idx, opts.timeoutMs ?? 10_000, new Meter(undefined));
}

// ============================================================================ temporal-slack placement
/** Grid points k * step inside [lo, hi]. */
function gridIn(lo: number, hi: number, step = GRID_STEP): number[] {
  const a = Math.ceil(lo / step - 1e-12);
  const b = Math.floor(hi / step + 1e-12);
  const out: number[] = [];
  for (let k = a; k <= b; k++) out.push(k * step);
  return out;
}

/** Nearest grid value (0.5 s; hours: integers) inside the hole's interval; the plain value if there is none. */
function snap(hour: boolean, x: number, lo: number, hi: number): number {
  if (hour) return Math.min(Math.max(pyRound(x), Math.ceil(lo - 1e-9)), Math.floor(hi + 1e-9)) + 0;
  const cands = gridIn(lo, hi);
  if (cands.length > 0) {
    let best = cands[0] as number;
    for (const g of cands) {
      const dg = Math.abs(g - x);
      const db = Math.abs(best - x);
      if (dg < db || (dg === db && g < best)) best = g;
    }
    return best + 0;
  }
  return pyRound3(Math.min(Math.max(x, lo), hi)) + 0;
}

async function place(
  enc: Encoder, cr: CompiledRule, p0: Record<string, number>, mStar: number, satIdx: readonly number[], timeoutMs: number, m: Meter,
): Promise<{ holes: Record<string, number>; how: string }> {
  if (enc.holeNames.length === 0) return { holes: {}, how: "no holes" };
  const satPreps = satIdx.map((k) => [enc.preps[k], (enc.examples[k] as Example).positive] as const);
  const verify = (pt: Record<string, number>): boolean =>
    satPreps.every(([p, pos]) => {
      const s = cr.score(p, pt);
      return holds(pos, s, mStar, 1e-9) && labelOk(pos, s);
    });
  let box: Record<string, [number, number]>;
  try {
    box = await boxOf(enc, satIdx, timeoutMs, m);
  } catch (e) {
    if (!(e instanceof InfeasibleBox)) throw e; // numerically odd; keep the Z3 point
    box = Object.fromEntries(Object.entries(p0).map(([h, v]) => [h, [v, v] as [number, number]]));
  }
  const target: Record<string, number> = {};
  for (const [h, [lo, hi]] of Object.entries(box)) target[h] = enc.lowerHoles.has(h) && lo <= 0.0 && 0.0 <= hi ? 0.0 : (lo + hi) / 2;
  const hour = (h: string): boolean => enc.kindOf(h) === "hour";
  const snapped = (pt: Record<string, number>): Record<string, number> =>
    Object.fromEntries(Object.entries(pt).map(([h, x]) => [h, snap(hour(h), x, (box[h] as [number, number])[0], (box[h] as [number, number])[1])]));
  const rounded = (pt: Record<string, number>): Record<string, number> =>
    Object.fromEntries(Object.entries(pt).map(([h, x]) => [h, (hour(h) ? pyRound(x) : pyRound3(x)) + 0]));
  const cand = snapped(target);
  if (verify(cand)) return { holes: cand, how: "slack-centre" };
  for (const s of [0.75, 0.5, 0.25, 0.125]) {
    // step back from the target towards the Z3 point
    const pt = Object.fromEntries(Object.keys(p0).map((h) => [h, (p0[h] as number) + s * ((target[h] as number) - (p0[h] as number))]));
    const variants: [Record<string, number>, string][] = [[snapped(pt), "slack-stepback-grid"], [rounded(pt), "slack-stepback"]];
    for (const [v, name] of variants) if (verify(v)) return { holes: v, how: `${name}(${s})` };
  }
  const tail: [Record<string, number>, string][] = [[snapped(p0), "model-grid"], [rounded(p0), "model-rounded"]];
  for (const [v, name] of tail) if (verify(v)) return { holes: v, how: name };
  return { holes: { ...p0 }, how: "model" };
}

/** Index of the largest margin level that is <= `lowerBound` (0 if none). */
function bestLevel(levels: readonly number[], lowerBound: number): number {
  let best = 0;
  levels.forEach((lv, i) => {
    if (lvl(lv) <= lowerBound + 1e-9) best = i;
  });
  return best;
}

/**
 * Is the rule with the shown hole values (`ref`) as good as Z3's? Scored by the evaluator it must get exactly the same
 * examples wrong, and fail the margin `mStar` on no more example weight than Z3's rule does.
 */
function referenceIsAsGood(
  enc: Encoder, cr: CompiledRule, ref: Readonly<Record<string, number>>, mStar: number, zScores: readonly number[], zViolated: readonly string[],
): boolean {
  if (!enc.holeNames.every((h) => Object.hasOwn(ref, h) && Number.isFinite(ref[h]))) return false;
  const rs = enc.preps.map((p) => cr.score(p, ref));
  const failing = (scores: readonly number[]): number =>
    enc.examples.reduce((w, e, k) => (holds(e.positive, scores[k] as number, mStar, 1e-9) ? w : w + e.weight), 0);
  const wrong = enc.examples.filter((e, k) => !labelOk(e.positive, rs[k] as number)).map((e) => e.clip_id);
  const same = wrong.length === zViolated.length && wrong.every((c) => zViolated.includes(c));
  return same && failing(rs) <= failing(zScores) + 1e-9;
}

// ============================================================================ public: solveSketchZ3
/**
 * Fill the holes of `sketch` so that it matches the positive examples and none of the negative ones: minimise the
 * violated example weight, then maximise the margin (the least |robustness| over the satisfied examples), then place
 * the holes with temporal slack. Throws `SketchError` for an ill-typed sketch, `EncoderMismatch` if the encoding and
 * the evaluator ever disagree, and `Cancelled` when `opts.isCancelled()` turns true between Z3 calls.
 */
export async function solveSketchZ3(api: Z3Api, sketch: Rule, examples: readonly Example[], opts: Z3SolveOptions = {}): Promise<Z3SolveResult> {
  const t0 = now();
  const timeoutMs = opts.timeoutMs ?? 10_000;
  const m = new Meter(opts.isCancelled);
  const levels = marginLevelsMicro();
  const ex = [...examples];
  const ids = (pred: (k: number) => boolean): string[] => ex.filter((_, k) => pred(k)).map((e) => e.clip_id);
  const ms = (): number => Math.round(now() - t0);
  const left = (): number => Math.max(500, timeoutMs - (now() - t0));
  const finish = (r: Omit<Z3SolveResult, "solveMs" | "timings" | "violatedWeight" | "placementDegraded" | "referenceVerified"> & { referenceVerified?: boolean | null }): Z3SolveResult => {
    const bad = new Set(r.violated);
    const violatedWeight = ex.reduce((w, e) => (bad.has(e.clip_id) ? w + e.weight : w), 0);
    return { referenceVerified: null, ...r, violatedWeight, placementDegraded: m.degraded, solveMs: ms(), timings: m.snapshot() };
  };
  const mk = (level: number): Encoder => {
    const t = now();
    const e = new Encoder(api.context(), sketch, ex, level);
    m.encodeMs += now() - t;
    return e;
  };

  let enc = mk(levels[0] as number);
  const cr = compileRule(sketch);
  const [status, model] = await maxsmt(enc, left(), m);

  if (status === "unsat") {
    // the hole domain itself is empty (e.g. eventually[10, ?b] on a 4 s clip)
    return finish({
      status: "unsat", holes: {}, margin: 0, violated: ids((k) => (ex[k] as Example).positive), satisfied: [], placement: "",
      note: "no hole assignment is admissible for this sketch on these clips",
    });
  }
  if (status === "unknown" || model === null) {
    return finish({ status: "timeout", holes: {}, margin: 0, violated: ex.map((e) => e.clip_id), satisfied: [], placement: "", note: "Z3 timed out" });
  }

  // ---- stage 1 done: W* and a witness point; stage 2: climb the margin levels
  const wStar = violatedWeight(enc, model);
  const p1 = enc.readHoles(model);
  const s1 = enc.preps.map((p) => cr.score(p, p1));
  const z3Ok1 = ex.map((_, k) => enc.isTrue(model, enc.goal(k)));
  const sat1 = z3Ok1.map((o, k) => (o ? k : -1)).filter((k) => k >= 0);
  const hasPos = ex.some((e) => e.positive);
  const neverFires = hasPos ? ex.filter((e) => e.positive).reduce((s, e) => s + e.weight, 0) : ex.reduce((s, e) => s + e.weight, 0);
  if (wStar >= neverFires - 1e-9) {
    // no better than the trivial "never fires" rule
    diffCheckPoint(enc, cr, p1, lvl(enc.marginMicro), z3Ok1);
    return finish({
      status: "unsat", holes: {}, margin: 0, violated: ids((k) => !z3Ok1[k]), satisfied: ids((k) => z3Ok1[k] as boolean), placement: "",
      note: "the best assignment is no better than a rule that never fires",
    });
  }
  let best: [Encoder, NonNullable<typeof model>] = [enc, model];
  const start = bestLevel(levels, Math.min(...sat1.map((k) => Math.abs(s1[k] as number))));
  let noteExtra = "";
  if (start > 0) {
    // the witness already achieves a higher level
    const e2 = mk(levels[start] as number);
    const [st2, m2] = await maxsmt(e2, left(), m);
    if (st2 === "sat" && m2 !== null && violatedWeight(e2, m2) <= wStar + 1e-9) best = [e2, m2];
    else noteExtra = "; margin level not proven"; // cannot happen unless Z3 timed out
  }
  const cur = best[0] !== enc ? start : 0;
  for (let i = cur + 1; i < levels.length; i++) {
    if (now() - t0 >= timeoutMs) {
      noteExtra = "; margin maximisation stopped by the timeout";
      break;
    }
    const e2 = mk(levels[i] as number);
    const [st2, m2] = await maxsmt(e2, left(), m);
    if (st2 === "unknown") {
      noteExtra = "; margin maximisation stopped by the timeout";
      break;
    }
    if (st2 === "sat" && m2 !== null && violatedWeight(e2, m2) <= wStar + 1e-9) best = [e2, m2];
    else break;
  }

  enc = best[0];
  const mdl = best[1];
  const mStar = lvl(enc.marginMicro);
  const p0 = enc.readHoles(mdl);
  const z3Ok = ex.map((_, k) => enc.isTrue(mdl, enc.goal(k)));
  diffCheckPoint(enc, cr, p0, mStar, z3Ok); // throws EncoderMismatch
  const satIdx = z3Ok.map((o, k) => (o ? k : -1)).filter((k) => k >= 0);

  // ---- temporal-slack placement, then the mandatory differential check on the returned rule
  const { holes, how } = await place(enc, cr, p0, mStar, satIdx, Math.max(1000, Math.min(PLACEMENT_BUDGET_MS, timeoutMs - (now() - t0))), m);
  const scores = enc.preps.map((p) => cr.score(p, holes));
  for (const k of satIdx) {
    const e = ex[k] as Example;
    const s = scores[k] as number;
    if (!labelOk(e.positive, s) || !holds(e.positive, s, mStar, EPS)) {
      throw new EncoderMismatch(
        `placed rule \`${JSON.stringify(fillHoles(sketch, holes))}\` fails on clip ${e.clip_id}: evaluator score ${s.toFixed(4)}, expected ` +
        `${e.positive ? ">=" : "<="} ${(e.positive ? mStar : -mStar).toFixed(4)}`,
      );
    }
  }
  const ok = ex.map((e, k) => labelOk(e.positive, scores[k] as number));
  const violated = ids((k) => !ok[k]);
  return finish({
    status: "sat", holes, margin: mStar, violated, satisfied: ids((k) => ok[k] as boolean), placement: how,
    note: `placement: ${how}${noteExtra}${m.degraded ? "; hole box cut short by the time limit" : ""}`,
    referenceVerified: opts.referenceHoles === undefined ? null : referenceIsAsGood(enc, cr, opts.referenceHoles, mStar, scores, violated),
  });
}
