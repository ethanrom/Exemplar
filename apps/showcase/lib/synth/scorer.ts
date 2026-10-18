// Scoring a sketch at many hole points.
//
// The same robustness semantics as the DSL evaluator (lib/dsl/evaluator.ts, `evalNode`): identical operations on
// identical doubles, so the scores are bit-for-bit those of `CompiledRule.score` (a test compares them on thousands of
// points). The difference is speed: the solver visits every hole class of a sketch (up to ~40,000 points for two
// holes), and the general evaluator rebuilds window index lists per point. Here
//   * window membership is a direct scan of the trace's offset matrix (`a <= D[i][j] <= b`), and
//   * every sub-formula is memoised on the class indices of only the holes it mentions (a sub-formula that does not
//     mention a hole is computed once for all values of that hole).
// Nothing here knows about labels, weights or margins.

import type { Bound, Ctx, Phi, PreparedTrace, Rule } from "../dsl/index.ts";
import { C, isHole } from "../dsl/ast.ts";
import { ctxValue } from "../dsl/evaluator.ts";
import { THRESHOLD } from "../dsl/ontology.ts";

interface SNode {
  readonly id: number;
  readonly op: Phi["op"];
  readonly kids: readonly SNode[];
  readonly pred: string;
  readonly args: readonly string[];
  /** Window bounds: constant value, or the index of the hole (>= 0) when `aHole` / `bHole` is set. */
  readonly aConst: number;
  readonly bConst: number;
  readonly aHole: number;
  readonly bHole: number;
  /** Hole indices this sub-formula depends on, ascending. */
  readonly free: readonly number[];
  readonly strides: readonly number[];
  readonly memo: boolean;
}

interface BEnv {
  readonly prep: PreparedTrace;
  readonly binding: Map<string, string>;
  readonly memo: Map<number, Float64Array>[];
  /** Reusable output buffers of the nodes that are not memoised (their result is consumed before the next point). */
  readonly scratch: (Float64Array | undefined)[];
}

export class PointScorer {
  private readonly nHoles: number;
  private readonly root: SNode;
  private readonly nNodes: number;
  private readonly preps: readonly PreparedTrace[];
  private readonly types: readonly string[];
  private readonly names: readonly string[];
  private readonly when: readonly Ctx[];
  private readonly hourHoles: boolean;
  private readonly holeNames: readonly string[];
  private envs: (BEnv[] | null)[];
  private idx: ArrayLike<number> = [];
  private vals: ArrayLike<number> = [];
  private holesObj: Record<string, number> = {};
  private ctxConst: number | null = null;

  constructor(sketch: Rule, preps: readonly PreparedTrace[], holeNames: readonly string[], classCounts: readonly number[]) {
    this.nHoles = holeNames.length;
    this.holeNames = holeNames;
    this.preps = preps;
    this.types = sketch.vars.map((v) => v.type);
    this.names = sketch.vars.map((v) => v.name);
    this.when = sketch.when;
    this.hourHoles = sketch.when.some((c) => c.op === "hour_in" && (isHole(c.h1) || isHole(c.h2)));
    const holeIdx = new Map(holeNames.map((n, i) => [n, i] as const));
    let counter = 0;
    const build = (node: Phi): SNode => {
      let kids: SNode[] = [];
      let pred = "";
      let args: readonly string[] = [];
      let a: Bound = 0;
      let b: Bound = 0;
      switch (node.op) {
        case "atom":
          pred = node.pred;
          args = node.args;
          break;
        case "not":
          kids = [build(node.arg)];
          break;
        case "and":
        case "or":
          kids = node.args.map(build);
          break;
        case "eventually":
        case "always":
          a = node.a;
          b = node.b;
          kids = [build(node.arg)];
          break;
        case "then":
          a = node.a;
          b = node.b;
          kids = [build(node.left), build(node.right)];
          break;
        case "holds_for":
          a = node.d;
          kids = [build(node.arg)];
          break;
      }
      const free = new Set<number>();
      for (const k of kids) for (const h of k.free) free.add(h);
      const bound = (x: Bound): { c: number; h: number } => {
        if (isHole(x)) {
          const h = holeIdx.get(x.name);
          if (h === undefined) throw new Error(`unknown hole ?${x.name}`);
          free.add(h);
          return { c: 0, h };
        }
        return { c: x, h: -1 };
      };
      const ba = bound(a);
      const bb = bound(b);
      const f = [...free].sort((x, y) => x - y);
      const strides: number[] = [];
      let s = 1;
      for (const h of f) {
        strides.push(s);
        s *= classCounts[h] as number;
      }
      return {
        id: counter++, op: node.op, kids, pred, args,
        aConst: ba.c, aHole: ba.h, bConst: bb.c, bHole: bb.h, free: f, strides, memo: f.length < this.nHoles,
      };
    };
    this.root = build(sketch.body);
    this.nNodes = counter;
    this.envs = preps.map(() => null);
    if (!this.hourHoles) this.ctxConst = null; // computed lazily per trace (depends on the trace's context)
  }

  /** Set the current hole point: class index and value per hole. */
  setPoint(idx: ArrayLike<number>, vals: ArrayLike<number>): void {
    this.idx = idx;
    this.vals = vals;
    if (this.hourHoles) {
      const o: Record<string, number> = {};
      for (let h = 0; h < this.nHoles; h++) o[this.holeNames[h] as string] = vals[h] as number;
      this.holesObj = o;
    }
  }

  private envsOf(t: number): BEnv[] {
    let e = this.envs[t];
    if (e === null || e === undefined) {
      const prep = this.preps[t] as PreparedTrace;
      e = prep.bindings(this.types).map((b) => {
        const binding = new Map<string, string>();
        this.names.forEach((n, i) => binding.set(n, b[i] as string));
        const memo: Map<number, Float64Array>[] = [];
        for (let i = 0; i < this.nNodes; i++) memo.push(new Map());
        return { prep, binding, memo, scratch: new Array<Float64Array | undefined>(this.nNodes) };
      });
      this.envs[t] = e;
    }
    return e;
  }

  /** robustness of the sketch on trace `t` at the current point (CompiledRule.score semantics). */
  score(t: number): number {
    const prep = this.preps[t] as PreparedTrace;
    if (!prep.ok) return -C;
    const envs = this.envsOf(t);
    if (envs.length === 0) return -C;
    if (ctxValue(this.when, prep.trace.context, this.hourHoles ? this.holesObj : null) < 0) return -C;
    let best = -Infinity;
    for (const env of envs) {
      const body = this.ev(this.root, env);
      for (let i = 0; i < body.length; i++) if ((body[i] as number) > best) best = body[i] as number;
    }
    return Math.min(best, C);
  }

  private key(n: SNode): number {
    let k = 0;
    for (let i = 0; i < n.free.length; i++) k += (this.idx[n.free[i] as number] as number) * (n.strides[i] as number);
    return k;
  }

  private ev(n: SNode, env: BEnv): Float64Array {
    if (n.memo) {
      const k = this.key(n);
      const hit = env.memo[n.id]!.get(k);
      if (hit !== undefined) return hit;
      const r = this.compute(n, env);
      env.memo[n.id]!.set(k, r);
      return r;
    }
    return this.compute(n, env);
  }

  private lo(n: SNode): number {
    return n.aHole >= 0 ? (this.vals[n.aHole] as number) : n.aConst;
  }

  private hi(n: SNode): number {
    return n.bHole >= 0 ? (this.vals[n.bHole] as number) : n.bConst;
  }

  private out(n: SNode, env: BEnv): Float64Array {
    if (n.memo) return new Float64Array(env.prep.T);
    return (env.scratch[n.id] ??= new Float64Array(env.prep.T));
  }

  private compute(n: SNode, env: BEnv): Float64Array {
    const prep = env.prep;
    const T = prep.T;
    switch (n.op) {
      case "atom": {
        const args = n.args.map((a) => env.binding.get(a) ?? a);
        const s = prep.signal(n.pred, args);
        const r = this.out(n, env);
        for (let i = 0; i < T; i++) r[i] = (s[i] as number) - THRESHOLD;
        return r;
      }
      case "not": {
        const x = this.ev(n.kids[0] as SNode, env);
        const r = this.out(n, env);
        for (let i = 0; i < T; i++) r[i] = -(x[i] as number);
        return r;
      }
      case "and":
      case "or": {
        const isAnd = n.op === "and";
        const m = this.out(n, env);
        const x0 = this.ev(n.kids[0] as SNode, env);
        for (let i = 0; i < T; i++) m[i] = x0[i] as number;
        for (let k = 1; k < n.kids.length; k++) {
          const y = this.ev(n.kids[k] as SNode, env);
          for (let i = 0; i < T; i++) {
            const p = m[i] as number;
            const q = y[i] as number;
            m[i] = isAnd ? (q < p ? q : p) : q > p ? q : p;
          }
        }
        return m;
      }
      case "eventually":
      case "always": {
        const x = this.ev(n.kids[0] as SNode, env);
        const a = this.lo(n);
        const b = this.hi(n);
        const D = prep.D;
        const isEv = n.op === "eventually";
        const r = this.out(n, env);
        for (let i = 0; i < T; i++) {
          let acc = isEv ? -Infinity : Infinity;
          let has = false;
          const row = i * T;
          for (let j = 0; j < T; j++) {
            const d = D[row + j] as number;
            if (d >= a && d <= b) {
              has = true;
              const v = x[j] as number;
              if (isEv) {
                if (v > acc) acc = v;
              } else if (v < acc) acc = v;
            }
          }
          r[i] = has ? acc : -C; // empty window -> -C (both operators, by design)
        }
        return r;
      }
      case "then": {
        const x = this.ev(n.kids[0] as SNode, env);
        const y = this.ev(n.kids[1] as SNode, env);
        const a = this.lo(n);
        const b = this.hi(n);
        const D = prep.D;
        const inner = this.out(n, env);
        for (let i = 0; i < T; i++) {
          let ymax = -Infinity;
          let has = false;
          const row = i * T;
          for (let j = 0; j < T; j++) {
            const d = D[row + j] as number;
            if (d >= a && d <= b) {
              has = true;
              const v = y[j] as number;
              if (v > ymax) ymax = v;
            }
          }
          inner[i] = Math.min(x[i] as number, has ? ymax : -C);
        }
        return revCummaxInPlace(inner);
      }
      case "holds_for": {
        const x = this.ev(n.kids[0] as SNode, env);
        const d = this.lo(n);
        const D = prep.D;
        const inner = this.out(n, env);
        for (let i = 0; i < T; i++) {
          let m = Infinity;
          let has = false;
          const row = i * T;
          for (let j = 0; j < T; j++) {
            const off = D[row + j] as number;
            if (off >= 0.0 && off <= d) {
              has = true;
              const v = x[j] as number;
              if (v < m) m = v;
            }
          }
          inner[i] = (prep.toEnd[i] as number) >= d && has ? m : -C;
        }
        return revCummaxInPlace(inner);
      }
      default:
        throw new Error(`unknown op ${(n as { op: string }).op}`);
    }
  }
}

/** max over t1 >= t, for every t (in place). */
function revCummaxInPlace(x: Float64Array): Float64Array {
  let m = -Infinity;
  for (let t = x.length - 1; t >= 0; t--) {
    if ((x[t] as number) > m) m = x[t] as number;
    x[t] = m;
  }
  return x;
}

