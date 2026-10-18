// Canonical DSL text printer (`toText`): minimal parentheses by precedence, parseable by `parse`.
// Port of engine/exemplar/dsl/printer.py.

import { isRule, isVarDecl } from "./ast.ts";
import type { Ctx, Node, Phi } from "./ast.ts";
import { boundText } from "./util.ts";

// Precedence, loosest -> tightest. A child printed in a context of higher level gets parentheses.
const OR = 0;
const AND = 1;
const THEN = 2;
const UNARY = 3;
const ATOM = 4;

function level(node: Phi): number {
  switch (node.op) {
    case "or":
      return OR;
    case "and":
      return AND;
    case "then":
      return THEN;
    case "not":
    case "eventually":
    case "always":
    case "holds_for":
      return UNARY;
    default:
      return ATOM;
  }
}

function wrap(node: Phi, ctxLevel: number): string {
  const s = phi(node);
  return level(node) < ctxLevel ? `(${s})` : s;
}

function phi(node: Phi): string {
  switch (node.op) {
    case "atom":
      return `${node.pred}(${node.args.join(", ")})`;
    case "not":
      return `not ${wrap(node.arg, UNARY)}`;
    case "and":
      return node.args.map((c) => wrap(c, THEN)).join(" and ");
    case "or":
      return node.args.map((c) => wrap(c, AND)).join(" or ");
    case "eventually":
    case "always":
      return `${node.op}[${boundText(node.a)}, ${boundText(node.b)}] ${wrap(node.arg, UNARY)}`;
    case "then":
      return `${wrap(node.left, THEN)} then[${boundText(node.a)}, ${boundText(node.b)}] ${wrap(node.right, UNARY)}`;
    case "holds_for":
      return `holds_for >= ${boundText(node.d)} ${wrap(node.arg, UNARY)}`;
    default:
      throw new TypeError(`not a formula: ${JSON.stringify(node)}`);
  }
}

function ctx(node: Ctx): string {
  switch (node.op) {
    case "hour_in":
      return `hour in [${boundText(node.h1)}, ${boundText(node.h2)}]`;
    case "subtype_eq":
      return `subtype = ${node.value}`;
    case "device_eq":
      return `device = ${node.value}`;
    default:
      throw new TypeError(`not a context atom: ${JSON.stringify(node)}`);
  }
}

/**
 * Canonical DSL text of a `Rule`, a formula node, a context atom or a `VarDecl`.
 *
 * For every well-typed rule in normal form (nested and/or flattened, which is all the parser produces),
 * `parse(toText(r))` equals `r`; use `normalize` first for hand-built nested trees.
 */
export function toText(node: Node): string {
  if (isRule(node)) {
    let s = "exists " + node.vars.map((v) => `${v.name}: ${v.type}`).join(", ") + ": " + phi(node.body);
    if (node.when.length > 0) s += " when " + node.when.map(ctx).join(" and ");
    return s;
  }
  if (isVarDecl(node)) return `${node.name}: ${node.type}`;
  if (node.op === "hour_in" || node.op === "subtype_eq" || node.op === "device_eq") return ctx(node);
  return phi(node);
}
