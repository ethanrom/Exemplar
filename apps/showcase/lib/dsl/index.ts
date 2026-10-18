// Exemplar DSL for the browser: a TypeScript port of engine/exemplar/dsl (parser, typechecker, printers,
// evaluator, witnesses). Pure and deterministic: no DOM, no runtime dependencies. Python is the reference;
// the golden tests in ./test compare every output with the engine's.

export type {
  Always, And, Atom, Bound, Ctx, DeviceEq, Eventually, Hole, HoldsFor, HourIn, Node, Not, Or, Phi, Rule, SubtypeEq,
  Then, VarDecl,
} from "./ast.ts";
export { C, children, holesOf, isHole, nodeCount } from "./ast.ts";
export { toEnglish } from "./english.ts";
export { DSLError, DSLSyntaxError, UnboundHoleError } from "./errors.ts";
export { CompiledRule, PreparedTrace, compileRule, ctxHolds, ctxValue, evaluate, prepare, rho, robustness } from "./evaluator.ts";
export type { Argmax } from "./evaluator.ts";
export * from "./ontology.ts";
export { parse } from "./parser.ts";
export { toText } from "./printer.ts";
export type { Entity, Fact, Frame, PerceptionMeta, Trace, TraceContext } from "./trace.ts";
export { typecheck } from "./typecheck.ts";
export { pyFloatRepr, pyRound } from "./pycompat.ts";
export { boundText, boundValue, fillHoles, fmtNum, normalize, resolveHoles } from "./util.ts";
export type { HoleValues } from "./util.ts";
export { witness } from "./witness.ts";
export type { Witness, WitnessEntity, WitnessSpan } from "./witness.ts";
