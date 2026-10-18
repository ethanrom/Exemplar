// F6 `synth.recorded` and F9 `cegis.presets`: the solver and the replay loop against the real engine.
import { test } from "node:test";
import assert from "node:assert/strict";

import { parse } from "../dsl/index.ts";
import { categorize } from "./compare/categorize.ts";
import type { EngineEntry } from "./compare/categorize.ts";
import { makeExampleContext, solveSketchExhaustive } from "./exhaustive.ts";
import { runReplay } from "./replay.ts";
import type { RunEvent } from "./state.ts";
import { makeExample } from "./types.ts";
import { readGolden, readGridJson } from "./testutil.ts";

const traces = readGridJson("golden/traces.json.gz").traces;
const exampleOf = (e: { alias: string; positive: boolean; weight: number }) =>
  makeExample(traces[e.alias], e.positive, e.weight, e.alias);

test("F6 synth.recorded: every recorded solve_result of the six exported runs", () => {
  const { meta, records } = readGolden("synth.recorded");
  const counts: Record<string, number> = { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0 };
  const byRun = new Map<string, ReturnType<typeof makeExampleContext>>();
  for (const r of records) {
    const run = r.input.run as string;
    if (!byRun.has(run)) byRun.set(run, makeExampleContext(r.input.examples.map(exampleOf)));
    const ctx = byRun.get(run)!;
    const sketch = parse(r.input.sketch);
    const ts = solveSketchExhaustive(sketch, ctx);
    const e = r.expect;
    const engine: EngineEntry = {
      status: e.status, holes: e.holes, margin: e.margin, violated: e.violated, placement: e.placement,
    };
    const v = categorize(sketch, ctx, ts, engine);
    counts[v.category] = (counts[v.category] ?? 0) + 1;
    if (v.category === "mismatch") console.error(`MISMATCH ${r.id} ${r.input.sketch}: ${v.reason}`);
  }
  console.log(`F6 synth.recorded (${meta.count}):`, JSON.stringify(counts));
  assert.equal(counts.mismatch, 0);
  assert.equal(meta.count, records.length);
});

test("F9 cegis.presets: the replay loop reproduces the engine's run_cegis stream", () => {
  const { records } = readGolden("cegis.presets");
  for (const r of records) {
    const examples = r.input.examples.map(exampleOf);
    const events: RunEvent[] = [];
    const out = runReplay(examples, r.input.rounds, (e) => events.push(e), { k: r.input.k, maxRounds: r.input.max_rounds });
    const norm = (e: any) => {
      const o: any = { type: e.type };
      for (const k of ["round", "sketch", "result", "holes", "margin", "violated_clip_ids", "error"]) {
        if (e[k] !== undefined && e[k] !== null) o[k] = e[k];
      }
      if (e.type === "candidates") delete o.sketch;
      return o;
    };
    const got = events.filter((e) => e.type !== "done").map(norm);
    const want: any[] = r.expect.events;
    const wantRes = new Map(want.filter((e) => e.type === "solve_result").map((e) => [e.sketch, e] as const));
    let engineSupplied = 0;
    for (const g of got.filter((e) => e.type === "solve_result")) {
      const w = wantRes.get(g.sketch);
      assert.ok(w, `unexpected solve_result for ${g.sketch}`);
      if (g.result === "budget_exceeded") {
        engineSupplied += 1;
        continue;
      }
      if (JSON.stringify(g) !== JSON.stringify(w)) {
        const ts = out.state!.records.get(g.sketch)!.result!;
        const v = categorize(ts.sketch, out.state!.ctx, ts, {
          status: w.result, holes: w.holes ?? null, margin: w.margin ?? null, violated: w.violated_clip_ids ?? [], placement: null,
        });
        assert.notEqual(v.category, "mismatch", `${r.id} ${g.sketch}: ${v.reason}`);
        engineSupplied += v.category === "engine_supplied" ? 1 : 0;
      }
    }
    console.log(`F9 ${r.id}: ${got.length} events (engine ${want.length}), ${engineSupplied} engine-supplied solves`);
    if (engineSupplied === 0) {
      assert.deepEqual(got, want.filter((e) => e.type !== "done"), `${r.id}: event stream`);
      assert.deepEqual(out.candidates.map((c) => c.dsl_text), r.expect.candidates.map((c: any) => c.dsl_text), `${r.id}: candidates`);
    }
  }
});
