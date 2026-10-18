import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";

import { LabSession, freePlay, slotOf, statesOf } from "./session.ts";
import type { LabData, WorkerMessage } from "./session.ts";
import { readGolden } from "./testutil.ts";

const dir = new URL("../../data/grid/", import.meta.url);
const sketches = JSON.parse(readFileSync(new URL("sketches.json", dir), "utf-8")) as { id: number; text: string }[];
const curated = JSON.parse(readFileSync(new URL("curated.json", dir), "utf-8")) as { clips: string[]; default: (string | null)[] };
const traces = JSON.parse(gunzipSync(readFileSync(new URL("golden/traces.json.gz", dir))).toString("utf-8")).traces;
const data: LabData = { curated: curated.clips.map((a) => ({ alias: a, trace: traces[a] })), sketches };
const defaultStates = curated.default.map((d) => (d === "pos" ? 1 : d === "neg" ? 2 : 0)) as (0 | 1 | 2)[];

test("slot arithmetic: base 3, clip 0 least significant", () => {
  assert.equal(slotOf([1, 0, 0, 0, 0, 0, 0, 0]), 1);
  assert.equal(slotOf([0, 2, 0, 0, 0, 0, 0, 0]), 6);
  assert.deepEqual(statesOf(slotOf(defaultStates)), defaultStates);
  assert.equal(slotOf([2, 2, 2, 2, 2, 2, 2, 2]), 6560);
});

test("free play on the recorded default labels: 37 sketches, six ranked candidates, no sketch rejected", () => {
  const events: string[] = [];
  const r = freePlay(data, defaultStates, (e) => events.push(e.type));
  assert.equal(r.outcomes.length, 37);
  assert.ok(r.outcomes.every((o) => o.status !== "rejected"));
  assert.equal(r.items.length, 6);
  assert.deepEqual(r.items.map((i) => i.rank), [1, 2, 3, 4, 5, 6]);
  for (let i = 1; i < r.items.length; i++) assert.ok((r.items[i - 1] as any).mdl <= (r.items[i] as any).mdl);
  assert.equal(events.filter((e) => e === "sketch_proposed").length, 37);
  assert.equal(events.filter((e) => e === "solve_started").length, 37);
  assert.equal(events[events.length - 1], "candidates");
});

test("LabSession: request ids, a newer request supersedes the running one, cancel drops results", async () => {
  const out: WorkerMessage[] = [];
  const s = new LabSession((m) => out.push(m));
  await s.handle({ type: "init", data });
  // two requests back to back: only the second one may produce results
  const p1 = s.handle({ type: "free", request_id: 1, states: defaultStates });
  const p2 = s.handle({ type: "free", request_id: 2, states: defaultStates });
  await Promise.all([p1, p2]);
  assert.ok(out.every((m) => m.request_id === 2), "only request 2 posts");
  assert.ok(out.some((m) => m.type === "done" && m.request_id === 2));
  const cands = out.find((m) => m.type === "candidates") as Extract<WorkerMessage, { type: "candidates" }>;
  assert.equal(cands.items.length, 6);
  // a cancelled request posts nothing
  out.length = 0;
  const p3 = s.handle({ type: "free", request_id: 3, states: defaultStates });
  await s.handle({ type: "cancel", request_id: 3 });
  await p3;
  assert.equal(out.length, 0);
  // an older request id that arrives late is ignored
  await s.handle({ type: "free", request_id: 2, states: defaultStates });
  assert.equal(out.length, 0);
});

test("LabSession preset: replays the recorded rounds of P1 and reports its candidates", async () => {
  const { records } = readGolden("cegis.presets");
  const p1 = records.find((r) => r.id === "p1-playground")!;
  const out: WorkerMessage[] = [];
  const s = new LabSession((m) => out.push(m));
  await s.handle({ type: "init", data: { ...data, traces } });
  await s.handle({ type: "preset", request_id: 7, run: { examples: p1.input.examples, rounds: p1.input.rounds, k: 6 } });
  const cands = out.find((m) => m.type === "candidates") as Extract<WorkerMessage, { type: "candidates" }>;
  assert.deepEqual(cands.items.map((c) => c.dsl_text), p1.expect.candidates.map((c: any) => c.dsl_text));
  assert.ok(out.some((m) => m.type === "done"));
});
