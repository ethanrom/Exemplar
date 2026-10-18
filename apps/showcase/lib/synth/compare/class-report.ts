// Per-sketch hole-class counts for the grid's example sets and the presets (SPEC 7.4: the class-count report).
//
//   node lib/synth/compare/class-report.ts
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";

import { holesOf, parse, prepare } from "../../dsl/index.ts";
import { exampleGeometry, holeClasses } from "../classes.ts";
import { MAX_CLASSES } from "../exhaustive.ts";
import { readGolden } from "../testutil.ts";

const dir = new URL("../../../data/grid/", import.meta.url);
const traces = JSON.parse(gunzipSync(readFileSync(new URL("golden/traces.json.gz", dir))).toString("utf-8")).traces;
const sketches = JSON.parse(readFileSync(new URL("sketches.json", dir), "utf-8")) as { id: number; text: string }[];
const clips = JSON.parse(readFileSync(new URL("curated.json", dir), "utf-8")).clips as string[];

const rows: Record<string, unknown>[] = [];
for (const s of sketches) {
  const sk = parse(s.text);
  const names = holesOf(sk);
  let max = 0;
  let over = 0;
  let subsets = 0;
  let full = 0;
  for (let U = 1; U < 1 << clips.length; U++) {
    const idx = clips.map((_, i) => i).filter((i) => (U >> i) & 1);
    if (idx.length < 2) continue;
    const geo = exampleGeometry(idx.map((i) => prepare(traces[clips[i] as string])));
    const p = holeClasses(sk, names, geo).product;
    subsets += 1;
    if (U === (1 << clips.length) - 1) full = p;
    max = Math.max(max, p);
    if (p > MAX_CLASSES) over += 1;
  }
  rows.push({ id: s.id, holes: names.length, classes_all_8_clips: full, max_over_subsets: max, subsets_over_budget: over, of_subsets: subsets });
}
const presets: Record<string, number[]> = {};
for (const r of readGolden("cegis.presets").records) {
  const geo = exampleGeometry(r.input.examples.map((e: any) => prepare(traces[e.alias])));
  presets[r.id] = sketches.map((s) => holeClasses(parse(s.text), holesOf(parse(s.text)), geo).product);
}
console.log(JSON.stringify({ budget: MAX_CLASSES, grid: rows, presets_class_product_per_sketch: presets }, null, 1));
