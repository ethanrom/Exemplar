// Quantitative (robustness) evaluator; semantics in docs/DSL.md. Port of engine/exemplar/dsl/evaluator.py,
// checked against the scalar reference engine/tests/dsl/dsl_reference.py by the golden tests.
//
// Time is integer milliseconds. A window offset is computed as (t_ms[j] - t_ms[i]) / 1000 (one division of
// exact integers, correctly rounded) and compared with the bounds; it is never a difference of float seconds.
// All values are IEEE doubles computed with the same operations as the engine, so results are bit-identical.
//
// Frame times must be non-decreasing (the engine's Trace validation requires strictly increasing): a window
// W(i; a, b) is then a contiguous range of frames, found with two pointers.
//
// Evaluators require *closed*, well-typed rules (typecheck first if the rule came from an LLM).
//
// Hot path: `CompiledRule.score(prepared, holes)` allocates nothing per call once the rule has seen the trace
// (atom series and node buffers are cached per rule x trace), which is what hole sweeps in synthesis rely on.

import { C, holesOf, isHole } from "./ast.ts";
import type { Bound, Ctx, Phi, Rule } from "./ast.ts";
import { UnboundHoleError } from "./errors.ts";
import { ABSENT_VALUE, CONF_VALUE, THRESHOLD, VAR_TYPES } from "./ontology.ts";
import type { Trace, TraceContext } from "./trace.ts";
import { boundValue } from "./util.ts";
import type { HoleValues } from "./util.ts";

const SEP = "\u0001";

function sigKey(pred: string, args: readonly string[]): string {
  return pred + SEP + args.join(SEP);
}

const hasOwn = (o: object, k: string): boolean => Object.hasOwn(o, k);

/**
 * A `Trace` plus the arrays every evaluation needs: the pairwise offset matrix, a one-pass signal index and a
 * bindings cache. Build once per trace (`prepare`) and reuse it across many rule / hole evaluations; the
 * instance is read-only apart from its caches.
 */
export class PreparedTrace {
  readonly trace: Trace;
  readonly T: number;
  /** status "ok" and at least one frame. */
  readonly ok: boolean;
  readonly tMs: Float64Array;
  /** D[i * T + j] = (t_ms[j] - t_ms[i]) / 1000. */
  readonly D: Float64Array;
  /** toEnd[i] = (t_ms[last] - t_ms[i]) / 1000 with the last frame by index. */
  readonly toEnd: Float64Array;
  /** Frame times are non-decreasing (required to evaluate windows). */
  readonly sorted: boolean;
  private readonly absent: Float64Array;
  private sig: Map<string, Float64Array> | null = null;
  private readonly bindingCache = new Map<string, string[][]>();

  constructor(trace: Trace) {
    this.trace = trace;
    const frames = trace.frames;
    const T = frames.length;
    this.T = T;
    this.ok = trace.status === "ok" && T > 0;
    this.tMs = new Float64Array(T);
    let sorted = true;
    for (let i = 0; i < T; i++) {
      this.tMs[i] = frames[i].t_ms;
      if (i > 0 && this.tMs[i] < this.tMs[i - 1]) sorted = false;
    }
    this.sorted = sorted;
    this.D = new Float64Array(T * T);
    for (let i = 0; i < T; i++) for (let j = 0; j < T; j++) this.D[i * T + j] = (this.tMs[j] - this.tMs[i]) / 1000;
    this.toEnd = new Float64Array(T);
    for (let i = 0; i < T; i++) this.toEnd[i] = this.D[i * T + (T - 1)];
    this.absent = new Float64Array(T).fill(ABSENT_VALUE);
  }

  /** One pass over all facts; agrees exactly with `Trace.signal` in the engine (tested there). */
  private buildSignals(): Map<string, Float64Array> {
    const n = this.T;
    const tr = this.trace;
    const idx = new Map<string, Float64Array>();
    const put = (key: string, i: number, v: number): void => {
      let arr = idx.get(key);
      if (arr === undefined) {
        arr = new Float64Array(n).fill(ABSENT_VALUE);
        idx.set(key, arr);
      }
      if (v > arr[i]) arr[i] = v;
    };
    for (let i = 0; i < n; i++) {
      for (const f of tr.frames[i].facts ?? []) {
        const v = CONF_VALUE[f.conf];
        put(sigKey(f.pred, f.args), i, v);
        for (const a of f.args) put(sigKey("present", [a]), i, v); // presence is implied by any fact on the entity
      }
    }
    const floor = CONF_VALUE.med;
    for (const e of tr.entities) {
      // clip-level attrs hold in every frame
      for (const label of e.attrs ?? []) {
        const key = sigKey("attr", [e.id, label]);
        const arr = idx.get(key);
        if (arr === undefined) idx.set(key, new Float64Array(n).fill(floor));
        else for (let i = 0; i < n; i++) if (floor > arr[i]) arr[i] = floor;
      }
    }
    return idx;
  }

  /** Same values as the engine's `Trace.signal(pred, args)`; the returned array is shared, do not modify it. */
  signal(pred: string, args: readonly string[]): Float64Array {
    this.sig ??= this.buildSignals();
    return this.sig.get(sigKey(pred, args)) ?? this.absent;
  }

  /**
   * The frames of window W(i; a, b) = { j : a <= (t_j - t_i)/1000 <= b } as the inclusive ranges
   * [lo[i], hi[i]] (empty when lo[i] > hi[i]). Written into the given arrays.
   */
  windowInto(a: number, b: number, lo: Int32Array, hi: Int32Array): void {
    if (!this.sorted) throw new Error("frame times must be non-decreasing");
    const T = this.T;
    const D = this.D;
    let l = 0;
    let h = -1;
    for (let i = 0; i < T; i++) {
      const row = i * T;
      while (l < T && D[row + l] < a) l++;
      while (h + 1 < T && D[row + h + 1] <= b) h++;
      lo[i] = l;
      hi[i] = h;
    }
  }

  /** Frame indices of W(i; a, b), ascending. */
  windowIndices(i: number, a: number, b: number): number[] {
    const lo = new Int32Array(this.T);
    const hi = new Int32Array(this.T);
    this.windowInto(a, b, lo, hi);
    const out: number[] = [];
    for (let j = lo[i]; j <= hi[i]; j++) out.push(j);
    return out;
  }

  /** Every assignment of *distinct* entities to variables of the given DSL types (itertools.product order). */
  bindings(varTypes: readonly string[]): string[][] {
    const key = varTypes.join(",");
    let b = this.bindingCache.get(key);
    if (b === undefined) {
      const pools = varTypes.map((vt) => {
        const admitted = VAR_TYPES.get(vt) ?? [];
        return this.trace.entities.filter((e) => admitted.includes(e.type)).map((e) => e.id);
      });
      const out: string[][] = [];
      const cur: string[] = [];
      const rec = (k: number): void => {
        if (k === pools.length) {
          if (new Set(cur).size === cur.length) out.push(cur.slice());
          return;
        }
        for (const id of pools[k]) {
          cur.push(id);
          rec(k + 1);
          cur.pop();
        }
      };
      rec(0);
      b = out;
      this.bindingCache.set(key, b);
    }
    return b;
  }
}

const preparedCache = new WeakMap<Trace, PreparedTrace>();

/** The `PreparedTrace` for `trace` (cached by object identity). */
export function prepare(trace: Trace | PreparedTrace): PreparedTrace {
  if (trace instanceof PreparedTrace) return trace;
  let p = preparedCache.get(trace);
  if (p === undefined) {
    p = new PreparedTrace(trace);
    preparedCache.set(trace, p);
  }
  return p;
}

// =========================================================================== lowering (AST -> plan)
/** A formula node in post-order: kids come before their parent. `a`/`b` hold constants, `aName`/`bName` holes. */
export interface PNode {
  readonly id: number;
  readonly op: Phi["op"];
  readonly node: Phi;
  readonly kids: readonly PNode[];
  /** atom: predicate and arguments. */
  readonly pred: string;
  readonly args: readonly string[];
  /** atom: per argument, the variable slot it names or -1 for a literal (zone / label). */
  readonly slots: readonly number[];
  readonly aConst: number;
  readonly bConst: number;
  readonly aName: string | null;
  readonly bName: string | null;
}

function bndName(x: Bound | undefined): string | null {
  return x !== undefined && isHole(x) ? x.name : null;
}
function bndConst(x: Bound | undefined): number {
  return x === undefined || isHole(x) ? 0 : x;
}

/** Lower a formula to a post-order plan; `names` are the variables (the last declaration of a name wins). */
export function lowerPlan(body: Phi, names: readonly string[]): PNode[] {
  const slotOf = new Map<string, number>();
  names.forEach((n, i) => slotOf.set(n, i));
  const plan: PNode[] = [];
  const go = (node: Phi): PNode => {
    const kids: PNode[] =
      node.op === "atom" ? []
      : node.op === "and" || node.op === "or" ? node.args.map(go)
      : node.op === "then" ? [go(node.left), go(node.right)]
      : [go(node.arg)];
    let a: Bound | undefined;
    let b: Bound | undefined;
    if (node.op === "eventually" || node.op === "always" || node.op === "then") {
      a = node.a;
      b = node.b;
    } else if (node.op === "holds_for") {
      a = node.d;
    }
    const args = node.op === "atom" ? node.args : [];
    const p: PNode = {
      id: plan.length, op: node.op, node, kids,
      pred: node.op === "atom" ? node.pred : "", args, slots: args.map((x) => slotOf.get(x) ?? -1),
      aConst: bndConst(a), bConst: bndConst(b), aName: bndName(a), bName: bndName(b),
    };
    plan.push(p);
    return p;
  };
  go(body);
  return plan;
}

const isTemporal = (op: Phi["op"]): boolean => op === "eventually" || op === "always" || op === "then" || op === "holds_for";

/** Everything cached for one (plan, trace, bindings) triple; node buffers are reused across calls. */
export class TraceCache {
  readonly prep: PreparedTrace;
  readonly bindings: readonly (readonly string[])[];
  /** atomRho[nodeId][binding]: s(t) - THRESHOLD for atom nodes. */
  readonly atomRho: (Float64Array[] | null)[];
  /** buf[nodeId]: rho of the node for the binding last evaluated. */
  readonly buf: Float64Array[];
  /** inner[nodeId]: the pre-cummax array of `then` / `holds_for` nodes. */
  readonly inner: (Float64Array | null)[];
  /** lo[nodeId], hi[nodeId]: the window of temporal nodes as inclusive frame ranges per start frame. */
  readonly lo: (Int32Array | null)[];
  readonly hi: (Int32Array | null)[];
  /** Numeric window bounds of the last call, per node: a (or d) and b. */
  readonly av: Float64Array;
  readonly bv: Float64Array;

  constructor(plan: readonly PNode[], prep: PreparedTrace, bindings: readonly (readonly string[])[]) {
    this.prep = prep;
    this.bindings = bindings;
    const T = prep.T;
    this.atomRho = plan.map(() => null);
    this.buf = plan.map(() => new Float64Array(0));
    this.inner = plan.map(() => null);
    this.lo = plan.map(() => null);
    this.hi = plan.map(() => null);
    this.av = new Float64Array(plan.length);
    this.bv = new Float64Array(plan.length);
    for (const n of plan) {
      if (n.op === "atom") {
        this.atomRho[n.id] = bindings.map((b) => {
          const s = prep.signal(n.pred, n.args.map((x, k) => (n.slots[k] >= 0 ? b[n.slots[k]] : x)));
          const r = new Float64Array(T);
          for (let i = 0; i < T; i++) r[i] = s[i] - THRESHOLD;
          return r;
        });
      } else {
        this.buf[n.id] = new Float64Array(T);
        if (n.op === "then" || n.op === "holds_for") this.inner[n.id] = new Float64Array(T);
        if (isTemporal(n.op)) {
          this.lo[n.id] = new Int32Array(T);
          this.hi[n.id] = new Int32Array(T);
        }
      }
    }
  }
}

function holeValue(name: string, holes: HoleValues | null | undefined): number {
  if (holes == null || !hasOwn(holes, name)) throw new UnboundHoleError([name]);
  return Number(holes[name]);
}

/** Resolve the numeric bounds and windows of every temporal node (once per hole point, shared by bindings). */
export function setupWindows(plan: readonly PNode[], tc: TraceCache, holes: HoleValues | null | undefined): void {
  const prep = tc.prep;
  for (const n of plan) {
    if (!isTemporal(n.op)) continue;
    const a = n.aName === null ? n.aConst : holeValue(n.aName, holes);
    const b = n.bName === null ? n.bConst : holeValue(n.bName, holes);
    tc.av[n.id] = a;
    tc.bv[n.id] = b;
    if (n.op === "holds_for") prep.windowInto(0.0, a, tc.lo[n.id] as Int32Array, tc.hi[n.id] as Int32Array);
    else prep.windowInto(a, b, tc.lo[n.id] as Int32Array, tc.hi[n.id] as Int32Array);
  }
}

/** out[t] = max over t1 >= t of x[t1]. */
function revCummaxInto(x: Float64Array, out: Float64Array): void {
  let m = -Infinity;
  for (let t = x.length - 1; t >= 0; t--) {
    if (x[t] > m) m = x[t];
    out[t] = m;
  }
}

/** Evaluate every node for binding `b`; the series of node `n` is left in `tc.buf[n.id]`. Returns the root's. */
export function runPlan(plan: readonly PNode[], tc: TraceCache, b: number): Float64Array {
  const T = tc.prep.T;
  const toEnd = tc.prep.toEnd;
  for (const n of plan) {
    const id = n.id;
    switch (n.op) {
      case "atom":
        tc.buf[id] = (tc.atomRho[id] as Float64Array[])[b];
        break;
      case "not": {
        const x = tc.buf[n.kids[0].id];
        const r = tc.buf[id];
        for (let i = 0; i < T; i++) r[i] = -x[i];
        break;
      }
      case "and":
      case "or": {
        let acc = tc.buf[n.kids[0].id];
        if (n.kids.length === 1) {
          tc.buf[id] = acc;
          break;
        }
        const isAnd = n.op === "and";
        const r = tc.buf[id];
        for (let k = 1; k < n.kids.length; k++) {
          const y = tc.buf[n.kids[k].id];
          if (isAnd) for (let i = 0; i < T; i++) r[i] = acc[i] < y[i] ? acc[i] : y[i];
          else for (let i = 0; i < T; i++) r[i] = acc[i] > y[i] ? acc[i] : y[i];
          acc = r;
        }
        break;
      }
      case "eventually":
      case "always": {
        const x = tc.buf[n.kids[0].id];
        const lo = tc.lo[id] as Int32Array;
        const hi = tc.hi[id] as Int32Array;
        const r = tc.buf[id];
        const ev = n.op === "eventually";
        for (let i = 0; i < T; i++) {
          const l = lo[i];
          const h = hi[i];
          if (l > h) {
            r[i] = -C; // empty window -> -C (both operators, by design)
            continue;
          }
          let acc = x[l];
          if (ev) {
            for (let j = l + 1; j <= h; j++) if (x[j] > acc) acc = x[j];
          } else {
            for (let j = l + 1; j <= h; j++) if (x[j] < acc) acc = x[j];
          }
          r[i] = acc;
        }
        break;
      }
      case "then": {
        const x = tc.buf[n.kids[0].id];
        const y = tc.buf[n.kids[1].id];
        const lo = tc.lo[id] as Int32Array;
        const hi = tc.hi[id] as Int32Array;
        const inner = tc.inner[id] as Float64Array;
        for (let i = 0; i < T; i++) {
          const l = lo[i];
          const h = hi[i];
          let ymax = -C;
          if (l <= h) {
            ymax = y[l];
            for (let j = l + 1; j <= h; j++) if (y[j] > ymax) ymax = y[j];
          }
          inner[i] = x[i] < ymax ? x[i] : ymax;
        }
        revCummaxInto(inner, tc.buf[id]);
        break;
      }
      case "holds_for": {
        const x = tc.buf[n.kids[0].id];
        const d = tc.av[id];
        const lo = tc.lo[id] as Int32Array;
        const hi = tc.hi[id] as Int32Array;
        const inner = tc.inner[id] as Float64Array;
        for (let i = 0; i < T; i++) {
          const l = lo[i];
          const h = hi[i];
          // valid: t1 + d <= t_end (one-division offsets) and a non-empty window
          if (toEnd[i] >= d && l <= h) {
            let m = x[l];
            for (let j = l + 1; j <= h; j++) if (x[j] < m) m = x[j];
            inner[i] = m;
          } else {
            inner[i] = -C;
          }
        }
        revCummaxInto(inner, tc.buf[id]);
        break;
      }
      default:
        throw new Error(`unknown op ${(n as { op: string }).op}`);
    }
  }
  return tc.buf[plan[plan.length - 1].id];
}

// =========================================================================== context atoms (crisp)
/** Truth of one context atom. Missing context (null / undefined) makes the atom false. */
export function ctxHolds(c: Ctx, context: TraceContext | undefined, values?: HoleValues | null): boolean {
  switch (c.op) {
    case "hour_in": {
      const h = context?.local_hour;
      if (h == null) return false;
      const h1 = boundValue(c.h1, values, true);
      const h2 = boundValue(c.h2, values, true);
      return h1 <= h2 ? h1 <= h && h <= h2 : h >= h1 || h <= h2; // h1 > h2 wraps past midnight
    }
    case "subtype_eq":
      return context?.sub_type != null && context.sub_type === c.value;
    case "device_eq":
      return context?.device_id != null && context.device_id === c.value;
    default:
      throw new TypeError(`not a context atom: ${JSON.stringify(c)}`);
  }
}

/** Context atoms are crisp +-C and combine with min (and): +C if all hold or there are none, else -C. */
export function ctxValue(ctxs: readonly Ctx[], context: TraceContext | undefined, values?: HoleValues | null): number {
  for (const c of ctxs) if (!ctxHolds(c, context, values)) return -C;
  return C;
}

// =========================================================================== rules
/** Where the best score of a rule on a trace is reached (the first binding, then the earliest frame). */
export interface Argmax {
  readonly value: number;
  readonly binding: number;
  readonly frame: number;
}

/**
 * A rule lowered once for repeated evaluation (e.g. a sketch with holes at many hole points):
 *
 *     const cr = compileRule(sketch);
 *     for (const point of points) cr.score(prepared, point);
 */
export class CompiledRule {
  readonly rule: Rule;
  readonly names: readonly string[];
  readonly types: readonly string[];
  readonly plan: readonly PNode[];
  readonly when: readonly Ctx[];
  readonly holes: readonly string[];
  private readonly caches = new WeakMap<PreparedTrace, TraceCache>();

  constructor(rule: Rule) {
    this.rule = rule;
    this.names = rule.vars.map((v) => v.name);
    this.types = rule.vars.map((v) => v.type);
    this.plan = lowerPlan(rule.body, this.names);
    this.when = rule.when;
    this.holes = holesOf(rule);
  }

  private check(holes: HoleValues | null | undefined): void {
    if (this.holes.length === 0) return;
    const missing = this.holes.filter((h) => holes == null || !hasOwn(holes, h));
    if (missing.length > 0) throw new UnboundHoleError(missing);
  }

  /** The cache of this rule on `prep` (built on first use). Requires prep.ok and at least one binding. */
  cacheFor(prep: PreparedTrace): TraceCache {
    let tc = this.caches.get(prep);
    if (tc === undefined) {
      tc = new TraceCache(this.plan, prep, prep.bindings(this.types));
      this.caches.set(prep, tc);
    }
    return tc;
  }

  private argmaxChecked(prep: PreparedTrace, holes: HoleValues | null | undefined): Argmax {
    const tc = this.cacheFor(prep);
    setupWindows(this.plan, tc, holes);
    let best = -Infinity;
    let bi = 0;
    let ti = 0;
    for (let b = 0; b < tc.bindings.length; b++) {
      const body = runPlan(this.plan, tc, b);
      for (let t = 0; t < body.length; t++) {
        if (body[t] > best) {
          best = body[t];
          bi = b;
          ti = t;
        }
      }
    }
    return { value: best, binding: bi, frame: ti };
  }

  /**
   * Evaluate every binding; returns the argmax (first binding, earliest frame on ties) or null when the rule has
   * no bindings on the trace (or the trace failed). Ignores the context atoms (see `ctxValue`).
   */
  argmax(prep: PreparedTrace, holes?: HoleValues | null): Argmax | null {
    this.check(holes);
    if (!prep.ok || prep.bindings(this.types).length === 0) return null;
    return this.argmaxChecked(prep, holes);
  }

  /** Re-evaluate one binding so that `cacheFor(prep).buf` / `.inner` hold its node series (witness extraction). */
  evalBinding(prep: PreparedTrace, binding: number, holes?: HoleValues | null): TraceCache {
    const tc = this.cacheFor(prep);
    setupWindows(this.plan, tc, holes);
    runPlan(this.plan, tc, binding);
    return tc;
  }

  /** robustness of the rule on the trace, with `holes` substituted (hours round to int, half to even). */
  score(trace: Trace | PreparedTrace, holes?: HoleValues | null): number {
    this.check(holes);
    const prep = prepare(trace);
    if (!prep.ok || prep.bindings(this.types).length === 0) return -C;
    if (this.when.length > 0 && ctxValue(this.when, prep.trace.context, holes) < 0) return -C;
    const best = this.argmaxChecked(prep, holes).value;
    return best < C ? best : C;
  }

  scores(traces: readonly (Trace | PreparedTrace)[], holes?: HoleValues | null): number[] {
    return traces.map((t) => this.score(t, holes));
  }
}

export function compileRule(rule: Rule): CompiledRule {
  return new CompiledRule(rule);
}

/**
 * score(rule, clip) = max over type-correct bindings of max over t of rho(body AND context).
 *
 * No bindings, an empty / failed trace, or a false context atom gives -C (= -0.5). The result lies in
 * [-C, C]; the rule matches when it is > 0. A closed rule is required: pass `holes` to fill any holes,
 * otherwise `UnboundHoleError` is thrown.
 */
export function robustness(rule: Rule, trace: Trace | PreparedTrace, holes?: HoleValues | null): number {
  return new CompiledRule(rule).score(trace, holes);
}

/** Robustness of `fillHoles(rule, holes)` on `trace` (the hole-point helper synthesis calls). */
export function evaluate(rule: Rule, trace: Trace | PreparedTrace, holes?: HoleValues | null): number {
  return robustness(rule, trace, holes);
}

/**
 * rho(phi, t) at every frame t for one binding (variable name -> entity id), a plain array of length T.
 * Arguments of atoms that are not keys of `binding` are literals (zones, labels).
 */
export function rho(
  phi: Phi, trace: Trace | PreparedTrace, binding: Readonly<Record<string, string>>, holes?: HoleValues | null,
): number[] {
  const left = holesOf(phi).filter((h) => holes == null || !hasOwn(holes, h));
  if (left.length > 0) throw new UnboundHoleError(left);
  const prep = prepare(trace);
  if (prep.T === 0) return [];
  const names = Object.keys(binding);
  const plan = lowerPlan(phi, names);
  const tc = new TraceCache(plan, prep, [names.map((n) => binding[n])]);
  setupWindows(plan, tc, holes);
  return Array.from(runPlan(plan, tc, 0));
}
