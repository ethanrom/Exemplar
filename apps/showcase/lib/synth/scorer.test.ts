// The memoised point scorer is bit-identical to the DSL evaluator (`CompiledRule.score`) at every hole point.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";

import { compileRule, holesOf, parse, prepare } from "../dsl/index.ts";
import { exampleGeometry, holeClasses } from "./classes.ts";
import { PointScorer } from "./scorer.ts";

const dir = new URL("../../data/grid/", import.meta.url);
const traces = JSON.parse(gunzipSync(readFileSync(new URL("golden/traces.json.gz", dir))).toString("utf-8")).traces;
const sketches = JSON.parse(readFileSync(new URL("sketches.json", dir), "utf-8")) as { id: number; text: string }[];
const clips = JSON.parse(readFileSync(new URL("curated.json", dir), "utf-8")).clips as string[];

test("PointScorer == CompiledRule.score on random class points of every sketch", () => {
  const preps = clips.map((a) => prepare(traces[a]));
  const geo = exampleGeometry(preps);
  let n = 0;
  let seed = 12345;
  const rnd = (m: number): number => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed % m;
  };
  for (const s of sketches) {
    const sketch = parse(s.text);
    const names = holesOf(sketch);
    const cls = holeClasses(sketch, names, geo);
    const scorer = new PointScorer(sketch, preps, names, cls.reps.map((r) => r.length));
    const cr = compileRule(sketch);
    for (let it = 0; it < 150; it++) {
      const idx = new Int32Array(names.length);
      const vals = new Float64Array(names.length);
      const holes: Record<string, number> = {};
      names.forEach((nm, h) => {
        idx[h] = rnd((cls.reps[h] as Float64Array).length);
        vals[h] = (cls.reps[h] as Float64Array)[idx[h] as number] as number;
        holes[nm] = vals[h] as number;
      });
      scorer.setPoint(idx, vals);
      for (let k = 0; k < preps.length; k++) {
        const a = scorer.score(k);
        const b = cr.score(preps[k]!, holes);
        n += 1;
        assert.ok(a === b, `sketch ${s.id} clip ${k} point ${JSON.stringify(holes)}: ${a} vs ${b}`);
      }
    }
  }
  console.log(`scorer: ${n} scores identical to the evaluator`);
});
