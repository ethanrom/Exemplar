import { test } from "node:test";
import assert from "node:assert/strict";

import { calibrateScores, clopperPearson, conformalRank, conformalThreshold, minNegatives } from "./conformal.ts";
import { closeTo, numEq, readGolden } from "./testutil.ts";

const { meta, records } = readGolden("cal");
let cases = 0;
let mismatches = 0;
const fail = (id: string, what: string, got: unknown, want: unknown): void => {
  mismatches += 1;
  if (mismatches <= 20) console.error(`MISMATCH ${id} ${what}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
};

test(`F10 cal goldens (${meta.count} records, engine ${meta.engine_commit.slice(0, 8)}): 0 mismatches`, () => {
  for (const r of records) {
    if (r.kind === "rank") {
      const { alpha, n_max } = r.input;
      for (let n = 0; n <= n_max; n++) {
        cases += 1;
        const k = conformalRank(n, alpha);
        if (k !== r.expect.k[n]) fail(r.id, `k(n=${n})`, k, r.expect.k[n]);
      }
      cases += 1;
      if (minNegatives(alpha) !== r.expect.min_negatives) fail(r.id, "min_negatives", minNegatives(alpha), r.expect.min_negatives);
    } else if (r.kind === "cp") {
      cases += 1;
      const { x, n } = r.input;
      const [lo, hi] = clopperPearson(x, n);
      if (!numEq(x / n, r.expect.recall)) fail(r.id, "recall", x / n, r.expect.recall);
      if (!closeTo(lo, r.expect.ci[0], 0, 1e-9)) fail(r.id, "ci lo", lo, r.expect.ci[0]);
      if (!closeTo(hi, r.expect.ci[1], 0, 1e-9)) fail(r.id, "ci hi", hi, r.expect.ci[1]);
    } else if (r.kind === "cal") {
      cases += 1;
      const cal = calibrateScores(r.input.pos, r.input.neg, r.input.alpha);
      const e = r.expect;
      for (const f of ["alpha", "n_random_neg", "n_random_pos", "k", "tau", "delta", "tau_alpha", "recall"] as const) {
        const got = cal[f];
        const want = e[f];
        const ok = want === null ? got === null : numEq(got, want);
        if (!ok) fail(r.id, f, got, want);
      }
      if (cal.guarantee !== e.guarantee) fail(r.id, "guarantee", cal.guarantee, e.guarantee);
      if (cal.message !== e.message) fail(r.id, "message", cal.message, e.message);
      if (e.recall_ci95 === null) {
        if (cal.recall_ci95 !== null) fail(r.id, "ci", cal.recall_ci95, null);
      } else if (
        cal.recall_ci95 === null ||
        !closeTo(cal.recall_ci95[0], e.recall_ci95[0], 0, 1e-9) ||
        !closeTo(cal.recall_ci95[1], e.recall_ci95[1], 0, 1e-9)
      ) {
        fail(r.id, "ci", cal.recall_ci95, e.recall_ci95);
      }
    }
  }
  console.log(`F10 cal: ${cases} cases, ${mismatches} mismatches`);
  assert.equal(mismatches, 0);
  assert.ok(cases >= 15000);
});

test("hand checks: rank, floor at zero, no-guarantee message", () => {
  assert.equal(conformalRank(9, 0.1), 9);
  assert.equal(conformalRank(8, 0.1), 9);
  assert.equal(minNegatives(0.1), 9);
  const none = conformalThreshold([-0.5, -0.5, -0.5], 0.1);
  assert.equal(none.guarantee, false);
  assert.equal(none.k, null);
  assert.equal(none.message, "guarantee needs ≥ 9 random negatives (have 3)");
  const plateau = conformalThreshold(new Array(20).fill(-0.5), 0.1);
  assert.equal(plateau.tau_alpha, -0.5);
  assert.equal(plateau.tau, 0);
});
