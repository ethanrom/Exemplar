import { test } from "node:test";
import assert from "node:assert/strict";

import { parse } from "../dsl/index.ts";
import { BITS_PER_NODE, mdl } from "./mdl.ts";
import { closeTo, readGolden } from "./testutil.ts";

test("F11 mdl: every closed rule, sketch and random rule against the engine", () => {
  const { meta, records } = readGolden("mdl");
  let bad = 0;
  for (const r of records) {
    const want = r.expect.mdl as number;
    const fromText = mdl(parse(r.input.dsl_text), r.input.violations);
    const fromAst = mdl(r.input.ast, r.input.violations);
    for (const [how, got] of [["text", fromText], ["ast", fromAst]] as const) {
      if (!closeTo(got, want, 1e-12)) {
        bad += 1;
        if (bad < 20) console.error(`MDL MISMATCH ${r.id} (${how}): ${got} vs ${want}`);
      }
    }
  }
  console.log(`F11 mdl: ${records.length} cases x 2 inputs (${meta.count} records), ${bad} mismatches`);
  assert.equal(bad, 0);
});

test("constants: log2(21) bits per node, bit-identical to Python", () => {
  assert.equal(BITS_PER_NODE, 4.392317422778761);
});
