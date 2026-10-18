// "How long does the body of a `holds_for >= ?d φ` sketch hold on a clip?" - the number the solver's range of d is made of.
//
// For a one-hole sketch  exists v: T: holds_for >= ?d φ  and one clip, let r(t) be the robustness of φ at each sampled
// frame t for a binding. `holds_for >= d` needs a window [t1, t1 + d] with every sampled frame in it true, and the window
// inside the clip (t1 + d <= last frame time). So the rule holds for exactly the d below the length of the longest run of true
// frames, measured to the frame that ends the run (an open bound: that frame is inside the window at d) or, when the
// run reaches the last frame, to the end of the clip (a closed bound). Everything here reads the DSL evaluator's own
// per-frame values (`rho`) and offsets (`PreparedTrace.D`), never a reimplementation of the semantics; the tests
// cross-check it against `robustness` on a 0.5 s sweep.

import { holesOf, isHole, rho as rhoAt, robustness, witness } from "../../../lib/dsl/index.ts";
import type { Phi, Rule } from "../../../lib/dsl/index.ts";
import type { TraceJson } from "../../../lib/data/types.ts";
import { asTrace, prep } from "./rules.ts";

export interface HoldsForShape {
  /** Name of the single hole, the `d` of `holds_for >= ?d`. */
  hole: string;
  /** The formula that has to hold continuously. */
  arg: Phi;
}

/** The sketch's shape if it is `exists ...: holds_for >= ?d φ` with φ hole-free and no context clause, else null. */
export function holdsForShape(sketch: Rule): HoldsForShape | null {
  const b = sketch.body;
  if (b.op !== "holds_for" || !isHole(b.d)) return null;
  if (sketch.when.length > 0 || holesOf(b.arg).length > 0) return null;
  return { hole: b.d.name, arg: b.arg };
}

export interface Hold {
  /** Supremum of the d for which a window fits inside a run of frames that pass the test; null if no frame passes. */
  sup: number | null;
  /** True when d = sup still holds (the run reaches the clip's last frame); false when the bound is open (d < sup). */
  closed: boolean;
  /** The entity binding (in variable order) the longest run belongs to. */
  binding: string[];
  /** Per-frame robustness of φ for that binding (the first binding when nothing passes). */
  rho: number[];
  /** Frame index range of that run, inclusive; null if no frame passes. */
  run: [number, number] | null;
}

/** Longest hold of the sketch body on a clip. `ok(r)` says whether a frame with body robustness r counts as holding. */
export function longestHold(sketch: Rule, trace: TraceJson, ok: (r: number) => boolean): Hold {
  const shape = holdsForShape(sketch);
  if (shape === null) throw new TypeError("longestHold needs a one-hole holds_for sketch");
  const p = prep(trace);
  const T = p.T;
  const names = sketch.vars.map((v) => v.name);
  let best: Hold = { sup: null, closed: false, binding: [], rho: new Array<number>(T).fill(-0.5), run: null };
  if (!p.ok) return best;
  let firstRho: number[] | null = null;
  let firstBinding: string[] = [];
  for (const b of p.bindings(sketch.vars.map((v) => v.type))) {
    const binding: Record<string, string> = {};
    names.forEach((n, i) => { binding[n] = b[i] as string; });
    const r = rhoAt(shape.arg, p, binding);
    if (firstRho === null) { firstRho = r; firstBinding = b; }
    let i = 0;
    while (i < T) {
      if (!ok(r[i] as number)) { i++; continue; }
      let j = i;
      while (j + 1 < T && ok(r[j + 1] as number)) j++;
      const closed = j === T - 1;
      const sup = closed ? (p.toEnd[i] as number) : (p.D[i * T + j + 1] as number);
      if (best.sup === null || sup > best.sup || (sup === best.sup && closed && !best.closed)) {
        best = { sup, closed, binding: b, rho: r, run: [i, j] };
      }
      i = j + 1;
    }
  }
  if (best.sup === null && firstRho !== null) best = { ...best, binding: firstBinding, rho: firstRho };
  return best;
}

const EPS = 1e-9;

export interface HoldExample {
  alias: string;
  label: "pos" | "neg";
  weight: number;
  trace: TraceJson;
}

export interface HoldTick extends Hold {
  alias: string;
  label: "pos" | "neg";
  weight: number;
  /** Sampled frame times in seconds. */
  times: number[];
}

/**
 * One tick per example, at margin m:
 *   a positive example needs the rule to score >= +m, so only frames with rho >= m count as holding;
 *   a negative example needs <= -m, so every frame that is not clearly false (rho > -m) counts as holding.
 * With m = 0 these are the plain "body is true" runs.
 */
export function holdTicks(sketch: Rule, examples: readonly HoldExample[], margin: number): HoldTick[] {
  return examples.map((e) => {
    const ok = e.label === "pos" ? (r: number) => r >= margin - EPS && r > 0 : (r: number) => r > -margin + EPS;
    const h = longestHold(sketch, e.trace, ok);
    return { ...h, alias: e.alias, label: e.label, weight: e.weight, times: e.trace.frames.map((f) => f.t_ms / 1000) };
  });
}

export interface HoldBox {
  lo: number;
  hi: number;
  /** The hole domain's upper end: the longest clip (engine: max of the clip duration and the last frame time). */
  domainHi: number;
}

/** Length of the hole domain [0, L]: the longest clip among the examples, in seconds. */
export function clipLength(examples: readonly HoldExample[]): number {
  let ms = 0;
  for (const e of examples) {
    const last = e.trace.frames.length > 0 ? (e.trace.frames[e.trace.frames.length - 1] as { t_ms: number }).t_ms : 0;
    ms = Math.max(ms, e.trace.duration_ms, last);
  }
  return ms / 1000;
}

/**
 * The range of d that keeps the `satisfied` examples right at the margin: at least the longest hold of every
 * satisfied negative, at most the longest hold of every satisfied positive (the engine reports this closure).
 */
export function holdBox(ticks: readonly HoldTick[], satisfied: ReadonlySet<string>, domainHi: number): HoldBox {
  let lo = 0;
  let hi = domainHi;
  for (const t of ticks) {
    if (!satisfied.has(t.alias)) continue;
    if (t.label === "neg") lo = Math.max(lo, t.sup ?? 0);
    else hi = Math.min(hi, t.sup ?? 0);
  }
  return { lo, hi, domainHi };
}

/** The 0.5 s grid points inside [lo, hi] (hours would be integers; not needed here). */
export function gridPoints(lo: number, hi: number, step = 0.5): number[] {
  const a = Math.ceil(lo / step - 1e-12);
  const b = Math.floor(hi / step + 1e-12);
  const out: number[] = [];
  for (let k = a; k <= b; k++) out.push(k * step);
  return out;
}

/** The engine's placement of a one-hole holds_for sketch: the centre of the range, snapped to the 0.5 s grid. */
export function placeD(box: { lo: number; hi: number }, step = 0.5): { centre: number; snapped: number | null } {
  const centre = (box.lo + box.hi) / 2;
  const cands = gridPoints(box.lo, box.hi, step);
  if (cands.length === 0) return { centre, snapped: null };
  let best = cands[0] as number;
  for (const g of cands) {
    const dg = Math.abs(g - centre);
    const db = Math.abs(best - centre);
    if (dg < db || (dg === db && g < best)) best = g;
  }
  return { centre, snapped: best };
}

export interface ScoreAt {
  score: number;
  /** The score is on the labelled side of zero. */
  right: boolean;
  /** The window the evaluator used for the best start: [t_start, t_end] in seconds, or null if the trace has none. */
  window: [number, number] | null;
}

/** The rule's score on one example with the hole set to d, from the DSL evaluator, and the window behind it. */
export function scoreAt(sketch: Rule, ex: HoldExample, d: number): ScoreAt {
  const shape = holdsForShape(sketch);
  if (shape === null) throw new TypeError("scoreAt needs a one-hole holds_for sketch");
  const holes = { [shape.hole]: d };
  const t = asTrace(ex.trace);
  const score = robustness(sketch, t, holes);
  const w = witness(sketch, t, holes);
  const root = w.spans.find((s) => s.path === "body");
  return {
    score,
    right: score > 0 === (ex.label === "pos"),
    window: root ? [root.t_start_ms / 1000, root.t_end_ms / 1000] : null,
  };
}
