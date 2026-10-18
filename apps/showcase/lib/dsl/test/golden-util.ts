// Golden-file helpers: read the engine's .jsonl.gz goldens and compare with the frozen semantics of SPEC 6.3.
//
//   * numbers are compared with ===  (so +0 and -0 are equal, like Python's ==);
//   * NaN or +-Infinity anywhere, on either side, is a failure;
//   * objects must have the same keys, arrays the same length and order.

import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";

const GOLDEN_DIR = fileURLToPath(new URL("./golden/", import.meta.url));

export interface GoldenMeta {
  family: string;
  generator: string;
  engine_commit: string;
  seed: number | null;
  count: number;
  [k: string]: unknown;
}
export interface GoldenRow {
  id: string;
  // Golden payloads are free-form JSON produced by the engine; each family test knows its own shape.
  input: any;
  expect: any;
}

export function goldenPath(name: string): string {
  return GOLDEN_DIR + name;
}

export function readJsonlGz(name: string): { meta: GoldenMeta; rows: GoldenRow[] } {
  const text = gunzipSync(readFileSync(goldenPath(name))).toString("utf8");
  const lines = text.split("\n").filter((l) => l.length > 0);
  const meta = JSON.parse(lines[0]) as GoldenMeta;
  const rows = lines.slice(1).map((l) => JSON.parse(l) as GoldenRow);
  if (rows.length !== meta.count) throw new Error(`${name}: meta.count ${meta.count} but ${rows.length} rows`);
  return { meta, rows };
}

export function readJsonGz<T = unknown>(name: string): T {
  return JSON.parse(gunzipSync(readFileSync(goldenPath(name))).toString("utf8")) as T;
}

/** First difference between two JSON-like values under the SPEC 6.3 rules, or null when identical. */
export function diff(got: unknown, want: unknown, path = "$"): string | null {
  if (typeof got === "number" || typeof want === "number") {
    if (typeof got !== "number" || typeof want !== "number") return `${path}: ${show(got)} vs ${show(want)}`;
    if (!Number.isFinite(got) || !Number.isFinite(want)) return `${path}: non-finite number (${got} vs ${want})`;
    return got === want ? null : `${path}: ${got} !== ${want}`;
  }
  if (got === null || want === null || typeof got !== "object" || typeof want !== "object") {
    return got === want ? null : `${path}: ${show(got)} !== ${show(want)}`;
  }
  if (Array.isArray(got) || Array.isArray(want)) {
    if (!Array.isArray(got) || !Array.isArray(want)) return `${path}: array vs non-array`;
    if (got.length !== want.length) return `${path}: length ${got.length} !== ${want.length}`;
    for (let i = 0; i < got.length; i++) {
      const d = diff(got[i], want[i], `${path}[${i}]`);
      if (d !== null) return d;
    }
    return null;
  }
  const g = got as Record<string, unknown>;
  const w = want as Record<string, unknown>;
  const gk = Object.keys(g).filter((k) => g[k] !== undefined).sort();
  const wk = Object.keys(w).filter((k) => w[k] !== undefined).sort();
  if (gk.join("\u0000") !== wk.join("\u0000")) return `${path}: keys [${gk}] !== [${wk}]`;
  for (const k of wk) {
    const d = diff(g[k], w[k], `${path}.${k}`);
    if (d !== null) return d;
  }
  return null;
}

function show(x: unknown): string {
  const s = JSON.stringify(x);
  return s === undefined ? String(x) : s.length > 120 ? s.slice(0, 117) + "..." : s;
}
