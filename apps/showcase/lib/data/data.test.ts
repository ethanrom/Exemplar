// Consistency tests for the exported data: node --test apps/showcase/lib/data/
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";

import {
  creditOf,
  dataRoot,
  loadCalibration,
  loadClaims,
  loadCredits,
  loadCurated,
  loadLibrary,
  loadLive,
  loadManifest,
  loadRule,
  loadRun,
  loadSketches,
  loadTrace,
  resolveMedia,
  ruleSlugs,
  runSlugs,
  traceAliases,
} from "./load.ts";

const showcase = path.resolve(dataRoot(), "..");
const library = loadLibrary("frames");
const aliases = new Set(library.map((c) => c.alias));

test("manifest lists every file with matching size and hash", () => {
  const m = loadManifest();
  assert.equal(m.schema, "exemplar.showcase/1");
  assert.ok(m.files.length > 0);
  for (const f of m.files) {
    const p = path.join(showcase, f.path);
    assert.ok(existsSync(p), `missing ${f.path}`);
    const b = readFileSync(p);
    assert.equal(b.length, f.bytes, f.path);
    assert.equal(createHash("sha256").update(b).digest("hex"), f.sha256, f.path);
  }
  assert.equal(m.counts.library, library.length);
  assert.ok(m.asserts.every((a) => a.ok === true));
});

test("library: unique aliases, 16 frame times, credits resolve, media files exist", () => {
  assert.equal(aliases.size, library.length);
  const credits = new Set(loadCredits().map((c) => c.id));
  for (const c of library) {
    assert.equal(c.sheet_times_ms.length, 16, c.alias);
    assert.ok(credits.has(c.credit), `${c.alias}: unknown credit ${c.credit}`);
    assert.deepEqual(
      loadTrace(c.alias).frames.map((f) => f.t_ms),
      c.sheet_times_ms,
      `${c.alias}: sheet times differ from the trace`,
    );
    assert.equal(loadTrace(c.alias).clip_id, c.alias);
    if (c.media === "frames") {
      assert.ok(c.poster && existsSync(path.join(showcase, "public", c.poster)), `${c.alias}: poster`);
      assert.ok(c.sheet && existsSync(path.join(showcase, "public", c.sheet)), `${c.alias}: sheet`);
    } else {
      assert.equal(c.poster, undefined);
      assert.equal(c.sheet, undefined);
    }
  }
  assert.deepEqual([...traceAliases()].sort(), [...aliases].sort());
});

test("every credits entry has evidence; clips point at entries that list them", () => {
  const credits = loadCredits();
  for (const e of credits) assert.ok(e.permission.evidence.trim().length > 0, e.id);
  for (const c of library) assert.ok(creditOf(c).aliases.includes(c.alias), `${c.alias} not listed by ${c.credit}`);
});

test("every credits entry is cleared (the owner decided to show the Playground frames)", () => {
  assert.deepEqual(loadCredits().filter((c) => c.permission.status !== "cleared").map((c) => c.id), []);
});

test("SANDBOX_MEDIA=trace hides frames of pending clips only", () => {
  // Every entry is cleared in the export, so the variant is exercised by marking the sandbox entry pending in memory.
  const credits = loadCredits().map((c) =>
    c.id === "playground-sandbox" ? { ...c, permission: { ...c.permission, status: "pending_user_decision" as const } } : c);
  const trace = resolveMedia(library, credits, "trace");
  const pending = new Set(credits.filter((c) => c.permission.status === "pending_user_decision").map((c) => c.id));
  for (const c of trace) {
    if (pending.has(c.credit)) {
      assert.equal(c.media, "trace_only");
      assert.equal(c.poster, undefined);
    } else assert.equal(c.media, "frames");
  }
  assert.ok(trace.some((c) => c.media === "trace_only"));
});

test("runs, rules and ranks are consistent", () => {
  const rules = new Set(ruleSlugs());
  for (const s of runSlugs()) {
    const run = loadRun(s);
    for (const e of run.examples) assert.ok(aliases.has(e.alias), `${s}: example ${e.alias}`);
    for (const r of run.candidates) assert.ok(rules.has(r), `${s}: candidate ${r}`);
    for (const ev of run.events) {
      for (const a of ev.violated_clip_ids ?? []) assert.ok(aliases.has(a), `${s}: violated ${a}`);
      for (const r of ev.rule_ids ?? []) assert.ok(rules.has(r), `${s}: rule_ids ${r}`);
    }
    assert.ok(run.events.every((e, i, all) => i === 0 || e.seq > all[i - 1].seq));
  }
  for (const slug of rules) {
    const r = loadRule(slug);
    assert.equal(r.slug, slug);
    assert.ok(runSlugs().includes(r.run as never), `${slug}: run ${r.run}`);
    if (r.recorded_rank) {
      const run = loadRun(r.recorded_rank.run);
      assert.equal(run.candidates[r.recorded_rank.position - 1], slug);
      assert.equal(run.candidates.length, r.recorded_rank.of);
    }
    for (const b of r.backtest) assert.ok(aliases.has(b.alias), `${slug}: backtest ${b.alias}`);
    for (const a of r.violations) assert.ok(aliases.has(a), `${slug}: violation ${a}`);
  }
});

test("the deployed package rule: published wording, rank and calibration", () => {
  const r = loadRule("package-deployed");
  assert.equal(r.english, "There is a package k such that (k is on the steps or k is on the porch) continuously for at least 15 s.");
  assert.deepEqual(r.recorded_rank, { run: "p1-playground", position: 3, of: 6 });
  assert.equal(r.selection, "chosen_by_user_and_deployed");
  assert.deepEqual(loadCalibration().calibration, r.calibration);
  assert.equal(loadCalibration().random.length, loadCalibration().provenance.random_labels);
});

test("live: five events, outcomes as observed", () => {
  const live = loadLive();
  assert.deepEqual(live.events.map((e) => e.order), [1, 2, 3, 4, 5]);
  assert.deepEqual(live.events.map((e) => e.class), ["pg_bird", "pg_vehicle", "pg_package", "pg_vehicle", "pg_package"]);
  const fired = live.events.map((e) => e.decisions.filter((d) => d.fired).map((d) => d.rule));
  assert.deepEqual(fired, [[], ["vehicle-deployed"], ["package-deployed"], ["vehicle-deployed"], ["package-deployed"]]);
  for (const e of live.events) {
    assert.ok(aliases.has(e.alias));
    for (const d of e.decisions) assert.equal(d.witness !== null, d.fired);
  }
});

test("lab files, claims", () => {
  const cur = loadCurated();
  // seven clips are offered; the grid's eighth (most significant) digit is pinned to "not used", so slot numbers are unchanged
  assert.equal(cur.clips.length, 7);
  assert.equal(cur.default.length, 7);
  for (const a of cur.clips) assert.ok(aliases.has(a));
  assert.ok(loadSketches().length > 0);
  for (const c of loadClaims().claims) assert.ok(c.source.quote.includes(c.display), c.id);
});

test("no identifier-carrying keys anywhere in the data", () => {
  const banned = new Set(["device_id", "cache_key", "started_at_ms", "raw_json", "snapshot_path", "path_local", "access" + "_token", "refresh" + "_token"]);
  const walk = (o: unknown, where: string) => {
    if (Array.isArray(o)) o.forEach((v, i) => walk(v, `${where}[${i}]`));
    else if (o && typeof o === "object") {
      for (const [k, v] of Object.entries(o)) {
        assert.ok(!banned.has(k), `${where}.${k}`);
        walk(v, `${where}.${k}`);
      }
    }
  };
  walk(loadLive(), "live");
  for (const a of traceAliases()) walk(loadTrace(a), `trace ${a}`);
  for (const s of ruleSlugs()) walk(loadRule(s), `rule ${s}`);
  for (const s of runSlugs()) walk(loadRun(s), `run ${s}`);
});
