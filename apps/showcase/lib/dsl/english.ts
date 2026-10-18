// Deterministic English printer (`toEnglish`). Never an LLM: the UI shows exactly this text.
// Port of engine/exemplar/dsl/english.py; templates are tabulated in docs/DSL.md ("English templates").
// Scope is made explicit with parentheses: a phrase that extends to the right (`at some point within ..., X`,
// `X, and then within ... Y`, `it is not the case that X`) is parenthesised unless it is the last thing in the
// sentence.

import { isRule, isVarDecl, isHole } from "./ast.ts";
import type { Atom, Bound, Ctx, HourIn, Node, Phi, VarDecl } from "./ast.ts";
import { PREDICATES } from "./ontology.ts";
import { fmtNum } from "./util.ts";

// levels, loosest -> tightest (same idea as the DSL printer)
const OR = 0;
const AND = 1;
const THEN = 2;
const UNARY = 3;
const ATOM = 4;

const ZONE_PHRASE: ReadonlyMap<string, string> = new Map([
  ["door", "at the door"], ["porch", "on the porch"], ["steps", "on the steps"], ["yard", "in the yard"],
  ["driveway", "in the driveway"], ["sidewalk", "on the sidewalk"], ["street", "in the street"],
  ["dock", "at the dock"],
]);

// predicate -> [positive template, negative template]; {0} {1} are arguments, {z} the zone as "the porch",
// {zp} the zone as "on the porch", {label} an attr label with underscores replaced by spaces.
const ATOM_TEMPLATES: ReadonlyMap<string, readonly [string, string]> = new Map<string, readonly [string, string]>([
  ["present", ["{0} is present", "{0} is not present"]],
  ["in_zone", ["{0} is {zp}", "{0} is not {zp}"]],
  ["near", ["{0} is near {1}", "{0} is not near {1}"]],
  ["carrying", ["{0} is carrying {1}", "{0} is not carrying {1}"]],
  ["picks_up", ["{0} picks up {1}", "{0} does not pick up {1}"]],
  ["puts_down", ["{0} puts down {1}", "{0} does not put down {1}"]],
  ["rings_bell", ["{0} rings the doorbell", "{0} does not ring the doorbell"]],
  ["enters", ["{0} enters {z}", "{0} does not enter {z}"]],
  ["leaves", ["{0} leaves {z}", "{0} does not leave {z}"]],
  ["facing_camera", ["{0} faces the camera", "{0} does not face the camera"]],
  ["attr", ['{0} has the attribute "{label}"', '{0} does not have the attribute "{label}"']],
]);

const TYPE_WORDS: ReadonlyMap<string, readonly [string, string]> = new Map<string, readonly [string, string]>([
  ["Entity", ["an", "entity"]], ["Person", ["a", "person"]], ["Vehicle", ["a", "vehicle"]],
  ["Package", ["a", "package"]], ["Animal", ["an", "animal"]], ["Object", ["an", "object"]],
  ["Carryable", ["a", "package or object"]],
]);

function num(b: Bound): string {
  return isHole(b) ? "?" + b.name : fmtNum(b);
}

function fill(template: string, args: readonly string[], z: string, zp: string, label: string): string {
  return template.replace(/\{(0|1|z|zp|label)\}/g, (_m, k: string) => {
    if (k === "0") return args[0];
    if (k === "1") return args[1];
    if (k === "z") return z;
    if (k === "zp") return zp;
    return label;
  });
}

function atomText(a: Atom, negated: boolean): string {
  const tpl = ATOM_TEMPLATES.get(a.pred);
  const kinds = PREDICATES.get(a.pred);
  if (tpl === undefined || kinds === undefined || a.args.length !== kinds.length) {
    const text = `${a.pred}(${a.args.join(", ")})`; // unknown / malformed: show the raw atom
    return negated ? `not ${text}` : text;
  }
  const zone = a.args.length > 1 ? a.args[1] : "";
  return fill(tpl[negated ? 1 : 0], a.args, `the ${zone}`, ZONE_PHRASE.get(zone) ?? `in ${zone}`, zone.replaceAll("_", " "));
}

function windowText(a: Bound, b: Bound): string {
  return `within ${num(a)} to ${num(b)} s`;
}

// c returns [text, level, extendsRight]: extendsRight means the phrase runs to the end of the enclosing
// clause, so it needs parentheses unless it is the last thing in the sentence.
type Piece = readonly [string, number, boolean];

function c(n: Phi, tail: boolean): Piece {
  switch (n.op) {
    case "atom":
      return [atomText(n, false), ATOM, false];
    case "not": {
      const x = n.arg;
      if (x.op === "atom") return [atomText(x, true), ATOM, false];
      if (x.op === "eventually") {
        return [`at no point ${windowText(x.a, x.b)}, ${child(x.arg, UNARY, tail)}`, UNARY, true];
      }
      return [`it is not the case that ${child(x, UNARY, tail)}`, UNARY, true];
    }
    case "and":
      return [join(n.args, " and ", tail), AND, false];
    case "or":
      return [join(n.args, " or ", tail), OR, false];
    case "eventually":
      return [`at some point ${windowText(n.a, n.b)}, ${child(n.arg, UNARY, tail)}`, UNARY, true];
    case "always":
      return [`at every moment ${windowText(n.a, n.b)}, ${child(n.arg, UNARY, tail)}`, UNARY, true];
    case "then": {
      const left = child(n.left, UNARY, false);
      return [`${left}, and then ${windowText(n.a, n.b)} ${child(n.right, UNARY, tail)}`, THEN, true];
    }
    case "holds_for":
      return [`${child(n.arg, ATOM, false)} continuously for at least ${num(n.d)} s`, UNARY, false];
    default:
      throw new TypeError(`not a formula: ${JSON.stringify(n)}`);
  }
}

function child(n: Phi, minLevel: number, tail: boolean): string {
  const [text, level, extendsRight] = c(n, tail);
  if (level < minLevel || (extendsRight && !tail)) {
    return `(${tail ? text : c(n, true)[0]})`; // inside parentheses the scope is closed
  }
  return text;
}

function join(kids: readonly Phi[], sep: string, tail: boolean): string {
  const last = kids.length - 1;
  return kids.map((k, i) => child(k, UNARY, tail && i === last)).join(sep);
}

function hourText(h: HourIn): string {
  if (typeof h.h1 === "number" && typeof h.h2 === "number") {
    if (h.h1 <= h.h2) return `the local hour is between ${h.h1} and ${h.h2} inclusive`;
    return `the local hour is ${h.h1} or later, or ${h.h2} or earlier`;
  }
  return `the local hour is in [${num(h.h1)}, ${num(h.h2)}] (inclusive; wraps past midnight if the first is larger)`;
}

function ctxText(x: Ctx): string {
  switch (x.op) {
    case "hour_in":
      return hourText(x);
    case "subtype_eq":
      return `the event sub-type is ${x.value.replaceAll("_", " ")}`;
    case "device_eq":
      return `the device is ${x.value}`;
    default:
      throw new TypeError(`not a context atom: ${JSON.stringify(x)}`);
  }
}

function varText(v: VarDecl): string {
  const [art, word] = TYPE_WORDS.get(v.type) as readonly [string, string];
  return `${art} ${word} ${v.name}`;
}

function list(items: readonly string[]): string {
  return items.length === 1 ? items[0] : items.slice(0, -1).join(", ") + " and " + items[items.length - 1];
}

/**
 * Deterministic English for a `Rule` (a full sentence), a formula (a clause) or a context atom.
 *
 * Example: `exists p: Person, k: Package: picks_up(p, k) then[0, 20] leaves(p, porch)` ->
 * "There is a person p and a package k such that p picks up k, and then within 0 to 20 s p leaves the porch."
 * Holes print as `?name`; numbers with up to 3 decimals.
 */
export function toEnglish(node: Node): string {
  if (isRule(node)) {
    let s = `There is ${list(node.vars.map(varText))} such that ${c(node.body, true)[0]}`;
    if (node.when.length > 0) s += ", when " + node.when.map(ctxText).join(" and ");
    return s + ".";
  }
  if (isVarDecl(node)) return varText(node);
  if (node.op === "hour_in" || node.op === "subtype_eq" || node.op === "device_eq") return ctxText(node);
  return c(node, true)[0];
}
