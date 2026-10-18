// SPEC 6.5: the solver must never read the grid's expected outputs. This walks the import graph of everything outside
// the comparator (lib/synth/compare/**), the tests and the test helpers, and fails if any of it reaches the
// comparator, the grid decoder, a recorded run or rule file, or a data file; it also keeps the solver pure (no node:
// or DOM imports) and keeps lib/dsl free of any import from lib/synth.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

const importsOf = (file: string): string[] => {
  const src = readFileSync(file, "utf-8");
  const out: string[] = [];
  for (const m of src.matchAll(/(?:^|\n)\s*(?:import|export)\s[^;]*?from\s+["']([^"']+)["']/g)) out.push(m[1] as string);
  for (const m of src.matchAll(/(?:^|\n)\s*import\s+["']([^"']+)["']/g)) out.push(m[1] as string);
  for (const m of src.matchAll(/\bimport\(\s*["']([^"']+)["']\s*\)/g)) out.push(m[1] as string);
  return out;
};

const solverFiles = readdirSync(here)
  .filter((f) => f.endsWith(".ts") && !f.endsWith(".test.ts") && f !== "testutil.ts")
  .map((f) => join(here, f));

test("solver files do not import the comparator, the grid, recorded data or node built-ins", () => {
  assert.ok(solverFiles.length >= 8);
  for (const f of solverFiles) {
    for (const spec of importsOf(f)) {
      assert.ok(!/(^|\/)compare(\/|$)/.test(spec), `${f} imports the comparator: ${spec}`);
      assert.ok(!/grid|golden|\/data\/|public\/data|recorded|\.json/i.test(spec), `${f} imports data: ${spec}`);
      assert.ok(!spec.startsWith("node:"), `${f} imports a node built-in: ${spec}`);
      if (spec.startsWith(".")) {
        const target = resolve(dirname(f), spec);
        const ok = target.startsWith(here) || /[\\/]lib[\\/]dsl[\\/][^\\/]+\.ts$/.test(target);
        assert.ok(ok, `${f} reaches outside lib/synth and lib/dsl: ${spec}`);
        assert.ok(!/[\\/]lib[\\/](data|compare)[\\/]/.test(target), `${f} imports ${spec}`);
      } else {
        assert.fail(`${f} has a bare import (no runtime dependencies allowed): ${spec}`);
      }
    }
  }
});

test("the worker session is part of the solver graph and never touches the grid", () => {
  const code = readFileSync(join(here, "session.ts"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  assert.ok(!/compare\//.test(code));
  assert.ok(!/grid\.json|closed\.json|sketches\.json/.test(code));
});

test("lib/dsl does not import lib/synth", () => {
  const dsl = resolve(here, "..", "dsl");
  for (const f of readdirSync(dsl).filter((x) => x.endsWith(".ts"))) {
    for (const spec of importsOf(join(dsl, f))) assert.ok(!/synth/.test(spec), `${f} imports ${spec}`);
  }
});
