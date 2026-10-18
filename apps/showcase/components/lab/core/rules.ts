// Bridges between the exported data (lib/data/types.ts) and the in-browser DSL (lib/dsl). Pure; no framework imports.

import { parse, prepare } from "../../../lib/dsl/index.ts";
import type { PreparedTrace, Rule, Trace } from "../../../lib/dsl/index.ts";
import type { TraceJson } from "../../../lib/data/types.ts";

/** The exported trace is the engine's Trace minus the private fields; the evaluator reads exactly these fields. */
export function asTrace(t: TraceJson): Trace {
  return t as unknown as Trace;
}

const parsed = new Map<string, Rule>();

/** parse() with a cache keyed by the exact text (sketches and closed rules are re-parsed on every render otherwise). */
export function parseCached(text: string): Rule {
  let r = parsed.get(text);
  if (r === undefined) {
    r = parse(text);
    parsed.set(text, r);
  }
  return r;
}

/** A prepared trace (offset matrix, signal index) for an exported trace, cached by object identity. */
export function prep(t: TraceJson): PreparedTrace {
  return prepare(asTrace(t));
}
