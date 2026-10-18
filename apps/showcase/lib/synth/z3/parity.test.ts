// Parity of the Z3 path with the real engine, in Node (z3-solver's Node build). The full runs are `npm run parity:z3`
// (scripts/z3/parity.mjs); this file runs F6 in full and a stride of F7 and of the Lab grid so `npm test` stays short.
//
//   Z3_F7_STRIDE (default 8)   every n-th record of synth.random and synth.random.sat
//   Z3_GRID_STRIDE (default 500) every n-th valid Lab slot, all 37 sketches
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { loadGrid, runGrid, runRandom, runRecorded } from "./parity.ts";
import type { Tally } from "./parity.ts";
import { startNodeZ3 } from "./testutil.ts";
import type { NodeZ3 } from "./testutil.ts";

let z3: NodeZ3;
before(async () => {
  z3 = await startNodeZ3();
});
after(async () => {
  await z3.close();
});

const summary = (t: Tally): string =>
  `${t.family}: ${t.cases} cases, agree ${t.agree}, agree_outcome ${t.agree_outcome}, equal_optimum ${t.equal_optimum}, differs ${t.differs}, ` +
  `not_comparable ${t.not_comparable}, timeouts ${t.timeouts}, errors ${t.errors}` +
  (t.boxes !== undefined ? `, hole boxes ${t.boxes_identical}/${t.boxes}` : "") + `, ${Math.round(t.ms)} ms`;

/** Nothing may differ, error or time out; the notes of the non-identical cases are printed for the log. */
function assertClean(t: Tally): void {
  console.log(summary(t));
  for (const n of t.notes.filter((x) => !/: (agree_outcome|equal_optimum)/.test(x))) console.error(n);
  assert.equal(t.differs, 0, `${t.family}: ${t.differs} differ`);
  assert.equal(t.errors, 0, `${t.family}: ${t.errors} errors`);
  assert.equal(t.timeouts, 0, `${t.family}: ${t.timeouts} timeouts`);
  assert.equal(t.not_comparable, 0, `${t.family}: ${t.not_comparable} not comparable`);
  assert.equal(t.unsupported, 0, `${t.family}: ${t.unsupported} unsupported`);
}

test("F6 synth.recorded: all 49 recorded solves of the six exported runs are reproduced exactly", async () => {
  const t = await runRecorded(z3.api);
  console.log(summary(t));
  assert.equal(t.cases, 49);
  assert.deepEqual(t.notes, []);
  assert.equal(t.agree, 49, "status, holes, margin and violated set identical to the engine's on every recorded solve");
});

for (const family of ["synth.random", "synth.random.sat"] as const) {
  test(`F7 ${family} (a stride): context clauses, hour holes, ties; status, holes, margin, violated set and hole box`, async () => {
    const t = await runRandom(z3.api, family, { stride: Number(process.env.Z3_F7_STRIDE ?? 8) });
    assertClean(t);
    assert.ok(t.cases > 40);
    assert.equal(t.boxes_identical, t.boxes, "every hole box equals the engine's");
  });
}

test("F8 lab.grid (a stride of the valid slots): all 37 library sketches per slot", async () => {
  const t = await runGrid(z3.api, loadGrid(), { stride: Number(process.env.Z3_GRID_STRIDE ?? 500) });
  assertClean(t);
  assert.ok(t.cases >= 37 * 12);
});
