// Z3 encoding of the DSL semantics (docs/DSL.md): the TypeScript port of engine/exemplar/synth/z3enc.py, on the
// z3-solver high-level API. It runs in a Web Worker (worker.ts) and in Node (the parity tests).
//
// For a sketch (a rule whose only free symbols are holes), labelled examples and a margin level m, `Encoder` builds per
// example
//
//     GE = "score(rule, clip) >= m"      LE = "score(rule, clip) <= -m"
//
// as Z3 formulas over the hole variables, by the engine's recursion (memoised on (node, relevant bindings), vectorised
// over frames). Every atom's robustness is a constant read from the evaluator's own signal index, so atoms fold to
// booleans and the formulas hold only window comparisons on the holes. The margin is a constant level, not a variable.
//
// Conventions that must match the evaluator (lib/dsl) exactly:
//   - integer-ms time: window membership is a <= (t_j - t_i)/1000 <= b; constant bounds are compared with the same
//     double expression the evaluator uses, hole bounds as exact rationals;
//   - an empty eventually / always window has robustness -C; then / holds_for search every start t1 >= t;
//     holds_for needs t1 + d <= t_end (the last frame);
//   - context atoms are crisp +-C and missing context is false; `exists` is OR over type-correct bindings for GE and
//     AND for LE; no bindings / no frames / failed perception give -C.
//
// Robustness constants are kept in millionths (integers), so the margin levels and the atom values compare exactly.

import type { Arith, Bool, Context, Model } from "z3-solver";
import { holesOf, isHole } from "../../dsl/ast.ts";
import type { Bound, Ctx, HourIn, Phi, Rule } from "../../dsl/index.ts";
import { ABSENT_VALUE, CLAMP, CONF_VALUE, THRESHOLD } from "../../dsl/ontology.ts";
import { ctxHolds, prepare } from "../../dsl/evaluator.ts";
import type { PreparedTrace } from "../../dsl/evaluator.ts";
import { typecheck } from "../../dsl/typecheck.ts";
import type { TraceContext } from "../../dsl/trace.ts";
import { exampleGeometry, holeKinds, lowerBoundHoles, windowsWithHoles } from "../classes.ts";
import type { HoleKind } from "../classes.ts";
import { SketchError } from "../types.ts";
import type { Example } from "../types.ts";
import { Fraction, ratOf } from "./rational.ts";
import { parseSexpr } from "./rational.ts";

export type Z3Ctx = Context<"main">;
type Bx = boolean | Bool<"main">;
type Ar = Arith<"main">;

const MICRO = 1_000_000;
const toMicro = (x: number): number => Math.round(x * MICRO);
const C_MICRO = toMicro(CLAMP);
const THRESHOLD_MICRO = toMicro(THRESHOLD);
const rhoConst = (s: number): number => toMicro(s) - THRESHOLD_MICRO;

/** z3enc.margin_levels(): the margins that can be optimal, ascending, in millionths (default ontology: 0.1 0.3 0.45 0.5). */
export function marginLevelsMicro(): number[] {
  const vals = new Set<number>([...Object.values(CONF_VALUE), ABSENT_VALUE].map((s) => Math.abs(rhoConst(s))));
  vals.add(C_MICRO);
  return [...vals].filter((v) => v > 0).sort((a, b) => a - b);
}

// ============================================================================ boolean helpers (folded)
/** Boolean connectives over JS booleans and Z3 terms: constants fold away and duplicates are dropped. */
export class Bld {
  private readonly neg = new Map<number, Bool<"main">>();
  readonly z: Z3Ctx;
  constructor(z: Z3Ctx) {
    this.z = z;
  }

  not(x: Bx): Bx {
    if (x === true) return false;
    if (x === false) return true;
    const key = x.ast as unknown as number;
    let r = this.neg.get(key);
    if (r === undefined) {
      r = this.z.Not(x);
      this.neg.set(key, r);
      this.neg.set(r.ast as unknown as number, x);
    }
    return r;
  }

  and(xs: readonly Bx[]): Bx {
    const out: Bool<"main">[] = [];
    const seen = new Set<number>();
    for (const x of xs) {
      if (x === true) continue;
      if (x === false) return false;
      const key = x.ast as unknown as number;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(x);
      }
    }
    if (out.length === 0) return true;
    return out.length === 1 ? (out[0] as Bool<"main">) : this.z.And(...out);
  }

  or(xs: readonly Bx[]): Bx {
    const out: Bool<"main">[] = [];
    const seen = new Set<number>();
    for (const x of xs) {
      if (x === false) continue;
      if (x === true) return true;
      const key = x.ast as unknown as number;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(x);
      }
    }
    if (out.length === 0) return false;
    return out.length === 1 ? (out[0] as Bool<"main">) : this.z.Or(...out);
  }

  implies(a: Bx, b: Bx): Bx {
    return this.or([this.not(a), b]);
  }
}

// ============================================================================ IR (hash-consed formula DAG)
type Bnd = number | string; // constant seconds, or the name of a hole

export interface Ir {
  readonly id: number;
  readonly op: Phi["op"];
  readonly pred: string;
  readonly args: readonly string[];
  readonly a: Bnd;
  readonly b: Bnd;
  readonly kids: readonly Ir[];
  /** Variables the node depends on, sorted. */
  readonly free: readonly string[];
}

const bnd = (x: Bound): Bnd => (isHole(x) ? x.name : x);

/** z3enc._Lowering: the rule body as a hash-consed DAG (equal subformulas share a node). */
export function lowerIr(body: Phi, varNames: readonly string[]): Ir {
  const vars = new Set(varNames);
  const table = new Map<string, Ir>();
  const mk = (op: Phi["op"], pred: string, args: readonly string[], a: Bnd, b: Bnd, kids: readonly Ir[]): Ir => {
    const key = JSON.stringify([op, pred, args, a, b, kids.map((k) => k.id)]);
    let n = table.get(key);
    if (n === undefined) {
      const free = new Set<string>(args.filter((x) => vars.has(x)));
      for (const k of kids) for (const v of k.free) free.add(v);
      n = { id: table.size, op, pred, args, a, b, kids, free: [...free].sort() };
      table.set(key, n);
    }
    return n;
  };
  const lower = (node: Phi): Ir => {
    switch (node.op) {
      case "atom":
        return mk("atom", node.pred, node.args, 0, 0, []);
      case "not":
        return mk("not", "", [], 0, 0, [lower(node.arg)]);
      case "and":
      case "or":
        return mk(node.op, "", [], 0, 0, node.args.map(lower));
      case "eventually":
      case "always":
        return mk(node.op, "", [], bnd(node.a), bnd(node.b), [lower(node.arg)]);
      case "then":
        return mk("then", "", [], bnd(node.a), bnd(node.b), [lower(node.left), lower(node.right)]);
      case "holds_for":
        return mk("holds_for", "", [], bnd(node.d), 0, [lower(node.arg)]);
      default:
        throw new SketchError(`not a formula: ${JSON.stringify(node)}`);
    }
  };
  return lower(body);
}

// ============================================================================ the encoder
/** One Z3 context, the hole variables and the per-example formulas of one sketch at one margin level. */
export class Encoder {
  readonly sketch: Rule;
  readonly examples: readonly Example[];
  readonly marginMicro: number;
  readonly z: Z3Ctx;
  readonly B: Bld;
  readonly preps: PreparedTrace[];
  readonly holeNames: string[];
  readonly kinds: Map<string, HoleKind>;
  readonly lowerHoles: Set<string>;
  readonly varNames: string[];
  readonly varTypes: string[];
  readonly ir: Ir;
  readonly clipLenMs: number;
  readonly hv = new Map<string, Ar>();
  readonly domain: Bool<"main">[];
  private readonly rvCache = new Map<string, Ar>();
  private readonly waCache = new Map<string, Bx>();
  /** Window cells shared across examples: (a, b, diff_ms) -> a <= diff/1000 <= b over the holes. */
  readonly cellCache = new Map<string, Bx>();
  readonly neCache = new Map<string, Bx>();
  private readonly formulas = new Map<number, [Bx, Bx]>();
  private readonly exEnc = new Map<number, ExampleEncoder>();

  /** `marginMicro`: the margin level in millionths. `z` is the (shared) Z3 context. */
  constructor(z: Z3Ctx, sketch: Rule, examples: readonly Example[], marginMicro: number) {
    const errs = typecheck(sketch);
    if (errs.length > 0) throw new SketchError("sketch does not typecheck: " + errs.join("; "));
    if (!(marginMicro >= 0 && marginMicro <= C_MICRO)) throw new RangeError(`margin must lie in [0, ${CLAMP}], got ${marginMicro / MICRO}`);
    this.z = z;
    this.B = new Bld(z);
    this.sketch = sketch;
    this.examples = examples;
    this.marginMicro = marginMicro;
    this.preps = examples.map((e) => prepare(e.trace));
    this.holeNames = holesOf(sketch);
    this.kinds = holeKinds(sketch);
    this.lowerHoles = lowerBoundHoles(sketch);
    this.varNames = sketch.vars.map((v) => v.name);
    this.varTypes = sketch.vars.map((v) => v.type);
    this.ir = lowerIr(sketch.body, this.varNames);
    this.clipLenMs = exampleGeometry(this.preps).lengthMs; // holes live in [0, longest clip]
    for (const h of this.holeNames) {
      this.hv.set(h, this.kindOf(h) === "hour" ? z.Int.const(`h_${h}`) : z.Real.const(`h_${h}`));
    }
    this.domain = this.buildDomain();
  }

  kindOf(h: string): HoleKind {
    return this.kinds.get(h) ?? "time";
  }

  hole(h: string): Ar {
    return this.hv.get(h) as Ar;
  }

  /** The Z3 real numeral of an exact fraction. */
  rv(x: Fraction): Ar {
    const key = x.toString();
    let r = this.rvCache.get(key);
    if (r === undefined) {
      r = this.z.Real.val(key);
      this.rvCache.set(key, r);
    }
    return r;
  }

  /** A constant robustness `c` (millionths) satisfies rho >= m. */
  geConst(c: number): boolean {
    return c >= this.marginMicro;
  }
  /** A constant robustness `c` (millionths) satisfies rho <= -m. */
  leConst(c: number): boolean {
    return c <= -this.marginMicro;
  }

  private buildDomain(): Bool<"main">[] {
    const d: Bool<"main">[] = [];
    const L = this.rv(new Fraction(BigInt(this.clipLenMs), 1000n));
    const zero = this.rv(Fraction.of(0));
    for (const h of this.holeNames) {
      const v = this.hole(h);
      if (this.kindOf(h) === "hour") d.push(v.ge(0), v.le(23));
      else d.push(v.ge(zero), v.le(L));
    }
    for (const [a, b] of windowsWithHoles(this.sketch)) {
      const lo = isHole(a) ? this.hole(a.name) : this.rv(ratOf(a));
      const hi = isHole(b) ? this.hole(b.name) : this.rv(ratOf(b));
      d.push(lo.le(hi));
    }
    return d;
  }

  // ------------------------------------------------------------------ window atoms
  /** a <= diff_ms / 1000. */
  lowerOk(a: Bnd, diffMs: number): Bx {
    if (typeof a === "string") {
      if (diffMs < 0) return false;
      const key = `lo|${a}|${diffMs}`;
      let x = this.waCache.get(key);
      if (x === undefined) {
        x = this.hole(a).le(this.rv(new Fraction(BigInt(diffMs), 1000n)));
        this.waCache.set(key, x);
      }
      return x;
    }
    return a <= diffMs / 1000;
  }

  /** diff_ms / 1000 <= b. */
  upperOk(b: Bnd, diffMs: number): Bx {
    if (typeof b === "string") {
      if (diffMs <= 0) return true;
      const key = `hi|${b}|${diffMs}`;
      let x = this.waCache.get(key);
      if (x === undefined) {
        x = this.hole(b).ge(this.rv(new Fraction(BigInt(diffMs), 1000n)));
        this.waCache.set(key, x);
      }
      return x;
    }
    return diffMs / 1000 <= b;
  }

  // ------------------------------------------------------------------ per-example formulas
  exampleEncoder(k: number): ExampleEncoder {
    let e = this.exEnc.get(k);
    if (e === undefined) {
      e = new ExampleEncoder(this, this.preps[k] as PreparedTrace);
      this.exEnc.set(k, e);
    }
    return e;
  }

  /** (GE, LE) of example k: score >= m and score <= -m. */
  top(k: number): [Bx, Bx] {
    let f = this.formulas.get(k);
    if (f === undefined) {
      f = this.exampleEncoder(k).top();
      this.formulas.set(k, f);
    }
    return f;
  }

  /** The constraint example k must satisfy: GE for a positive, LE for a negative. */
  goal(k: number): Bx {
    const [ge, le] = this.top(k);
    return (this.examples[k] as Example).positive ? ge : le;
  }

  // ------------------------------------------------------------------ model read-back
  readHoles(model: Model<"main">): Record<string, number> {
    const out: Record<string, number> = {};
    for (const h of this.holeNames) out[h] = parseSexpr(model.eval(this.hole(h), true).toString()).toNumber();
    return out;
  }

  isTrue(model: Model<"main">, g: Bx): boolean {
    if (g === true || g === false) return g;
    return model.eval(g, true).toString() === "true";
  }

  contextExpr(ctxs: readonly Ctx[], context: TraceContext | undefined): Bx {
    const out: Bx[] = [];
    for (const c of ctxs) {
      if (c.op === "hour_in" && (isHole(c.h1) || isHole(c.h2))) out.push(this.hourExpr(c, context?.local_hour ?? null));
      else out.push(ctxHolds(c, context));
    }
    return this.B.and(out);
  }

  private hourExpr(c: HourIn, hour: number | null): Bx {
    if (hour === null) return false;
    const z = this.z;
    const h1 = isHole(c.h1) ? this.hole(c.h1.name) : z.Int.val(c.h1);
    const h2 = isHole(c.h2) ? this.hole(c.h2.name) : z.Int.val(c.h2);
    return z.Or(
      z.And(h1.le(h2), h1.le(hour), h2.ge(hour)),
      z.And(h1.gt(h2), z.Or(h1.le(hour), h2.ge(hour))),
    );
  }
}

type Win = (i: number, j: number) => Bx;

/** GE / LE of one example: the recursion over the formula, memoised on (node, relevant bindings). */
export class ExampleEncoder {
  private readonly enc: Encoder;
  private readonly prep: PreparedTrace;
  private readonly T: number;
  private readonly B: Bld;
  private readonly memo = new Map<string, [Bx[], Bx[]]>();
  private readonly wins = new Map<string, Win>();
  private readonly nes = new Map<string, Bx[]>();
  private readonly dms: number[][];

  constructor(enc: Encoder, prep: PreparedTrace) {
    this.enc = enc;
    this.prep = prep;
    this.T = prep.T;
    this.B = enc.B;
    const t = prep.tMs;
    this.dms = Array.from({ length: this.T }, (_, i) => Array.from({ length: this.T }, (_, j) => (t[j] as number) - (t[i] as number)));
  }

  private static wkey(a: Bnd, b: Bnd): string {
    return `${typeof a === "string" ? "h" : "c"}${a}|${typeof b === "string" ? "h" : "c"}${b}`;
  }

  /** W(i, j) = a <= (t_j - t_i)/1000 <= b (constant windows are the evaluator's own mask). */
  private window(a: Bnd, b: Bnd): Win {
    const key = ExampleEncoder.wkey(a, b);
    let W = this.wins.get(key);
    if (W === undefined) {
      const T = this.T;
      if (typeof a !== "string" && typeof b !== "string") {
        const D = this.prep.D;
        W = (i, j) => {
          const d = D[i * T + j] as number;
          return a <= d && d <= b;
        };
      } else {
        const enc = this.enc;
        const cache = new Map<number, Bx>();
        W = (i, j) => {
          const k = i * T + j;
          let x = cache.get(k);
          if (x === undefined) {
            const dm = (this.dms[i] as number[])[j] as number;
            const ck = `${key}|${dm}`;
            x = enc.cellCache.get(ck);
            if (x === undefined) {
              x = this.B.and([enc.lowerOk(a, dm), enc.upperOk(b, dm)]);
              enc.cellCache.set(ck, x);
            }
            cache.set(k, x);
          }
          return x;
        };
      }
      this.wins.set(key, W);
    }
    return W;
  }

  private nonempty(a: Bnd, b: Bnd): Bx[] {
    const key = ExampleEncoder.wkey(a, b);
    let ne = this.nes.get(key);
    if (ne === undefined) {
      const W = this.window(a, b);
      const enc = this.enc;
      const T = this.T;
      const hole = typeof a === "string" || typeof b === "string";
      ne = [];
      for (let i = 0; i < T; i++) {
        if (W(i, i) === true) {
          // t_i itself is in the window
          ne.push(true);
          continue;
        }
        const rk = hole ? `${key}|${(this.dms[i] as number[]).join(",")}` : null;
        let x = rk !== null ? enc.neCache.get(rk) : undefined;
        if (x === undefined) {
          x = this.B.or(Array.from({ length: T }, (_, j) => W(i, j)));
          if (rk !== null) enc.neCache.set(rk, x);
        }
        ne.push(x);
      }
      this.nes.set(key, ne);
    }
    return ne;
  }

  private vec(n: Ir, bind: ReadonlyMap<string, string>): [Bx[], Bx[]] {
    const key = `${n.id}|${n.free.map((v) => bind.get(v)).join(",")}`;
    let r = this.memo.get(key);
    if (r === undefined) {
      r = this.vecOf(n, bind);
      this.memo.set(key, r);
    }
    return r;
  }

  private vecOf(n: Ir, bind: ReadonlyMap<string, string>): [Bx[], Bx[]] {
    const enc = this.enc;
    const T = this.T;
    const B = this.B;
    const op = n.op;
    const R = [...Array(T).keys()];
    const kid = (i: number): [Bx[], Bx[]] => this.vec(n.kids[i] as Ir, bind);
    if (op === "atom") {
      const sig = this.prep.signal(n.pred, n.args.map((x) => bind.get(x) ?? x));
      const cs = Array.from(sig, (s) => rhoConst(s));
      return [cs.map((c) => enc.geConst(c)), cs.map((c) => enc.leConst(c))];
    }
    if (op === "not") {
      const [ge, le] = kid(0);
      return [le, ge];
    }
    if (op === "and" || op === "or") {
      const vs = n.kids.map((_, i) => kid(i));
      if (op === "and") return [R.map((i) => B.and(vs.map((v) => v[0][i] as Bx))), R.map((i) => B.or(vs.map((v) => v[1][i] as Bx)))];
      return [R.map((i) => B.or(vs.map((v) => v[0][i] as Bx))), R.map((i) => B.and(vs.map((v) => v[1][i] as Bx)))];
    }
    if (op === "eventually" || op === "always") {
      const [gc, lc] = kid(0);
      const W = this.window(n.a, n.b);
      const gj = R.filter((j) => gc[j] !== false); // frames that can witness GE
      const lj = R.filter((j) => lc[j] !== true); // frames that can break LE
      if (op === "eventually") {
        return [
          R.map((i) => B.or(gj.map((j) => B.and([W(i, j), gc[j] as Bx])))),
          R.map((i) => B.and(lj.map((j) => B.implies(W(i, j), lc[j] as Bx)))),
        ];
      }
      const ne = this.nonempty(n.a, n.b);
      const gt = R.filter((j) => gc[j] !== true);
      const lf = R.filter((j) => lc[j] !== false);
      return [
        R.map((i) => B.and([ne[i] as Bx, ...gt.map((j) => B.implies(W(i, j), gc[j] as Bx))])),
        R.map((i) => B.or([B.not(ne[i] as Bx), ...lf.map((j) => B.and([W(i, j), lc[j] as Bx]))])),
      ];
    }
    if (op === "then") {
      const [gx, lx] = kid(0);
      const [gy, ly] = kid(1);
      const W = this.window(n.a, n.b);
      const gj = R.filter((j) => gy[j] !== false);
      const lj = R.filter((j) => ly[j] !== true);
      const gi = R.map((i) => (gx[i] !== false ? B.and([gx[i] as Bx, B.or(gj.map((j) => B.and([W(i, j), gy[j] as Bx])))]) : false));
      const li = R.map((i) => (lx[i] === true ? true : B.or([lx[i] as Bx, B.and(lj.map((j) => B.implies(W(i, j), ly[j] as Bx)))])));
      return [this.suffix(gi, "or"), this.suffix(li, "and")];
    }
    if (op === "holds_for") {
      const [gc, lc] = kid(0);
      const d = n.a;
      const W = this.window(0.0, d);
      const ne = this.nonempty(0.0, d);
      const tMs = this.prep.tMs;
      const endMs = tMs[T - 1] as number;
      const gt = R.filter((j) => gc[j] !== true);
      const lf = R.filter((j) => lc[j] !== false);
      const gi: Bx[] = [];
      const li: Bx[] = [];
      for (const i of R) {
        const fits: Bx = typeof d === "string" ? enc.lowerOk(d, endMs - (tMs[i] as number)) : (this.prep.toEnd[i] as number) >= d; // d <= (t_end - t_i)/1000
        const valid = B.and([fits, ne[i] as Bx]);
        gi.push(valid !== false ? B.and([valid, ...gt.map((j) => B.implies(W(i, j), gc[j] as Bx))]) : false);
        li.push(B.or([B.not(valid), ...lf.map((j) => B.and([W(i, j), lc[j] as Bx]))]));
      }
      return [this.suffix(gi, "or"), this.suffix(li, "and")];
    }
    throw new SketchError(`unsupported node ${op}`);
  }

  /** out[i] = combine over i1 >= i of xs[i1] (the search over every later start). */
  private suffix(xs: readonly Bx[], comb: "and" | "or"): Bx[] {
    const out = new Array<Bx>(this.T);
    let acc: Bx = comb === "and";
    for (let i = this.T - 1; i >= 0; i--) {
      acc = this.B[comb]([xs[i] as Bx, acc]);
      out[i] = acc;
    }
    return out;
  }

  top(): [Bx, Bx] {
    const enc = this.enc;
    const prep = this.prep;
    const B = this.B;
    if (!prep.ok) return [false, true]; // score = -C
    const bindings = prep.bindings(enc.varTypes);
    if (bindings.length === 0) return [false, true];
    const ok = enc.contextExpr(enc.sketch.when, prep.trace.context);
    if (ok === false) return [false, true];
    const geT: Bx[] = [];
    const leT: Bx[] = [];
    for (const b of bindings) {
      const bind = new Map(enc.varNames.map((v, i) => [v, b[i] as string] as const));
      const [ge, le] = this.vec(enc.ir, bind);
      geT.push(B.or(ge));
      leT.push(B.and(le));
    }
    return [B.and([ok, B.or(geT)]), B.or([B.not(ok), B.and(leT)])];
  }
}

