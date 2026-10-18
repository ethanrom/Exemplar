// DSL AST: TypeScript mirror of engine/exemplar/contracts/dsl_ast.py.
//
// Field names and `op` discriminators are identical to the Python models, so a Rule serialised with
// pydantic `model_dump(mode="json")` (the `ast_json` column, api.yaml `Rule`) is a valid `Rule` here.
// Time bounds and durations are seconds (numbers); hour bounds are integers 0..23; a Hole (`?name`) may
// appear wherever a number may. A rule is *closed* when it has no holes.
//
// Nodes are plain data. Nothing in this package mutates a node, so subtrees may be shared freely.

import { CLAMP } from "./ontology.ts";
import type { SubType, VarType } from "./ontology.ts";

export interface Hole {
  readonly op: "hole";
  readonly name: string;
}
export type Bound = number | Hole;

export interface Atom {
  readonly op: "atom";
  readonly pred: string;
  /** Each arg is a bound variable name, a Zone literal, or an attr Label literal. */
  readonly args: readonly string[];
}
export interface Not {
  readonly op: "not";
  readonly arg: Phi;
}
export interface And {
  readonly op: "and";
  readonly args: readonly Phi[];
}
export interface Or {
  readonly op: "or";
  readonly args: readonly Phi[];
}
export interface Eventually {
  readonly op: "eventually";
  readonly a: Bound;
  readonly b: Bound;
  readonly arg: Phi;
}
export interface Always {
  readonly op: "always";
  readonly a: Bound;
  readonly b: Bound;
  readonly arg: Phi;
}
/** `left then[a, b] right`: `right` occurs within [a, b] s after `left`. */
export interface Then {
  readonly op: "then";
  readonly a: Bound;
  readonly b: Bound;
  readonly left: Phi;
  readonly right: Phi;
}
/** `holds_for >= d arg`: `arg` holds continuously for at least d s. */
export interface HoldsFor {
  readonly op: "holds_for";
  readonly d: Bound;
  readonly arg: Phi;
}
export type Phi = Atom | Not | And | Or | Eventually | Always | Then | HoldsFor;

/** Local hour in [h1, h2] (inclusive; h1 > h2 wraps past midnight, e.g. [22, 6]). */
export interface HourIn {
  readonly op: "hour_in";
  readonly h1: number | Hole;
  readonly h2: number | Hole;
}
export interface SubtypeEq {
  readonly op: "subtype_eq";
  readonly value: SubType;
}
export interface DeviceEq {
  readonly op: "device_eq";
  readonly value: string;
}
export type Ctx = HourIn | SubtypeEq | DeviceEq;

export interface VarDecl {
  readonly name: string;
  readonly type: VarType;
}

/** `exists v1:T1, ...: body [when ctx and ...]`. */
export interface Rule {
  readonly vars: readonly VarDecl[];
  readonly body: Phi;
  readonly when: readonly Ctx[];
}

/** Anything `toText` / `toEnglish` / the traversal helpers accept. */
export type Node = Phi | Ctx | Rule | VarDecl;

/** C = 0.5, the clamp: robustness always lies in [-C, C]. */
export const C = CLAMP;

export function isHole(x: unknown): x is Hole {
  return typeof x === "object" && x !== null && (x as { op?: unknown }).op === "hole";
}

export function isRule(n: Node): n is Rule {
  return "vars" in n;
}

export function isVarDecl(n: Node): n is VarDecl {
  return !("op" in n) && !("vars" in n);
}

/** Direct sub-nodes (a Rule's body then its context atoms), as `children()` in dsl_ast.py. */
export function children(node: Node): readonly Node[] {
  if (isRule(node)) return [node.body, ...node.when];
  if (isVarDecl(node)) return [];
  switch (node.op) {
    case "and":
    case "or":
      return node.args;
    case "then":
      return [node.left, node.right];
    case "not":
    case "eventually":
    case "always":
    case "holds_for":
      return [node.arg];
    default:
      return [];
  }
}

type BoundField = "a" | "b" | "d" | "h1" | "h2";

function boundFields(node: Node): readonly BoundField[] {
  if (isRule(node) || isVarDecl(node)) return [];
  switch (node.op) {
    case "eventually":
    case "always":
    case "then":
      return ["a", "b"];
    case "holds_for":
      return ["d"];
    case "hour_in":
      return ["h1", "h2"];
    default:
      return [];
  }
}

/** Hole names in first-occurrence order (pre-order, bounds before children). */
export function holesOf(node: Node): string[] {
  const out: string[] = [];
  const walk = (n: Node): void => {
    for (const f of boundFields(n)) {
      const v = (n as unknown as Record<string, unknown>)[f];
      if (isHole(v) && !out.includes(v.name)) out.push(v.name);
    }
    for (const c of children(n)) walk(c);
  };
  walk(node);
  return out;
}

/** AST nodes excluding bounds (used by MDL). */
export function nodeCount(node: Node): number {
  let n = 1;
  for (const c of children(node)) n += nodeCount(c);
  return n;
}

export function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}
