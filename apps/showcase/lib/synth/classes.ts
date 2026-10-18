// Hole equivalence classes: the finite candidate set the exhaustive solver enumerates.
//
// Port of engine/tests/synth/synth_support.py (`_nodes`, `node_values`, `hole_candidates`) and of the hole helpers in
// engine/exemplar/synth/z3enc.py (`hole_kinds`, `lower_bound_holes`, window ordering).
//
// Window membership depends on a time hole only through how it compares with the frame-to-frame offsets
// Delta(i, j) = (t_j - t_i)/1000 (j >= i) of the examples. The "nodes" are 0, the clip length L, every such offset and
// every constant window bound <= L; two hole values between the same two consecutive nodes (or equal to the same node)
// are equivalent, so one representative per class is enough: each node and the midpoint of consecutive nodes.
// Hour holes are the integers 0..23. Nodes are exact: they are kept in half-millisecond units (integers), the
// midpoint of two integer-millisecond nodes is again an integer in those units, and `u / 2000` is the correctly
// rounded double of the exact rational, i.e. Python's `float(Fraction)`.

import type { Bound, Node, PreparedTrace, Rule } from "../dsl/index.ts";
import { children, isHole } from "../dsl/ast.ts";
import { SketchError } from "./types.ts";

export type HoleKind = "time" | "hour";

/** name -> kind; a name used as both an hour and a time is an error (z3enc.hole_kinds). */
export function holeKinds(sketch: Rule): Map<string, HoleKind> {
  const kinds = new Map<string, HoleKind>();
  const put = (x: unknown, kind: HoleKind): void => {
    if (isHole(x)) {
      const prev = kinds.get(x.name);
      if (prev === undefined) kinds.set(x.name, kind);
      else if (prev !== kind) throw new SketchError(`hole ?${x.name} is used both as an hour and as a time; use two names`);
    }
  };
  const walk = (n: Node): void => {
    if ("op" in n) {
      if (n.op === "eventually" || n.op === "always" || n.op === "then") {
        put(n.a, "time");
        put(n.b, "time");
      } else if (n.op === "holds_for") {
        put(n.d, "time");
      } else if (n.op === "hour_in") {
        put(n.h1, "hour");
        put(n.h2, "hour");
      }
    }
    for (const c of children(n)) walk(c);
  };
  walk(sketch);
  return kinds;
}

/** Holes that are the lower bound `a` of some eventually / always / then window. */
export function lowerBoundHoles(sketch: Rule): Set<string> {
  const out = new Set<string>();
  const walk = (n: Node): void => {
    if ("op" in n && (n.op === "eventually" || n.op === "always" || n.op === "then") && isHole(n.a)) out.add(n.a.name);
    for (const c of children(n)) walk(c);
  };
  walk(sketch);
  return out;
}

/** Windows (a, b) of eventually / always / then with at least one hole bound (z3enc._windows): the domain keeps a <= b. */
export function windowsWithHoles(sketch: Rule): [Bound, Bound][] {
  const out: [Bound, Bound][] = [];
  const walk = (n: Node): void => {
    if ("op" in n && (n.op === "eventually" || n.op === "always" || n.op === "then") && (isHole(n.a) || isHole(n.b))) {
      out.push([n.a, n.b]);
    }
    for (const c of children(n)) walk(c);
  };
  walk(sketch);
  return out;
}

/** Every window (a, b) of the sketch, with or without holes (synth_support._windows_with_holes). */
function allWindows(sketch: Rule): [Bound, Bound][] {
  const out: [Bound, Bound][] = [];
  const walk = (n: Node): void => {
    if ("op" in n && (n.op === "eventually" || n.op === "always" || n.op === "then")) out.push([n.a, n.b]);
    for (const c of children(n)) walk(c);
  };
  walk(sketch);
  return out;
}

/** What the nodes of a set of examples are made of (computed once per example set, shared by every sketch). */
export interface ExampleGeometry {
  /** Distinct integer-millisecond offsets t_j - t_i (j >= i) over all examples, ascending. */
  readonly deltasMs: readonly number[];
  /** Clip length in ms: max over examples of max(duration_ms, last frame time). */
  readonly lengthMs: number;
}

export function exampleGeometry(preps: readonly PreparedTrace[]): ExampleGeometry {
  const deltas = new Set<number>([0]);
  let L = 0;
  for (const p of preps) {
    const t = p.trace.frames.map((f) => f.t_ms);
    L = Math.max(L, p.trace.duration_ms ?? 0, t.length > 0 ? (t[t.length - 1] as number) : 0);
    for (let i = 0; i < t.length; i++) for (let j = i; j < t.length; j++) deltas.add((t[j] as number) - (t[i] as number));
  }
  return { deltasMs: [...deltas].sort((a, b) => a - b), lengthMs: L };
}

export interface HoleClasses {
  /** Hole names in first-occurrence order (the order `holes()` gives). */
  readonly names: readonly string[];
  readonly kinds: readonly HoleKind[];
  /** Representative value of each class, ascending (the engine's candidate list). */
  readonly reps: readonly Float64Array[];
  /** Closed interval of values the class covers: [lo, hi] (a node: lo == hi). Same indexing as `reps`. */
  readonly lo: readonly Float64Array[];
  readonly hi: readonly Float64Array[];
  /** Product of the per-hole class counts (the brute-force `total`). */
  readonly product: number;
  /** False if a constant window bound is not a whole number of milliseconds (not supported by the exact node set). */
  readonly supported: boolean;
}

/** Half-millisecond units -> seconds, correctly rounded. */
const sec = (u: number): number => u / 2000;

/**
 * hole_candidates(sketch, examples): per hole, one representative of every equivalence class.
 * `names` is the sketch's hole list in first-occurrence order.
 */
export function holeClasses(sketch: Rule, names: readonly string[], geo: ExampleGeometry): HoleClasses {
  const kinds = holeKinds(sketch);
  const nodes = new Set<number>(geo.deltasMs); // integer ms
  nodes.add(geo.lengthMs);
  let supported = true;
  for (const [a, b] of allWindows(sketch)) {
    for (const x of [a, b]) {
      if (isHole(x)) continue;
      const ms = x * 1000;
      if (Math.abs(ms - Math.round(ms)) > 1e-9) {
        supported = false;
        continue;
      }
      if (Math.round(ms) <= geo.lengthMs) nodes.add(Math.round(ms));
    }
  }
  const sorted = [...nodes].sort((x, y) => x - y);
  // class list in half-ms units: node, midpoint, node, midpoint, ..., node
  const reps: number[] = [];
  const lo: number[] = [];
  const hi: number[] = [];
  for (let i = 0; i < sorted.length; i++) {
    const u = 2 * (sorted[i] as number);
    reps.push(sec(u));
    lo.push(sec(u));
    hi.push(sec(u));
    if (i + 1 < sorted.length) {
      const next = 2 * (sorted[i + 1] as number);
      reps.push(sec((u + next) / 2));
      lo.push(sec(u));
      hi.push(sec(next));
    }
  }
  const repsT = Float64Array.from(reps);
  const loT = Float64Array.from(lo);
  const hiT = Float64Array.from(hi);
  const hours = Float64Array.from({ length: 24 }, (_, h) => h);
  const out = { reps: [] as Float64Array[], lo: [] as Float64Array[], hi: [] as Float64Array[], kinds: [] as HoleKind[] };
  let product = 1;
  for (const n of names) {
    const kind = kinds.get(n) ?? "time";
    out.kinds.push(kind);
    if (kind === "hour") {
      out.reps.push(hours);
      out.lo.push(hours);
      out.hi.push(hours);
      product *= 24;
    } else {
      out.reps.push(repsT);
      out.lo.push(loT);
      out.hi.push(hiT);
      product *= repsT.length;
    }
  }
  return { names, kinds: out.kinds, reps: out.reps, lo: out.lo, hi: out.hi, product, supported };
}
