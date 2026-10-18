// SPEC 6.5 for the Z3 path: the solver files must not read the grid, the goldens, recorded runs or the comparator, must not
// use node: built-ins (they run in a Web Worker), and the page must never import z3-solver itself (only the worker bundle does,
// and only types elsewhere). The Node-only harness files (tests, testutil.ts, parity.ts) are exempt.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const synth = resolve(here, "..");
const dsl = resolve(synth, "..", "dsl");

const importsOf = (file: string): { spec: string; typeOnly: boolean }[] => {
  const src = readFileSync(file, "utf-8");
  const out: { spec: string; typeOnly: boolean }[] = [];
  for (const m of src.matchAll(/(?:^|\n)\s*(import|export)\s+(type\s+)?[^;]*?from\s+["']([^"']+)["']/g)) {
    out.push({ spec: m[3] as string, typeOnly: m[2] !== undefined });
  }
  for (const m of src.matchAll(/(?:^|\n)\s*import\s+["']([^"']+)["']/g)) out.push({ spec: m[1] as string, typeOnly: false });
  for (const m of src.matchAll(/\bimport\(\s*["']([^"']+)["']\s*\)/g)) out.push({ spec: m[1] as string, typeOnly: false });
  return out;
};

const exempt = (f: string): boolean => f.endsWith(".test.ts") || f === "testutil.ts" || f === "parity.ts";
const files = readdirSync(here).filter((f) => f.endsWith(".ts") && !exempt(f));

test("the Z3 solver files do not reach the comparator, the grid, recorded data or node built-ins", () => {
  assert.ok(files.length >= 8, `found ${files.join(", ")}`);
  for (const f of files) {
    for (const { spec, typeOnly } of importsOf(join(here, f))) {
      assert.ok(!/(^|\/)compare(\/|$)/.test(spec), `${f} imports the comparator: ${spec}`);
      assert.ok(!/grid|golden|\/data\/|public\/data|recorded|\.json/i.test(spec), `${f} imports data: ${spec}`);
      assert.ok(!spec.startsWith("node:"), `${f} imports a node built-in: ${spec}`);
      if (spec.startsWith(".")) {
        const target = resolve(here, spec);
        const ok = target.startsWith(here) || target.startsWith(synth) || (target.startsWith(dsl) && /[\\/]dsl[\\/][^\\/]+\.ts$/.test(target));
        assert.ok(ok, `${f} reaches outside lib/synth and lib/dsl: ${spec}`);
        assert.ok(!/[\\/]lib[\\/](data|compare)[\\/]/.test(target), `${f} imports ${spec}`);
      } else if (spec === "z3-solver" || spec.startsWith("z3-solver/")) {
        // types anywhere; a value import only in the worker entry (esbuild bundles it there, never webpack)
        assert.ok(typeOnly || f === "worker.ts", `${f} imports z3-solver as a value`);
      } else {
        assert.fail(`${f} has a bare import: ${spec}`);
      }
    }
  }
});

test("the page-side files do not import the worker or z3-solver values", () => {
  for (const f of ["client.ts", "capability.ts", "model.ts", "verdict.ts", "protocol.ts"]) {
    for (const { spec, typeOnly } of importsOf(join(here, f))) {
      assert.ok(!/worker/.test(spec), `${f} imports the worker: ${spec}`);
      assert.ok(typeOnly || !spec.startsWith("z3-solver"), `${f} imports z3-solver`);
    }
  }
});

test("the worker never reads the grid or any recorded result", () => {
  const code = readFileSync(join(here, "worker.ts"), "utf-8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  assert.ok(!/grid\.json|closed\.json|sketches\.json|compare\//.test(code));
});
