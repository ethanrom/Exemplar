// F7 `synth.random`: random sketches over random small traces - solver, hole box and tie count against the engine.
import { test } from "node:test";
import assert from "node:assert/strict";

import { parse } from "../dsl/index.ts";
import { categorize } from "./compare/categorize.ts";
import type { EngineEntry } from "./compare/categorize.ts";
import { InfeasibleBox, holeBox, makeExampleContext, solveSketchExhaustive } from "./exhaustive.ts";
import { makeExample } from "./types.ts";
import { readGolden } from "./testutil.ts";

for (const family of ["synth.random", "synth.random.sat"]) test(`F7 ${family}: status, holes, margin, violated, box and alternatives`, () => {
  const { meta, records } = readGolden(family);
  const counts: Record<string, number> = { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0 };
  let boxes = 0;
  let boxMismatch = 0;
  let alts = 0;
  let altMismatch = 0;
  for (const r of records) {
    const sketch = parse(r.input.sketch);
    const ex = r.input.examples.map((e: any) => makeExample(e.trace, e.positive, e.weight, e.clip_id));
    const ctx = makeExampleContext(ex);
    const ts = solveSketchExhaustive(sketch, ctx);
    const e = r.expect;
    const engine: EngineEntry = { status: e.status, holes: e.holes, margin: e.margin, violated: e.violated, placement: e.placement };
    const v = categorize(sketch, ctx, ts, engine);
    counts[v.category] = (counts[v.category] ?? 0) + 1;
    if (v.category === "mismatch") console.error(`MISMATCH ${r.id} ${r.input.sketch}: ${v.reason}`);
    if (ts.status !== "budget_exceeded") {
      alts += 1;
      if (e.alternatives !== -1 && ts.alternatives !== e.alternatives) {
        altMismatch += 1;
        console.error(`ALT MISMATCH ${r.id} ${r.input.sketch}: ts ${ts.alternatives} engine ${e.alternatives}`);
      }
    }
    if (e.status === "sat" && Object.keys(e.holes ?? {}).length > 0 && ts.status !== "budget_exceeded") {
      boxes += 1;
      let box: Record<string, [number, number]> | null = null;
      try {
        box = holeBox(sketch, ctx, { satisfied: e.satisfied, margin: e.margin });
      } catch (err) {
        if (!(err instanceof InfeasibleBox)) throw err;
      }
      const ok = JSON.stringify(box) === JSON.stringify(e.box);
      if (!ok) {
        boxMismatch += 1;
        console.error(`BOX MISMATCH ${r.id} ${r.input.sketch}: ts ${JSON.stringify(box)} engine ${JSON.stringify(e.box)}`);
      }
    }
  }
  console.log(`F7 ${family} (${meta.count}):`, JSON.stringify(counts), `boxes ${boxes} (mismatch ${boxMismatch})`, `alternatives ${alts} (mismatch ${altMismatch})`);
  assert.equal(counts.mismatch, 0);
  assert.equal(boxMismatch, 0);
  assert.equal(altMismatch, 0);
});
