// Minimum-description-length score used to rank candidate rules (engine/exemplar/synth/mdl.py).
//
//   mdl = nodes * log2(|ops|) + 8 * #parameters + lambda * violations      (bits; lower is better)
//
// |ops| = 7 formula operators + the 11 ontology predicates + 3 context atoms = 21, so every AST node costs
// log2(21) ~ 4.39 bits. A sketch is charged for its distinct holes, a closed rule for its numeric bound slots.

import type { Node, Rule } from "../dsl/index.ts";
import { children, holesOf, nodeCount } from "../dsl/ast.ts";
import { PREDICATES } from "../dsl/ontology.ts";

export const OPS_ALPHABET = 7 + PREDICATES.size + 3;
export const BITS_PER_NODE = Math.log2(OPS_ALPHABET);
export const BITS_PER_HOLE = 8.0;

/** Number of numeric bound slots (window bounds, durations, hours) in a closed rule. */
function numericSlots(node: Node): number {
  let n = 0;
  if ("op" in node) {
    if (node.op === "eventually" || node.op === "always" || node.op === "then") n += 2;
    else if (node.op === "holds_for") n += 1;
    else if (node.op === "hour_in") n += 2;
  }
  for (const c of children(node)) n += numericSlots(c);
  return n;
}

/** Free parameters: the distinct holes of a sketch, else the numeric bound slots of a closed rule. */
export function nParameters(rule: Rule): number {
  const hs = holesOf(rule);
  return hs.length > 0 ? hs.length : numericSlots(rule);
}

/** `violations` is the (weighted) count of violated examples. */
export function mdl(rule: Rule, violations: number, lam = 4.0): number {
  return nodeCount(rule) * BITS_PER_NODE + BITS_PER_HOLE * nParameters(rule) + lam * violations;
}
