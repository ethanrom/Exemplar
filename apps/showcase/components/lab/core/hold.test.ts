// The number line of chapter 3 is derived from the DSL evaluator; these tests pin it to the exported data.
import assert from "node:assert/strict";
import { test } from "node:test";
import { loadRule, loadRun, loadTrace } from "../../../lib/data/load.ts";
import { clipLength, gridPoints, holdBox, holdTicks, holdsForShape, placeD, scoreAt } from "./hold.ts";
import type { HoldExample } from "./hold.ts";
import { parseCached } from "./rules.ts";

function p1() {
  const run = loadRun("p1-playground");
  const rule = loadRule("package-deployed");
  const sketch = parseCached(rule.sketch_text);
  const examples: HoldExample[] = run.examples.map((e) => ({ alias: e.alias, label: e.label, weight: e.weight, trace: loadTrace(e.alias) }));
  return { run, rule, sketch, examples };
}

test("the package sketch is a one-hole holds_for", () => {
  const { sketch } = p1();
  assert.equal(holdsForShape(sketch)?.hole, "d");
});

test("P1: the TS-derived range of d equals the engine's exported box", () => {
  const { rule, sketch, examples } = p1();
  const ticks = holdTicks(sketch, examples, rule.margin);
  const box = holdBox(ticks, new Set(examples.filter((e) => !rule.violations.includes(e.alias)).map((e) => e.alias)), clipLength(examples));
  const exported = (rule.box as Record<string, [number, number]>).d;
  assert.ok(Math.abs(box.lo - exported[0]) < 1e-9, `lo ${box.lo} vs ${exported[0]}`);
  assert.ok(Math.abs(box.hi - exported[1]) < 1e-9, `hi ${box.hi} vs ${exported[1]}`);
  const placed = placeD(box);
  assert.equal(placed.snapped, rule.holes.d);
});

test("P1: every example's score flips exactly where its tick says (0.5 s sweep against robustness)", () => {
  const { rule, sketch, examples } = p1();
  const ticks = holdTicks(sketch, examples, 0); // margin 0: plain "body is true" runs
  for (const ex of examples) {
    const tick = ticks.find((t) => t.alias === ex.alias)!;
    for (const d of gridPoints(0, 40, 0.5)) {
      const s = scoreAt(sketch, ex, d).score;
      if (tick.sup === null) {
        assert.ok(s <= 0, `${ex.alias} d=${d}`);
        continue;
      }
      const holds = tick.closed ? d <= tick.sup : d < tick.sup;
      assert.equal(s > 0, holds, `${ex.alias} d=${d} score ${s} sup ${tick.sup} closed ${tick.closed}`);
    }
  }
  assert.ok(rule.margin > 0);
});

test("P1: at the recorded d every example is on its labelled side with the recorded margin", () => {
  const { rule, sketch, examples } = p1();
  const d = rule.holes.d as number;
  let margin = Infinity;
  for (const ex of examples) {
    const s = scoreAt(sketch, ex, d);
    assert.ok(s.right, ex.alias);
    margin = Math.min(margin, Math.abs(s.score));
  }
  assert.ok(Math.abs(margin - rule.margin) < 1e-9);
});
