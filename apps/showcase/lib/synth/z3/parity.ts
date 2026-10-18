// Parity of the Z3 path with the real engine (Node only; used by parity.test.ts and scripts/z3/parity.mjs, never by the
// worker). Z3's answer for each case is compared with the engine's by `compareWithReference`:
//
//   F6  synth.recorded   the 49 recorded solve_results of the six exported runs
//   F7  synth.random     random sketches on random small traces (context clauses, hour holes, ties): status, holes,
//                        margin, violated set - and the hole box of every sat entry
//   F8  lab.grid         slots of the Lab grid (6,050 valid label combinations) x the 37 library sketches
//
// A case counts as `agree` (identical), `agree_outcome` (same outcome, hole values differ because the placement stepped
// back from the slack centre and depends on the solver's model point), `equal_optimum` (another optimal violated set,
// confirmed against the exhaustive solver's enumeration or, for the grid, against the engine's own tie count),
// `differs` (a failure) or `not_comparable`. `unsupported` counts sketches the encoder does not take (none exist in the
// library or the goldens). Pass `Z3Api` from a Node z3-solver instance (testutil.ts).

import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { parse } from "../../dsl/index.ts";
import type { Rule } from "../../dsl/index.ts";
import { Grid } from "../compare/grid.ts";
import { makeExampleContext, solveSketchExhaustive } from "../exhaustive.ts";
import { examplesOf, isValid, statesOf } from "../session.ts";
import type { LabData } from "../session.ts";
import { makeExample } from "../types.ts";
import type { Example } from "../types.ts";
import { holeBoxZ3, solveSketchZ3 } from "./solve.ts";
import type { Z3Api, Z3SolveResult } from "./solve.ts";
import { compareWithReference } from "./verdict.ts";
import type { Reference, VerdictKind } from "./verdict.ts";

const dataDir = new URL("../../../data/grid/", import.meta.url);

const readGz = (name: string): string => gunzipSync(readFileSync(new URL(name, dataDir))).toString("utf-8");
const readGolden = (family: string): { meta: Record<string, unknown>; records: any[] } => {
  const lines = readGz(`golden/${family}.jsonl.gz`).split("\n").filter((l) => l.trim() !== "");
  return { meta: JSON.parse(lines[0] as string), records: lines.slice(1).map((l) => JSON.parse(l)) };
};

export interface Tally {
  family: string;
  cases: number;
  agree: number;
  agree_outcome: number;
  equal_optimum: number;
  differs: number;
  not_comparable: number;
  unsupported: number;
  /** Z3 timed out (not an agreement and not a disagreement). */
  timeouts: number;
  /** Z3 raised an error (an encoder mismatch is a bug). */
  errors: number;
  /** Hole boxes compared (F7) and how many were identical. */
  boxes?: number;
  boxes_identical?: number;
  /** Wall time of the run in ms (sum over cases). */
  ms: number;
  /** One line per case that is not `agree`: what differs. */
  notes: string[];
}

export const newTally = (family: string): Tally => ({
  family, cases: 0, agree: 0, agree_outcome: 0, equal_optimum: 0, differs: 0, not_comparable: 0, unsupported: 0, timeouts: 0, errors: 0, ms: 0, notes: [],
});

const sumWeights = (ex: readonly Example[], ids: readonly string[]): number => ex.reduce((w, e) => (ids.includes(e.clip_id) ? w + e.weight : w), 0);

async function solveCase(
  api: Z3Api, sketch: Rule, ex: readonly Example[], timeoutMs: number, tally: Tally, label: string,
  referenceHoles?: Readonly<Record<string, number>> | null,
): Promise<Z3SolveResult | null> {
  const t = performance.now();
  try {
    const r = await solveSketchZ3(api, sketch, ex, { timeoutMs, referenceHoles: referenceHoles ?? undefined });
    tally.ms += performance.now() - t;
    tally.cases += 1;
    if (r.status === "timeout") {
      tally.timeouts += 1;
      tally.notes.push(`${label}: Z3 timed out`);
      return null;
    }
    return r;
  } catch (e) {
    tally.ms += performance.now() - t;
    tally.cases += 1;
    tally.errors += 1;
    tally.notes.push(`${label}: ${e instanceof Error ? `${e.name}: ${e.message}` : String(e)}`);
    return null;
  }
}

function record(tally: Tally, kind: VerdictKind, label: string, detail: string): void {
  tally[kind] += 1;
  if (kind !== "agree") tally.notes.push(`${label}: ${kind}${detail === "" ? "" : ` - ${detail}`}`);
}

// ============================================================================ F6 and F7
export async function runRecorded(api: Z3Api, opts: { timeoutMs?: number } = {}): Promise<Tally> {
  const { records } = readGolden("synth.recorded");
  const traces = JSON.parse(readGz("golden/traces.json.gz")).traces;
  const tally = newTally("F6 synth.recorded");
  const byRun = new Map<string, Example[]>();
  for (const r of records) {
    if (!byRun.has(r.input.run)) {
      byRun.set(r.input.run, r.input.examples.map((e: any) => makeExample(traces[e.alias], e.positive, e.weight, e.alias)));
    }
    const ex = byRun.get(r.input.run) as Example[];
    const sketch = parse(r.input.sketch);
    const z = await solveCase(api, sketch, ex, opts.timeoutMs ?? 20_000, tally, r.id, r.expect.holes);
    if (z === null) continue;
    const e = r.expect;
    const ref: Reference = {
      source: "engine", status: e.status, holes: e.holes ?? null, margin: e.margin ?? null, violated: e.violated ?? [],
      violatedWeight: sumWeights(ex, e.violated ?? []), placement: e.placement ?? null,
    };
    const v = compareWithReference(z, ref);
    record(tally, v.kind, r.id, v.differences.join("; "));
  }
  return tally;
}

/** F7 (`synth.random` or `synth.random.sat`): every `stride`-th record, starting at `offset`. */
export async function runRandom(
  api: Z3Api, family: "synth.random" | "synth.random.sat", opts: { stride?: number; offset?: number; timeoutMs?: number } = {},
): Promise<Tally> {
  const { records } = readGolden(family);
  const stride = opts.stride ?? 1;
  const tally = newTally(`F7 ${family}`);
  tally.boxes = 0;
  tally.boxes_identical = 0;
  for (let i = opts.offset ?? 0; i < records.length; i += stride) {
    const r = records[i];
    const sketch = parse(r.input.sketch);
    const ex: Example[] = r.input.examples.map((x: any) => makeExample(x.trace, x.positive, x.weight, x.clip_id));
    const z = await solveCase(api, sketch, ex, opts.timeoutMs ?? 20_000, tally, `${r.id} ${r.input.sketch}`, r.expect.holes);
    if (z === null) continue;
    const e = r.expect;
    const ref: Reference = {
      source: "engine", status: e.status, holes: e.holes ?? null, margin: e.margin ?? null, violated: e.violated ?? [],
      violatedWeight: sumWeights(ex, e.violated ?? []), placement: e.placement ?? null,
    };
    let v = compareWithReference(z, ref);
    if (v.kind === "differs" || v.kind === "agree_outcome") {
      // confirm against the independent enumeration of optimal sets
      const ts = solveSketchExhaustive(sketch, makeExampleContext(ex));
      if (ts.status !== "budget_exceeded") v = compareWithReference(z, { ...ref, optimalSets: ts.optimalSets });
    }
    record(tally, v.kind, `${r.id} ${r.input.sketch}`, v.differences.join("; "));
    if (e.status === "sat" && e.box && Object.keys(e.holes ?? {}).length > 0) {
      tally.boxes = (tally.boxes ?? 0) + 1;
      try {
        const box = await holeBoxZ3(api, sketch, ex, { satisfied: e.satisfied, margin: e.margin });
        if (JSON.stringify(box) === JSON.stringify(e.box)) tally.boxes_identical = (tally.boxes_identical ?? 0) + 1;
        else tally.notes.push(`${r.id} ${r.input.sketch}: hole box ${JSON.stringify(box)} vs engine ${JSON.stringify(e.box)}`);
      } catch (err) {
        tally.notes.push(`${r.id} ${r.input.sketch}: hole box failed: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  }
  return tally;
}

// ============================================================================ F8 (the Lab grid)
export interface GridFixture {
  readonly grid: Grid;
  readonly data: LabData;
  readonly validSlots: readonly number[];
}

export function loadGrid(): GridFixture {
  const grid = new Grid(JSON.parse(readGz("grid.json.gz")));
  const sketches = JSON.parse(readFileSync(new URL("sketches.json", dataDir), "utf-8")) as LabData["sketches"];
  const traces = JSON.parse(readGz("golden/traces.json.gz")).traces;
  const data: LabData = { curated: grid.clips.map((alias) => ({ alias, trace: traces[alias] })), sketches };
  const validSlots: number[] = [];
  for (let s = 0; s < 6561; s++) if (isValid(statesOf(s))) validSlots.push(s);
  return { grid, data, validSlots };
}

const GRID_STATUS = ["sat", "unsat", "rejected", "timeout", "grid_fallback", "error"] as const;

/** Every `stride`-th valid slot from `offset`, all library sketches (or only `sketchIds`). */
export async function runGrid(
  api: Z3Api, fx: GridFixture,
  opts: { stride?: number; offset?: number; skip?: number; limit?: number; sketchIds?: readonly number[]; timeoutMs?: number; onSlot?: (slot: number, t: Tally) => void } = {},
): Promise<Tally> {
  const { grid, data, validSlots } = fx;
  const tally = newTally("F8 lab.grid");
  const stride = opts.stride ?? 1;
  const slots: number[] = [];
  for (let i = opts.offset ?? 0; i < validSlots.length; i += stride) slots.push(validSlots[i] as number);
  // `skip` / `limit` take a window of that list, so a long sweep can run in short processes (z3-solver's 2 GB heap is not
  // returned between solves; one process survives about 2,500 grid solves)
  const window = slots.slice(opts.skip ?? 0, opts.limit === undefined ? undefined : (opts.skip ?? 0) + opts.limit);
  slots.length = 0;
  slots.push(...window);
  const parsed = data.sketches.map((s) => ({ id: s.id, rule: parse(s.text) }));
  for (const slot of slots) {
    const ex = examplesOf(data, statesOf(slot));
    for (const sk of parsed) {
      if (opts.sketchIds !== undefined && !opts.sketchIds.includes(sk.id)) continue;
      const g = grid.entry(sk.id, slot);
      if (g === null) continue;
      const status = GRID_STATUS[g.status] as string;
      const label = `slot ${slot} sketch ${sk.id}`;
      if (status !== "sat" && status !== "unsat") {
        tally.cases += 1;
        tally.not_comparable += 1;
        tally.notes.push(`${label}: engine status ${status}`);
        continue;
      }
      const names = grid.holeNames(sk.id);
      const violated = g.violated === null ? [] : grid.violatedIds(g.violated);
      const ref: Reference = {
        source: "engine", status, holes: g.holes === null ? null : Object.fromEntries(names.map((n, k) => [n, g.holes![k] as number])),
        margin: g.margin, violated, violatedWeight: sumWeights(ex, violated), placement: g.placement,
      };
      const z = await solveCase(api, sk.rule, ex, opts.timeoutMs ?? 20_000, tally, label, ref.holes);
      if (z === null) continue;
      const v = compareWithReference(z, ref);
      let kind = v.kind;
      let detail = v.differences.join("; ");
      if (kind === "equal_optimum" && g.alternatives === 1) {
        kind = "differs"; // the engine's tie count says its optimum is unique, so another violated set cannot be optimal
        detail = `engine says the optimum is unique (alternatives 1); ${detail}`;
      }
      record(tally, kind, label, detail);
    }
    opts.onSlot?.(slot, tally);
  }
  return tally;
}
