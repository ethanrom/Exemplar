import { test } from "node:test";
import assert from "node:assert/strict";

import { parse } from "../dsl/index.ts";
import { calibrate } from "./calibrate.ts";
import { closeTo, numEq, readGolden, readGridJson } from "./testutil.ts";

const traces = readGridJson("golden/traces.json.gz").traces;

test("F10 cal.real: every closed rule calibrated on the package random set (scores, k, tau, recall, CI)", () => {
  const { meta, records } = readGolden("cal.real");
  let bad = 0;
  const fail = (id: string, what: string, got: unknown, want: unknown): void => {
    bad += 1;
    if (bad <= 20) console.error(`MISMATCH ${id} ${what}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);
  };
  let scores = 0;
  for (const r of records) {
    const rule = parse(r.input.dsl_text);
    const labelled = r.input.random.map((x: any) => ({ clip_id: x.alias, trace: traces[x.alias], positive: x.positive }));
    const out = calibrate(rule, labelled, r.input.alpha);
    const all = [...out.pos, ...out.neg];
    // engine scores are listed in label order; ours split by label, so compare as the same multiset per label
    const wantPos = r.input.random.map((x: any, i: number) => (x.positive ? r.expect.scores[i] : null)).filter((x: unknown) => x !== null);
    const wantNeg = r.input.random.map((x: any, i: number) => (!x.positive ? r.expect.scores[i] : null)).filter((x: unknown) => x !== null);
    scores += all.length;
    if (JSON.stringify(out.pos) !== JSON.stringify(wantPos)) fail(r.id, "pos scores", out.pos, wantPos);
    if (JSON.stringify(out.neg) !== JSON.stringify(wantNeg)) fail(r.id, "neg scores", out.neg, wantNeg);
    const e = r.expect.calibration;
    const c = out.calibration;
    for (const f of ["alpha", "n_random_neg", "n_random_pos", "k", "tau", "delta", "tau_alpha", "recall"] as const) {
      if (f === "tau_alpha" && r.kind === "recorded") continue; // the recorded calibration_json has no tau_alpha
      const ok = e[f] === null ? c[f] === null : numEq(c[f], e[f]);
      if (!ok) fail(r.id, f, c[f], e[f]);
    }
    if (c.guarantee !== e.guarantee || c.message !== e.message) fail(r.id, "guarantee/message", [c.guarantee, c.message], [e.guarantee, e.message]);
    if (e.recall_ci95 === null ? c.recall_ci95 !== null : c.recall_ci95 === null || !closeTo(c.recall_ci95[0], e.recall_ci95[0], 0, 1e-9) || !closeTo(c.recall_ci95[1], e.recall_ci95[1], 0, 1e-9)) {
      fail(r.id, "ci", c.recall_ci95, e.recall_ci95);
    }
  }
  console.log(`F10 cal.real: ${records.length} calibrations, ${scores} evaluator scores, ${bad} mismatches (${meta.random_labels} random labels)`);
  assert.equal(bad, 0);
});
