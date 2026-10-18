// What "Z3 agrees" means: the verdicts of compareWithReference.
import { test } from "node:test";
import assert from "node:assert/strict";
import { compareWithReference, holeDifferences } from "./verdict.ts";
import type { Reference } from "./verdict.ts";
import type { Z3SolveResult } from "./solve.ts";

const timings = { encodeMs: 0, z3Ms: 0, checks: 0 };
const z = (over: Partial<Z3SolveResult> = {}): Z3SolveResult => ({
  status: "sat", holes: { d: 15 }, margin: 0.45, violated: [], violatedWeight: 0, satisfied: ["a", "b", "c"], placement: "slack-centre",
  placementDegraded: false, referenceVerified: null, note: "", solveMs: 1, timings, ...over,
});
const ref = (over: Partial<Reference> = {}): Reference => ({
  source: "browser", status: "sat", holes: { d: 15 }, margin: 0.45, violated: [], violatedWeight: 0, placement: "slack-centre", ...over,
});

test("identical status, holes, margin and violated set: agree", () => {
  const v = compareWithReference(z(), ref());
  assert.equal(v.kind, "agree");
  assert.deepEqual(v.differences, []);
  assert.equal(compareWithReference(z({ violated: ["a", "b"] }), ref({ violated: ["b", "a"] })).kind, "agree"); // order is irrelevant
  assert.equal(compareWithReference(z({ status: "unsat", holes: {}, margin: 0, violated: ["a"] }), ref({ status: "unsat", holes: null, margin: null, violated: ["a"] })).kind, "agree");
});

test("a different hole value at the slack centre is a difference, with the exact numbers", () => {
  const v = compareWithReference(z({ holes: { d: 14.5 } }), ref());
  assert.equal(v.kind, "differs");
  assert.deepEqual(v.differences, ["?d: Z3 14.5, shown 15"]);
  assert.match(v.summary, /Z3 differs: \?d: Z3 14.5, shown 15/);
});

test("a stepped-back placement that differs only in the holes agrees on the outcome, never as a bare agree", () => {
  const v = compareWithReference(z({ holes: { d: 2 }, placement: "slack-stepback(0.75)" }), ref({ holes: { d: 9 } }));
  assert.equal(v.kind, "agree_outcome");
  assert.deepEqual(v.differences, ["?d: Z3 2, shown 9"]);
  assert.equal(compareWithReference(z({ holes: { d: 2 } }), ref({ holes: { d: 9 }, placement: "model-rounded" })).kind, "agree_outcome");
});

test("holes that differ because Z3's hole-box queries hit a time limit are an outcome agreement that says so", () => {
  const v = compareWithReference(z({ holes: { d: 19.5 }, placementDegraded: true }), ref({ holes: { d: 22.5 } }));
  assert.equal(v.kind, "agree_outcome");
  assert.match(v.summary, /cut short by a time limit/);
  assert.deepEqual(v.differences, ["?d: Z3 19.5, shown 22.5"]);
  // a degraded placement never excuses a different margin or violated set
  assert.equal(compareWithReference(z({ margin: 0.3, placementDegraded: true }), ref()).kind, "differs");
});

test("holes that differ at the slack centre are an outcome agreement only when the evaluator confirms the shown rule is as good", () => {
  const verified = compareWithReference(z({ holes: { d: 11 }, referenceVerified: true }), ref({ holes: { d: 10 } }));
  assert.equal(verified.kind, "agree_outcome");
  assert.match(verified.summary, /evaluator confirms both placements are equally good/);
  assert.deepEqual(verified.differences, ["?d: Z3 11, shown 10"]);
  assert.equal(compareWithReference(z({ holes: { d: 11 }, referenceVerified: false }), ref({ holes: { d: 10 } })).kind, "differs");
  assert.equal(compareWithReference(z({ holes: { d: 11 }, referenceVerified: null }), ref({ holes: { d: 10 } })).kind, "differs");
  // never an excuse for a different margin or violated set
  assert.equal(compareWithReference(z({ margin: 0.3, referenceVerified: true }), ref()).kind, "differs");
});

test("status and margin differences are differences", () => {
  assert.deepEqual(compareWithReference(z({ status: "unsat" }), ref()).differences, ["status: Z3 unsat, shown sat"]);
  const v = compareWithReference(z({ margin: 0.3 }), ref());
  assert.equal(v.kind, "differs");
  assert.deepEqual(v.differences, ["margin: Z3 0.3, shown 0.45"]);
});

test("another optimal violated set: equal_optimum, verified against the enumerated sets or by equal weight", () => {
  const zz = z({ violated: ["b"], satisfied: ["a", "c"], violatedWeight: 3 });
  const viaSets = compareWithReference(zz, ref({ violated: ["a"], violatedWeight: 3, optimalSets: [["b", "c"], ["a", "c"]] }));
  assert.equal(viaSets.kind, "equal_optimum");
  assert.match(viaSets.summary, /another of the 2 equally optimal/);
  const viaWeight = compareWithReference(zz, ref({ violated: ["a"], violatedWeight: 3 }));
  assert.equal(viaWeight.kind, "equal_optimum");
  assert.equal(compareWithReference(zz, ref({ violated: ["a"], violatedWeight: 6 })).kind, "differs");
  assert.equal(compareWithReference(zz, ref({ violated: ["a"] })).kind, "differs"); // nothing to show it is a tie
  assert.equal(compareWithReference(zz, ref({ violated: ["a"], violatedWeight: 3, margin: 0.3 })).kind, "differs"); // margin first
});

test("no comparable reference, or a Z3 timeout: not comparable", () => {
  assert.equal(compareWithReference(z(), ref({ status: "timeout" })).kind, "not_comparable");
  assert.equal(compareWithReference(z({ status: "timeout" }), ref()).kind, "not_comparable");
});

test("holeDifferences names missing holes", () => {
  assert.deepEqual(holeDifferences({ a: 1 }, { a: 1, b: 2 }), ["?b: Z3 missing, shown 2"]);
  assert.deepEqual(holeDifferences({ a: 1 }, null), ["?a: Z3 1, shown missing"]);
  assert.deepEqual(holeDifferences({}, null), []);
});
