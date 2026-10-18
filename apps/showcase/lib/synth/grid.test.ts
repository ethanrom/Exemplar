// F8 `lab.grid` (sampled): the structure, provenance and scrubbing of data/grid, and the free-play pipeline against the
// grid on a stride of the valid slots. The full 6,050-slot run is `compare/run-parity.ts` (see the report).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { gunzipSync } from "node:zlib";

import { compileRule, parse, prepare, toEnglish, toText } from "../dsl/index.ts";
import { Grid } from "./compare/grid.ts";
import { checkSlot } from "./compare/parity.ts";
import { isValid, statesOf } from "./session.ts";
import type { LabData } from "./session.ts";

const dir = new URL("../../data/grid/", import.meta.url);
const gridText = gunzipSync(readFileSync(new URL("grid.json.gz", dir))).toString("utf-8");
const closedText = gunzipSync(readFileSync(new URL("closed.json.gz", dir))).toString("utf-8");
const grid = new Grid(JSON.parse(gridText));
const sketches = JSON.parse(readFileSync(new URL("sketches.json", dir), "utf-8")) as { id: number; text: string; holes: string[]; from_runs: string[] }[];
const curated = JSON.parse(readFileSync(new URL("curated.json", dir), "utf-8")) as { clips: string[]; default: (string | null)[] };
const traces = JSON.parse(gunzipSync(readFileSync(new URL("golden/traces.json.gz", dir))).toString("utf-8")).traces;
const data: LabData = { curated: grid.clips.map((a) => ({ alias: a, trace: traces[a] })), sketches };

test("grid structure and size budget (SPEC 4.5, 4.7)", () => {
  assert.equal(grid.doc.slots, 6561);
  assert.equal(grid.doc.valid_slots, 6050);
  assert.equal(grid.sketchCount, sketches.length);
  assert.equal(sketches.length, 37);
  assert.deepEqual(grid.clips, curated.clips);
  assert.ok(Buffer.byteLength(gridText) <= 6 * 1024 * 1024, "grid.json raw size");
  assert.ok(Buffer.byteLength(closedText) <= 600 * 1024, "closed.json raw size");
  assert.ok(statSync(new URL("grid.json.gz", dir)).size <= 800 * 1024, "grid.json transfer size");
  let valid = 0;
  for (let s = 0; s < 6561; s++) {
    const ok = isValid(statesOf(s));
    if (ok) valid += 1;
    for (let id = 0; id < grid.sketchCount; id++) {
      const e = grid.entry(id, s);
      if (!ok) assert.equal(e, null, `invalid slot ${s} must be null`);
      else assert.ok(e !== null, `valid slot ${s} sketch ${id} is missing from the grid`);
    }
  }
  assert.equal(valid, 6050);
  assert.equal(grid.doc.top6.length, 6561);
  // default states (recorded labels only)
  assert.deepEqual(curated.default, ["pos", "pos", "neg", "neg", "pos", null, "neg", "pos"]);
});

test("grid provenance: bank hash, curated trace digests, engine and solver parameters", () => {
  const p = grid.doc.provenance;
  assert.equal(p.solve_timeout_s, 60);
  assert.equal(p.k, 6);
  assert.equal(p.weight, 3.0);
  assert.match(p.engine_commit, /^[0-9a-f]{40}$/);
  const bank = createHash("sha256").update(JSON.stringify(sketches.map((s) => ({ id: s.id, text: s.text })))).digest("hex");
  assert.equal(p.sketch_bank_sha256, bank);
  assert.deepEqual(p.curated.map((c) => c.alias), grid.clips);
  for (const c of p.curated) assert.equal(c.trace_sha256, traces[c.alias].digest, `${c.alias} digest`);
});

test("no original ids, paths or tokens in the grid files (Scan S shapes)", () => {
  // the shapes are assembled from pieces so that this file itself stays clear of the publication scan
  const r = (...parts: string[]): RegExp => new RegExp(parts.join(""), "i");
  const shapes: RegExp[] = [
    r("\\b(cn|ru|run)_", "[0-9a-f]{10}\\b"), r("\\bup_", "[0-9a-f]{10}"), r("av", "a1\\."), r("ring\\.(dev", "ice|history|account)"),
    r("access", "_token"), r("\\bBear", "er\\s"), r("X-", "Amz-"), r("Signa", "ture="), r("arn", ":aws"), r("[A-Za-z]", ":[\\\\/]"),
    r("kask", "ara"), r("Sandar", "uwan"), r("/Us", "ers/"), r("local", "host"), r("127\\.0\\.", "0\\.1"), r("anthrop", "ic\\."),
    r("claude", "-[0-9]"),
  ];
  const texts = [gridText, closedText, readFileSync(new URL("sketches.json", dir), "utf-8"), readFileSync(new URL("curated.json", dir), "utf-8")];
  for (const t of texts) for (const re of shapes) assert.ok(!re.test(t), `shape ${re} found`);
});

test("closed rules: unique keys, scores for every library clip, dsl_text parses", () => {
  const closed = JSON.parse(closedText);
  assert.equal(closed.format, "exemplar.lab-closed/1");
  assert.equal(closed.clips.length, 64);
  const keys = new Set<string>();
  for (const r of closed.rules) {
    assert.ok(!keys.has(r.key));
    keys.add(r.key);
    assert.equal(r.scores.length, closed.clips.length);
    for (const s of r.scores) assert.ok(Number.isFinite(s));
  }
  // every top6 entry maps to a closed rule key
  for (let s = 0; s < grid.doc.slots; s++) {
    const t = grid.top6(s);
    if (t === null) continue;
    for (const id of t) {
      const e = grid.entry(id, s);
      assert.ok(e !== null && e.holes !== null || grid.holeNames(id).length === 0, `slot ${s} sketch ${id}`);
    }
  }
});

test("closed.json scores equal the TypeScript evaluator on every library clip", () => {
  const closed = JSON.parse(closedText);
  let n = 0;
  for (const r of closed.rules) {
    const cr = compileRule(parse(r.dsl_text));
    closed.clips.forEach((alias: string, i: number) => {
      const got = cr.score(prepare(traces[alias]));
      n += 1;
      assert.ok(got === r.scores[i], `${r.key} on ${alias}: ${got} vs ${r.scores[i]}`);
    });
    assert.equal(toText(parse(r.dsl_text)), r.dsl_text);
    assert.equal(toEnglish(parse(r.dsl_text)), r.english);
  }
  console.log(`closed.json: ${closed.rules.length} rules, ${n} scores identical`);
});

test("free play vs the grid on a stride of the valid slots: 0 mismatches", () => {
  const valid: number[] = [];
  for (let s = 0; s < 6561; s++) if (isValid(statesOf(s))) valid.push(s);
  const stride = Number(process.env.GRID_TEST_STRIDE ?? 150);
  const total = { slots: 0, entries: 0, identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0, top6Bad: 0, mdlBad: 0 };
  for (let i = 0; i < valid.length; i += stride) {
    const slot = valid[i] as number;
    if (grid.top6(slot) === null) continue; // a partial grid
    const r = checkSlot(grid, data, slot);
    total.slots += 1;
    total.entries += r.perSketch.length;
    total.identical += r.categories.identical;
    total.tie_verified += r.categories.tie_verified;
    total.engine_supplied += r.categories.engine_supplied;
    total.mismatch += r.categories.mismatch;
    total.top6Bad += r.top6 === "mismatch" ? 1 : 0;
    total.mdlBad += r.mdlMismatch;
    for (const p of r.problems) console.error(`slot ${slot}: ${p}`);
  }
  console.log("F8 sampled:", JSON.stringify(total));
  assert.ok(total.slots > 0);
  assert.equal(total.mismatch, 0);
  assert.equal(total.top6Bad, 0);
  assert.equal(total.mdlBad, 0);
});
