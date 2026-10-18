// Witness extraction: why a rule scored what it did (api.yaml `Witness`). Port of engine/exemplar/dsl/witness.py.
//
// Deterministic: ties go to the first binding (in `bindings` order) and the earliest frame.
//
// Result (api.yaml `Witness` minus `rule_id` / `tau` / `margin`, which the monitor adds):
//
//   { clip_id, score, bindings: {var: entity_id}, entities: [Entity], spans: [Span...], english }
//
// `spans` is pre-order. It covers the nodes the argmax descends through: every temporal node (eventually /
// always / then / holds_for), every atom reached (the evidence facts), every `not` reached (a point span at the
// evaluation time, with the positive robustness of the absence; the descent stops there), and the body root
// when it is an and / or (the hull of every span beneath it).
//
// Times per op: atom, not -> the frame (a point); eventually / always -> the window the evaluator used,
// [t + a, t + b] clipped to the last frame's time, then descending into the argmax frame (eventually) or the
// weakest frame (always) as an atom point; then -> from the chosen t1 to the chosen t2; holds_for -> the window
// it required, [t1, t1 + d] clipped to the last frame's time, descending into the weakest frame; or -> descends
// into the best branch; and -> descends into all branches. A window span reports the interval the rule asked
// about (`holds_for >= 15` from t1 reads t1 .. t1 + 15 s), not the last sampled frame in it.

import { C } from "./ast.ts";
import type { Rule } from "./ast.ts";
import { toEnglish } from "./english.ts";
import { CompiledRule, ctxValue, prepare } from "./evaluator.ts";
import type { PNode, PreparedTrace, TraceCache } from "./evaluator.ts";
import { pyRound } from "./pycompat.ts";
import { toText } from "./printer.ts";
import type { Trace } from "./trace.ts";
import { resolveHoles } from "./util.ts";
import type { HoleValues } from "./util.ts";

export interface WitnessSpan {
  /** AST path: `body`, `body.left`, `body.args[1]`, `body.arg`. */
  path: string;
  op: string;
  /** DSL text of that subformula. */
  text: string;
  t_start_ms: number;
  t_end_ms: number;
  /** Robustness of the subformula at the chosen frame. */
  rho: number;
}

export interface WitnessEntity {
  id: string;
  type: string;
  attrs: string[];
}

export interface Witness {
  clip_id: string;
  score: number;
  bindings: Record<string, string>;
  entities: WitnessEntity[];
  spans: WitnessSpan[];
  english: string;
}

/**
 * Witness for `rule` on `trace` (the argmax binding and the times behind the score).
 *
 * Works for non-matching clips too (the witness then shows the closest the rule got). With no bindings or a
 * failed trace: score -C, empty bindings and spans.
 */
export function witness(rule: Rule, trace: Trace | PreparedTrace, holes?: HoleValues | null): Witness {
  const closed = resolveHoles(rule, holes);
  const prep = prepare(trace);
  const tr = prep.trace;
  const out: Witness = {
    clip_id: tr.clip_id, score: -C, bindings: {}, entities: [], spans: [], english: toEnglish(closed),
  };
  const cr = new CompiledRule(closed);
  const am = cr.argmax(prep, null); // first binding, then earliest frame
  if (am === null) return out;
  const ctx = ctxValue(cr.when, tr.context);
  out.score = am.value < ctx ? am.value : ctx;
  const chosen = prep.bindings(cr.types)[am.binding];
  cr.names.forEach((n, i) => {
    out.bindings[n] = chosen[i];
  });
  for (const e of chosen) {
    const ent = tr.entities.find((x) => x.id === e);
    if (ent !== undefined) out.entities.push({ id: ent.id, type: ent.type, attrs: [...(ent.attrs ?? [])] });
  }

  const tc = cr.evalBinding(prep, am.binding, null);
  const root = cr.plan[cr.plan.length - 1];
  const spans: WitnessSpan[] = [];
  explain(root, am.frame, "body", tc, prep, spans);
  if (root.op === "and" || root.op === "or") {
    // root span covers everything its evidence touches
    const top = span("body", root, am.frame, am.frame, tc.buf[root.id][am.frame], prep);
    top.t_start_ms = Math.min(...spans.map((s) => s.t_start_ms));
    top.t_end_ms = Math.max(...spans.map((s) => s.t_end_ms));
    spans.unshift(top);
  }
  out.spans = spans;
  return out;
}

function span(path: string, n: PNode, i: number, j: number, rho: number, prep: PreparedTrace): WitnessSpan {
  return { path, op: n.op, text: toText(n.node), t_start_ms: prep.tMs[i], t_end_ms: prep.tMs[j], rho };
}

/** Span for a windowed operator at frame `i`: [t_i + a, t_i + b] in ms, clipped to the last frame's time. */
function windowSpan(path: string, n: PNode, i: number, a: number, b: number, rho: number, prep: PreparedTrace): WitnessSpan {
  const t0 = prep.tMs[i];
  const tEnd = prep.tMs[prep.T - 1];
  return {
    path, op: n.op, text: toText(n.node),
    t_start_ms: Math.min(t0 + pyRound(a * 1000), tEnd),
    t_end_ms: Math.min(t0 + pyRound(b * 1000), tEnd),
    rho,
  };
}

/** Earliest frame t1 >= t whose inner value attains `v` (the max over t1 >= t). */
function firstAtOrAfter(inner: Float64Array, t: number, v: number): number {
  let argmax = t;
  for (let k = t; k < inner.length; k++) {
    if (inner[k] === v) return k;
    if (inner[k] > inner[argmax]) argmax = k;
  }
  return argmax;
}

/** The first frame in [lo, hi] with the largest (or smallest) value of `series`. */
function argExtreme(series: Float64Array, lo: number, hi: number, max: boolean): number {
  let bestJ = lo;
  let bestV = series[lo];
  for (let j = lo + 1; j <= hi; j++) {
    const v = series[j];
    if (max ? v > bestV : v < bestV) {
      bestV = v;
      bestJ = j;
    }
  }
  return bestJ;
}

/** Append spans for node `n` evaluated at frame index `t` and recurse into its evidence. */
function explain(n: PNode, t: number, path: string, tc: TraceCache, prep: PreparedTrace, spans: WitnessSpan[]): void {
  const series = (k: PNode): Float64Array => tc.buf[k.id];
  const v = series(n)[t];
  switch (n.op) {
    case "atom":
    case "not":
      spans.push(span(path, n, t, t, v, prep));
      return;
    case "and":
      n.kids.forEach((k, i) => explain(k, t, `${path}.args[${i}]`, tc, prep, spans));
      return;
    case "or": {
      let j = 0;
      let bestV = series(n.kids[0])[t];
      for (let i = 1; i < n.kids.length; i++) {
        const x = series(n.kids[i])[t];
        if (x > bestV) {
          bestV = x;
          j = i;
        }
      }
      explain(n.kids[j], t, `${path}.args[${j}]`, tc, prep, spans);
      return;
    }
    case "eventually":
    case "always": {
      const lo = (tc.lo[n.id] as Int32Array)[t];
      const hi = (tc.hi[n.id] as Int32Array)[t];
      if (lo > hi) {
        spans.push(span(path, n, t, t, v, prep)); // empty window: nothing to point at
        return;
      }
      const j = argExtreme(series(n.kids[0]), lo, hi, n.op === "eventually");
      spans.push(windowSpan(path, n, t, tc.av[n.id], tc.bv[n.id], v, prep)); // the window searched; the evidence atom is a point
      explain(n.kids[0], j, `${path}.arg`, tc, prep, spans);
      return;
    }
    case "then": {
      const t1 = firstAtOrAfter(tc.inner[n.id] as Float64Array, t, v);
      const lo = (tc.lo[n.id] as Int32Array)[t1];
      const hi = (tc.hi[n.id] as Int32Array)[t1];
      if (lo > hi) {
        spans.push(span(path, n, t1, t1, v, prep));
        explain(n.kids[0], t1, `${path}.left`, tc, prep, spans);
        return;
      }
      const t2 = argExtreme(series(n.kids[1]), lo, hi, true);
      spans.push(span(path, n, t1, t2, v, prep));
      explain(n.kids[0], t1, `${path}.left`, tc, prep, spans);
      explain(n.kids[1], t2, `${path}.right`, tc, prep, spans);
      return;
    }
    case "holds_for": {
      const t1 = firstAtOrAfter(tc.inner[n.id] as Float64Array, t, v);
      const lo = (tc.lo[n.id] as Int32Array)[t1];
      const hi = (tc.hi[n.id] as Int32Array)[t1];
      if (lo > hi) {
        spans.push(span(path, n, t1, t1, v, prep));
        return;
      }
      const j = argExtreme(series(n.kids[0]), lo, hi, false); // weakest frame of the run
      spans.push(windowSpan(path, n, t1, 0.0, tc.av[n.id], v, prep)); // [t1, t1 + d], the run the rule required
      explain(n.kids[0], j, `${path}.arg`, tc, prep, spans);
      return;
    }
    default:
      throw new Error(`unknown op ${(n as { op: string }).op}`);
  }
}
