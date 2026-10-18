// Port of engine/exemplar/dsl/util.py plus fill_holes from contracts/dsl_ast.py:
// number formatting, AST normalisation, hole handling.

import { hasOwn, isHole, isRule, holesOf } from "./ast.ts";
import type { Bound, Ctx, Hole, Node, Phi, Rule } from "./ast.ts";
import { UnboundHoleError } from "./errors.ts";
import { formatFixed3, intString, pyFloatRepr, pyRound } from "./pycompat.ts";

/** A mapping from hole name to value (seconds; hours are rounded to an int when filled). */
export type HoleValues = Readonly<Record<string, number>>;

/**
 * Canonical number text. Integers print without `.0`; others with up to 3 decimals.
 *
 * `exact = true` (used by the DSL printer) falls back to the shortest round-trip repr when 3 decimals would
 * change the value, so `parse(toText(r))` equals `r` for every rule.
 */
export function fmtNum(x: number, exact = false): string {
  if (!Number.isFinite(x)) return pyFloatRepr(x);
  if (Number.isInteger(x)) return intString(x);
  let s = formatFixed3(x).replace(/0+$/, "").replace(/\.+$/, "");
  if (exact && Number(s) !== x) s = pyFloatRepr(x);
  return s;
}

/** Text of a bound: `?name` for a hole, the exact number text otherwise (printer.bound_text). */
export function boundText(b: Bound): string {
  return isHole(b) ? "?" + b.name : fmtNum(b, true);
}

/** Flatten nested `and` / `or` into n-ary nodes (what the parser always produces). */
export function normalize<T extends Node>(node: T): T;
export function normalize(node: Node): Node {
  if (isRule(node)) return { ...node, body: normalize(node.body) as Phi };
  if (!("op" in node)) return node;
  switch (node.op) {
    case "and":
    case "or": {
      const flat: Phi[] = [];
      for (const raw of node.args) {
        const c = normalize(raw) as Phi;
        if (c.op === node.op) flat.push(...(c as { args: readonly Phi[] }).args);
        else flat.push(c);
      }
      return { op: node.op, args: flat } as Phi;
    }
    case "not":
      return { op: "not", arg: normalize(node.arg) as Phi };
    case "eventually":
    case "always":
      return { op: node.op, a: node.a, b: node.b, arg: normalize(node.arg) as Phi };
    case "holds_for":
      return { op: "holds_for", d: node.d, arg: normalize(node.arg) as Phi };
    case "then":
      return {
        op: "then", a: node.a, b: node.b, left: normalize(node.left) as Phi, right: normalize(node.right) as Phi,
      };
    default:
      return node;
  }
}

/** Numeric value of a bound; looks a hole up in `values` (hours round like `fillHoles`: half to even). */
export function boundValue(b: Bound, values: HoleValues | null | undefined, hour = false): number {
  if (isHole(b)) {
    if (values == null || !hasOwn(values, b.name)) throw new UnboundHoleError([b.name]);
    const x = values[b.name];
    return hour ? pyRound(x) : Number(x);
  }
  return b;
}

/**
 * Substitute hole values (seconds; hours are rounded to int, half to even). Unknown holes are left in
 * place. Returns the same object when nothing changed.
 */
export function fillHoles<T extends Node>(node: T, values: HoleValues): T;
export function fillHoles(node: Node, values: HoleValues): Node {
  const fillBound = (b: Bound, hour: boolean): Bound => {
    if (isHole(b) && hasOwn(values, b.name)) return hour ? pyRound(values[b.name]) : Number(values[b.name]);
    return b;
  };
  if (isRule(node)) {
    return { ...node, body: fillHoles(node.body, values), when: node.when.map((c) => fillHoles(c, values)) as Ctx[] };
  }
  if (!("op" in node)) return node;
  switch (node.op) {
    case "and":
    case "or":
      return { op: node.op, args: node.args.map((c) => fillHoles(c, values)) } as Phi;
    case "not":
      return { op: "not", arg: fillHoles(node.arg, values) };
    case "eventually":
    case "always":
      return { op: node.op, a: fillBound(node.a, false), b: fillBound(node.b, false), arg: fillHoles(node.arg, values) };
    case "then":
      return {
        op: "then", a: fillBound(node.a, false), b: fillBound(node.b, false),
        left: fillHoles(node.left, values), right: fillHoles(node.right, values),
      };
    case "holds_for":
      return { op: "holds_for", d: fillBound(node.d, false), arg: fillHoles(node.arg, values) };
    case "hour_in":
      return { op: "hour_in", h1: fillBound(node.h1, true) as number | Hole, h2: fillBound(node.h2, true) as number | Hole };
    default:
      return node;
  }
}

/** `fillHoles` if values are given (and non-empty), then require the rule to be closed. */
export function resolveHoles(rule: Rule, values: HoleValues | null | undefined): Rule {
  let r = rule;
  if (values != null && Object.keys(values).length > 0) r = fillHoles(r, values);
  const left = holesOf(r);
  if (left.length > 0) throw new UnboundHoleError(left);
  return r;
}
