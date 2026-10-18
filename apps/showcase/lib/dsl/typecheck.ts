// Typechecker: `typecheck(rule) -> string[]`. Port of engine/exemplar/dsl/typecheck.py.
// Messages are written to be fed back to an LLM; they are the engine's, character for character.

import { isHole } from "./ast.ts";
import type { Atom, Bound, Phi, Rule } from "./ast.ts";
import { PREDICATES, SUB_TYPE_SET, SUB_TYPES, VAR_TYPES, ZONES, ZONE_SET } from "./ontology.ts";
import { pyFloatStr } from "./pycompat.ts";
import { boundText, fmtNum } from "./util.ts";
import { toText } from "./printer.ts";

// Python's `$` also matches just before a trailing newline, so `^X$` accepts "X" and "X\n".
const LABEL_RE = /^[a-z][a-z0-9_]*\n?$/;
const DEVICE_RE = /^[A-Za-z0-9._-]+\n?$/;

function sig(pred: string): string {
  return `${pred}(${(PREDICATES.get(pred) as readonly string[]).join(", ")})`;
}

function slot(kind: string): string {
  if (kind === "Entity") return "an entity variable (any type)";
  if (kind === "Carryable") return "a Carryable (Package or Object) variable";
  return `a ${kind} variable`;
}

/** A variable of type T fits a slot of kind K iff VAR_TYPES[T] is a subset of VAR_TYPES[K]. */
function fits(varType: string, kind: string): boolean {
  const have = VAR_TYPES.get(varType) ?? [];
  const want = new Set(VAR_TYPES.get(kind) ?? []);
  return have.every((e) => want.has(e));
}

/**
 * Return a list of human-readable problems; an empty list means the rule is well-typed.
 *
 * Checks: unique variable names; every atom argument is a declared variable, a Zone literal or (for `attr`'s
 * second argument) a label; predicate known and arity right; variable type fits each slot; numeric windows
 * satisfy `0 <= a <= b`; `holds_for` d >= 0; hours in 0-23; no unused variables. Holes (`?name`) are accepted
 * wherever a number may appear.
 */
export function typecheck(rule: Rule): string[] {
  const errs: string[] = [];
  const declared = new Map<string, string>();
  for (const v of rule.vars) {
    if (declared.has(v.name)) {
      errs.push(`variable '${v.name}' is declared more than once; every variable needs a unique name`);
    } else if (ZONE_SET.has(v.name)) {
      errs.push(`variable name '${v.name}' clashes with the zone '${v.name}'; rename the variable`);
    }
    if (!declared.has(v.name)) declared.set(v.name, v.type);
  }
  const used = new Set<string>();

  /** Check one concrete bound; holes pass. */
  const boundOk = (what: string, x: Bound, hour = false): boolean => {
    if (isHole(x)) return true;
    if (!hour && !Number.isFinite(x)) {
      errs.push(`${what}: bound must be a finite number, got ${pyFloatStr(x)}`);
      return false;
    }
    if (hour) {
      if (!Number.isInteger(x) || !(x >= 0 && x <= 23)) {
        errs.push(`${what}: hours must be whole numbers between 0 and 23, got ${fmtNum(x)}`);
        return false;
      }
    } else if (x < 0) {
      errs.push(`${what}: bounds are seconds and must be >= 0, got ${fmtNum(x)}`);
      return false;
    }
    return true;
  };

  const windowCheck = (name: string, lo: Bound, hi: Bound): void => {
    const text = `${name}[${boundText(lo)}, ${boundText(hi)}]`;
    const okLo = boundOk(text, lo);
    const okHi = boundOk(text, hi);
    if (okLo && okHi && !isHole(lo) && !isHole(hi) && lo > hi) {
      errs.push(`${text}: the lower bound must be <= the upper bound (needs 0 <= a <= b)`);
    }
  };

  const markUsed = (args: readonly string[]): void => {
    for (const x of args) if (declared.has(x)) used.add(x);
  };

  const atom = (a: Atom): void => {
    const kinds = PREDICATES.get(a.pred);
    if (kinds === undefined) {
      errs.push(`unknown predicate '${a.pred}'; known: ${[...PREDICATES.keys()].join(", ")}`);
      markUsed(a.args);
      return;
    }
    if (a.args.length !== kinds.length) {
      errs.push(
        `${a.pred} takes ${kinds.length} argument${kinds.length !== 1 ? "s" : ""} (${sig(a.pred)}), ` +
          `got ${a.args.length}: ${toText(a)}`,
      );
      markUsed(a.args);
      return;
    }
    kinds.forEach((kind, idx) => {
      const arg = a.args[idx];
      const where = `argument ${idx + 1} of ${a.pred}`;
      if (kind === "Zone") {
        if (ZONE_SET.has(arg)) return;
        if (declared.has(arg)) {
          used.add(arg);
          errs.push(`${where} must be a zone literal (${ZONES.join(", ")}), not the variable '${arg}'`);
        } else {
          errs.push(`${where}: '${arg}' is not a zone; zones are: ${ZONES.join(", ")}`);
        }
      } else if (kind === "Label") {
        if (declared.has(arg)) {
          used.add(arg);
          errs.push(
            `${where} must be a label literal such as hoodie or delivery_uniform, not the variable '${arg}'`,
          );
        } else if (!LABEL_RE.test(arg)) {
          errs.push(`${where}: '${arg}' is not a valid label (lower-case letters, digits, underscores)`);
        }
      } else if (declared.has(arg)) {
        used.add(arg);
        if (!fits(declared.get(arg) as string, kind)) {
          errs.push(
            `${where} must be ${slot(kind)} (${sig(a.pred)}), but '${arg}' is declared ${declared.get(arg)}`,
          );
        }
      } else if (ZONE_SET.has(arg)) {
        errs.push(`${where} must be ${slot(kind)}, not the zone '${arg}' (${sig(a.pred)})`);
      } else {
        const have = [...declared].map(([n, t]) => `${n}: ${t}`).join(", ");
        errs.push(`undeclared variable '${arg}' in ${toText(a)}; declared variables: ${have}`);
      }
    });
  };

  const walk = (n: Phi): void => {
    switch (n.op) {
      case "atom":
        atom(n);
        break;
      case "and":
      case "or":
        for (const c of n.args) walk(c);
        break;
      case "not":
        walk(n.arg);
        break;
      case "eventually":
      case "always":
        windowCheck(n.op, n.a, n.b);
        walk(n.arg);
        break;
      case "then":
        windowCheck("then", n.a, n.b);
        walk(n.left);
        walk(n.right);
        break;
      case "holds_for":
        boundOk("holds_for", n.d);
        walk(n.arg);
        break;
      default:
        errs.push(`unsupported node ${(n as { op?: string }).op ?? "?"}`);
    }
  };

  walk(rule.body);

  for (const name of declared.keys()) {
    if (!used.has(name)) errs.push(`variable '${name}' is declared but never used in the formula`);
  }

  for (const c of rule.when) {
    if (c.op === "hour_in") {
      boundOk("hour in [...]", c.h1, true);
      boundOk("hour in [...]", c.h2, true);
    } else if (c.op === "subtype_eq") {
      if (!SUB_TYPE_SET.has(c.value)) {
        errs.push(`unknown subtype '${c.value}'; known: ${SUB_TYPES.join(", ")}`);
      }
    } else if (c.op === "device_eq") {
      if (!DEVICE_RE.test(c.value)) {
        errs.push(`device id '${c.value}' may only contain letters, digits, '.', '_' and '-'`);
      }
    }
  }
  return errs;
}
