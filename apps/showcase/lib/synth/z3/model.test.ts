// The wording and the rules of the Z3 badge and the run summary.
import { test } from "node:test";
import assert from "node:assert/strict";
import { badgeModel, itemResult, pickItems, summarize, summaryText } from "./model.ts";
import type { ItemResult } from "./model.ts";
import type { Z3SolveResult } from "./solve.ts";
import type { Reference } from "./verdict.ts";

const timings = { encodeMs: 0, z3Ms: 0, checks: 0 };
const z = (over: Partial<Z3SolveResult> = {}): Z3SolveResult => ({
  status: "sat", holes: { d: 15 }, margin: 0.45, violated: [], violatedWeight: 0, satisfied: ["a"], placement: "slack-centre",
  placementDegraded: false, referenceVerified: null, note: "", solveMs: 1, timings, ...over,
});
const ref = (over: Partial<Reference> = {}): Reference => ({
  source: "browser", status: "sat", holes: { d: 15 }, margin: 0.45, violated: [], violatedWeight: 0, placement: "slack-centre", ...over,
});

test("a solved identical answer is 'Z3 agrees'; the badge says what it was compared with", () => {
  const r = itemResult({ kind: "solved", result: z() }, ref());
  const b = badgeModel(r, false);
  assert.equal(b?.label, "Z3 agrees");
  assert.equal(b?.tone, "pos");
  assert.equal(b?.icon, "check");
  assert.match(b?.title ?? "", /computed in your browser/);
  const e = badgeModel(itemResult({ kind: "solved", result: z() }, ref({ source: "engine" })), false);
  assert.equal(e?.label, "Z3 agrees");
  assert.match(e?.title ?? "", /engine's result/);
});

test("'Z3 agrees' never appears for anything but an identical answer", () => {
  const cases: ItemResult[] = [
    itemResult({ kind: "solved", result: z({ holes: { d: 14.5 } }) }, ref()),
    itemResult({ kind: "solved", result: z({ holes: { d: 2 }, placement: "slack-stepback(0.75)" }) }, ref({ holes: { d: 9 } })),
    itemResult({ kind: "solved", result: z({ violated: ["b"], satisfied: ["a"], violatedWeight: 3 }) }, ref({ violated: ["a"], violatedWeight: 3 })),
    itemResult({ kind: "solved", result: z({ status: "timeout" }) }, ref()),
    itemResult({ kind: "unsupported", reason: "x" }, ref()),
    itemResult({ kind: "error", message: "boom" }, ref()),
  ];
  for (const c of cases) assert.notEqual(badgeModel(c, false)?.label, "Z3 agrees");
});

test("a difference shows the exact numbers; the outcome-only and tie cases say so", () => {
  const diff = badgeModel(itemResult({ kind: "solved", result: z({ holes: { d: 14.5 } }) }, ref()), false);
  assert.equal(diff?.label, "Z3 differs");
  assert.equal(diff?.tone, "neg");
  assert.deepEqual(diff?.lines, ["?d: Z3 14.5, shown 15"]);
  const out = badgeModel(itemResult({ kind: "solved", result: z({ holes: { d: 2 }, placement: "slack-stepback(0.75)" }) }, ref({ holes: { d: 9 } })), false);
  assert.equal(out?.label, "Z3 agrees on the outcome");
  assert.deepEqual(out?.lines, ["?d: Z3 2, shown 9"]);
  const tie = badgeModel(itemResult({ kind: "solved", result: z({ violated: ["b"], satisfied: ["a"], violatedWeight: 3 }) }, ref({ violated: ["a"], violatedWeight: 3 })), false);
  assert.equal(tie?.label, "Z3: equally optimal choice");
});

test("errors remove the badge; unsupported and timed-out sketches say 'Not checked by Z3'", () => {
  assert.equal(badgeModel(itemResult({ kind: "error", message: "boom" }, ref()), false), null);
  const u = badgeModel(itemResult({ kind: "unsupported", reason: "the sketch does not parse" }, ref()), false);
  assert.equal(u?.label, "Not checked by Z3");
  assert.deepEqual(u?.lines, ["the sketch does not parse"]);
  const t = badgeModel(itemResult({ kind: "solved", result: z({ status: "timeout" }) }, ref()), false);
  assert.equal(t?.label, "Not checked by Z3");
  assert.match(t?.lines[0] ?? "", /time budget/);
  const n = badgeModel(itemResult({ kind: "solved", result: z() }, ref({ status: "timeout" })), false);
  assert.equal(n?.label, "Not checked by Z3");
});

test("while the run is going the badge is a quiet 'checking' tag; with nothing asked there is none", () => {
  assert.equal(badgeModel(undefined, true)?.label, "Z3 checking");
  assert.equal(badgeModel(undefined, false), null);
});

test("summary sentences", () => {
  const agree = itemResult({ kind: "solved", result: z() }, ref());
  assert.equal(summaryText(summarize([agree])), "Z3 agrees on the checked rule.");
  assert.equal(summaryText(summarize([agree, agree, agree])), "Z3 agrees on all 3 checked rules.");
  const diff = itemResult({ kind: "solved", result: z({ holes: { d: 14.5 } }) }, ref());
  const err = itemResult({ kind: "error", message: "boom" }, ref());
  const unc = itemResult({ kind: "unsupported", reason: "x" }, ref());
  assert.equal(summaryText(summarize([agree, diff, err, unc])), "Z3 checked 4 rules: 1 agree, 1 differ, 1 not checked, 1 failed (boom).");
  assert.equal(summaryText(summarize([])), "Nothing to check yet.");
});

test("pickItems: the selected rule first, then the top candidates, at most 7, no duplicates", () => {
  const views = Array.from({ length: 9 }, (_, i) => ({ key: `k${i}` }));
  assert.deepEqual(pickItems(views, "k3").map((v) => v.key), ["k3", "k0", "k1", "k2", "k4", "k5", "k6"]);
  assert.deepEqual(pickItems(views, null).map((v) => v.key), ["k0", "k1", "k2", "k3", "k4", "k5", "k6"]);
  assert.deepEqual(pickItems(views.slice(0, 2), "k9").map((v) => v.key), ["k0", "k1"]);
});
