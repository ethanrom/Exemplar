// Test helpers shared by the node --test files of lib/synth (not imported by the library code).
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";

const HERE = new URL(".", import.meta.url);

export interface GoldenMeta {
  family: string;
  generator: string;
  engine_commit: string;
  seed: unknown;
  count: number;
  [k: string]: unknown;
}
export interface GoldenRecord {
  id: string;
  input: any;
  expect: any;
  [k: string]: any;
}

/** data/grid/golden/<family>.jsonl.gz: a meta line, then one record per line. */
export function readGolden(family: string): { meta: GoldenMeta; records: GoldenRecord[] } {
  const buf = readFileSync(new URL(`../../data/grid/golden/${family}.jsonl.gz`, HERE));
  const lines = gunzipSync(buf).toString("utf-8").split("\n").filter((l) => l.trim() !== "");
  return { meta: JSON.parse(lines[0] as string), records: lines.slice(1).map((l) => JSON.parse(l)) };
}

/** Any file below data/grid (gz or plain JSON). */
export function readGridJson(name: string): any {
  const buf = readFileSync(new URL(`../../data/grid/${name}`, HERE));
  return JSON.parse((name.endsWith(".gz") ? gunzipSync(buf) : buf).toString("utf-8"));
}

/** SPEC 6.3: finite numbers compare with ===; +0 and -0 are equal; NaN / Infinity anywhere is a failure. */
export function numEq(a: unknown, b: unknown): boolean {
  if (typeof a !== "number" || typeof b !== "number") return false;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  return a === b;
}

export function closeTo(a: number, b: number, rel: number, abs = 0): boolean {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  return Math.abs(a - b) <= Math.max(abs, rel * Math.max(Math.abs(a), Math.abs(b)));
}
