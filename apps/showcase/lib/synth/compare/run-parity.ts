// Command line: parity of the free-play pipeline against data/grid/grid.json.gz over a range of valid slots.
//
//   node lib/synth/compare/run-parity.ts [--from i] [--to j] [--stride n] [--out file.json]
//
// i, j index the list of valid slots (6,050 of them); the summary goes to stdout and, with --out, to a file so that
// several processes can each take a range and be merged.

import { readFileSync, writeFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";

import { Grid } from "./grid.ts";
import { checkSlot } from "./parity.ts";
import type { SlotReport } from "./parity.ts";
import { isValid, statesOf } from "../session.ts";
import type { LabData } from "../session.ts";

const here = new URL("../../../data/grid/", import.meta.url);
const arg = (name: string, d: number): number => {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? Number(process.argv[i + 1]) : d;
};
const outIx = process.argv.indexOf("--out");
const out = outIx >= 0 ? (process.argv[outIx + 1] as string) : null;

const grid = new Grid(JSON.parse(gunzipSync(readFileSync(new URL("grid.json.gz", here))).toString("utf-8")));
const sketches = JSON.parse(readFileSync(new URL("sketches.json", here), "utf-8")) as { id: number; text: string }[];
const traces = JSON.parse(gunzipSync(readFileSync(new URL("golden/traces.json.gz", here))).toString("utf-8")).traces;
const data: LabData = { curated: grid.clips.map((a) => ({ alias: a, trace: traces[a] })), sketches };

const valid: number[] = [];
for (let s = 0; s < grid.doc.slots; s++) if (isValid(statesOf(s, grid.clips.length))) valid.push(s);
const from = arg("from", 0);
const to = Math.min(arg("to", valid.length), valid.length);
const stride = arg("stride", 1);

const total = {
  slots: 0, entries: 0, identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0, missing: 0,
  top6_same: 0, top6_explained: 0, top6_mismatch: 0, top6_missing: 0, mdl_checked: 0, mdl_mismatch: 0, alt_checked: 0, alt_mismatch: 0, ms: 0, max_slot_ms: 0,
  max_classes: 0,
  engine_supplied_by_sketch: {} as Record<string, number>, tie_verified_by_sketch: {} as Record<string, number>,
  problems: [] as string[],
};
for (let i = from; i < to; i += stride) {
  const slot = valid[i] as number;
  if (grid.top6(slot) === null) {
    total.missing += 1;
    continue;
  }
  const r: SlotReport = checkSlot(grid, data, slot);
  total.slots += 1;
  total.entries += r.perSketch.length;
  total.identical += r.categories.identical;
  total.tie_verified += r.categories.tie_verified;
  total.engine_supplied += r.categories.engine_supplied;
  total.mismatch += r.categories.mismatch;
  total[`top6_${r.top6}` as "top6_same"] += 1;
  total.mdl_checked += r.mdlChecked;
  total.mdl_mismatch += r.mdlMismatch;
  total.alt_checked += r.altChecked;
  total.alt_mismatch += r.altMismatch;
  total.ms += r.ms;
  total.max_slot_ms = Math.max(total.max_slot_ms, r.ms);
  total.max_classes = Math.max(total.max_classes, r.maxClasses);
  r.perSketch.forEach((c, sid) => {
    if (c === "engine_supplied") total.engine_supplied_by_sketch[sid] = (total.engine_supplied_by_sketch[sid] ?? 0) + 1;
    if (c === "tie_verified") total.tie_verified_by_sketch[sid] = (total.tie_verified_by_sketch[sid] ?? 0) + 1;
  });
  for (const p of r.problems) if (total.problems.length < 50) total.problems.push(`slot ${slot}: ${p}`);
}
const text = JSON.stringify(total, null, 1);
if (out !== null) writeFileSync(out, text);
console.log(text);
