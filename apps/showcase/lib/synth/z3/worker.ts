// Web Worker entry that hosts Z3 (z3-solver 5.3.1, WebAssembly). Bundled by esbuild (scripts/z3/prebuild.mjs) into a
// CLASSIC worker script, /z3/5.3.1/z3-worker.<hash>.js: z3-built.js must stay its own script, because Emscripten starts
// its pthread workers from that same file, and a module worker cannot call importScripts().
//
// Protocol (protocol.ts): { cmd: "init" } -> { type: "ready" } after one warm-up solve; { cmd: "check", examples, jobs }
// -> one { type: "item" } per sketch, then { type: "done" }; { cmd: "cancel" } abandons the request at the next
// check-point (between Z3 calls). Requests run one at a time; every reply carries the request_id it answers.
//
// Nothing here reads the grid or any recorded result: it solves what it is sent (SPEC 6.5).

import { init } from "z3-solver/build/browser.js";
import { DSLError, parse, typecheck } from "../../dsl/index.ts";
import type { Rule, Trace } from "../../dsl/index.ts";
import { holeKinds } from "../classes.ts";
import { Cancelled, SketchError, makeExample } from "../types.ts";
import type { Example } from "../types.ts";
import type { ReadyInfo, WireExample, Z3Message, Z3Outcome, Z3Request } from "./protocol.ts";
import { Z3_VERSION } from "./protocol.ts";
import { EncoderMismatch, solveSketchZ3 } from "./solve.ts";
import type { Z3Api } from "./solve.ts";

declare function importScripts(...urls: string[]): void;

interface WorkerScope {
  postMessage(m: Z3Message): void;
  onmessage: ((ev: { data: Z3Request }) => void) | null;
  location: { href: string };
  crossOriginIsolated: boolean;
}
const scope = globalThis as unknown as WorkerScope;

/** Per-sketch Z3 budget; the placement step takes what is left of it (at least 1 s), so a sketch stays well under the page's 15 s watchdog. */
const DEFAULT_SOLVE_TIMEOUT_MS = 6000;

let api: Z3Api | null = null;
const cancelled = new Set<number>();

const post = (m: Z3Message): void => scope.postMessage(m);

// ------------------------------------------------------------------------------------------------ warm-up
const warmTrace = (id: string, frames: number): Trace => ({
  clip_id: id, status: "ok", duration_ms: frames * 1000, entities: [{ id: "k1", type: "package" }],
  frames: Array.from({ length: frames }, (_, i) => ({ t_ms: i * 1000, facts: [{ pred: "in_zone", args: ["k1", "steps"], conf: "high" as const }] })),
});

/** One real solve through the whole path (encoder, MaxSMT, margin levels, hole box, placement, differential check). */
async function warmUp(z: Z3Api): Promise<void> {
  const sketch = parse("exists k: Package: holds_for >= ?d in_zone(k, steps)");
  const ex = [makeExample(warmTrace("warm-pos", 10), true, 3, "warm-pos"), makeExample(warmTrace("warm-neg", 3), false, 3, "warm-neg")];
  const r = await solveSketchZ3(z, sketch, ex, { timeoutMs: 10_000 });
  const d = r.holes.d;
  if (r.status !== "sat" || typeof d !== "number" || !(d > 2 && d <= 9)) {
    throw new Error(`the Z3 self-test gave an unexpected answer (${r.status}, ${JSON.stringify(r.holes)})`);
  }
}

// ------------------------------------------------------------------------------------------------ requests
async function handleInit(m: Extract<Z3Request, { cmd: "init" }>): Promise<void> {
  const t0 = performance.now();
  if (typeof SharedArrayBuffer === "undefined" || scope.crossOriginIsolated !== true) {
    throw new Error("this page is not cross-origin isolated (no SharedArrayBuffer), so Z3 cannot start");
  }
  const base = m.base ?? scope.location.href.replace(/[?#].*$/, "").replace(/[^/]*$/, "");
  importScripts(`${base}z3-built.js`);
  const t1 = performance.now();
  const z3 = await init({ locateFile: (file: string) => base + file, mainScriptUrlOrBlob: `${base}z3-built.js` });
  const t2 = performance.now();
  // ONE long-lived context: z3-solver frees a context only when the JS garbage collector finalises it, which never
  // happens in time to protect the fixed 2 GB WebAssembly heap (see solve.ts, Z3Api).
  const ctx = new z3.Context("main");
  api = { context: () => ctx };
  await warmUp(api);
  const t3 = performance.now();
  const info: ReadyInfo = {
    importMs: t1 - t0, initMs: t2 - t1, warmupMs: t3 - t2, totalMs: t3 - t0, z3Version: Z3_VERSION, crossOriginIsolated: scope.crossOriginIsolated,
  };
  post({ type: "ready", request_id: m.request_id, info });
}

function parseSketch(text: string): Rule | string {
  let rule: Rule;
  try {
    rule = parse(text.trim());
  } catch (e) {
    if (e instanceof DSLError) return `the sketch does not parse: ${e.message}`;
    throw e;
  }
  const errs = typecheck(rule);
  if (errs.length > 0) return `the sketch does not typecheck: ${errs.join("; ")}`;
  try {
    holeKinds(rule);
  } catch (e) {
    if (e instanceof SketchError) return e.message;
    throw e;
  }
  return rule;
}

async function solveOne(
  text: string, examples: readonly Example[], id: number, timeoutMs: number, referenceHoles?: Readonly<Record<string, number>>,
): Promise<Z3Outcome> {
  const sketch = parseSketch(text);
  if (typeof sketch === "string") return { kind: "unsupported", reason: sketch };
  try {
    const result = await solveSketchZ3(api as Z3Api, sketch, examples, { timeoutMs, isCancelled: () => cancelled.has(id), referenceHoles });
    return { kind: "solved", result };
  } catch (e) {
    if (e instanceof Cancelled) throw e;
    if (e instanceof SketchError) return { kind: "unsupported", reason: e.message };
    if (e instanceof EncoderMismatch) return { kind: "error", message: e.message };
    return { kind: "error", message: e instanceof Error ? e.message : String(e) };
  }
}

async function handleCheck(m: Extract<Z3Request, { cmd: "check" }>): Promise<void> {
  if (api === null) throw new Error("Z3 is not initialised");
  const t0 = performance.now();
  const examples: Example[] = m.examples.map((e: WireExample) => makeExample(e.trace, e.positive, e.weight, e.clip_id));
  for (const job of m.jobs) {
    if (cancelled.has(m.request_id)) return;
    let outcome: Z3Outcome;
    try {
      outcome = await solveOne(job.sketch, examples, m.request_id, m.timeoutMs ?? DEFAULT_SOLVE_TIMEOUT_MS, job.referenceHoles);
    } catch (e) {
      if (e instanceof Cancelled) return;
      throw e;
    }
    if (cancelled.has(m.request_id)) return;
    post({ type: "item", request_id: m.request_id, key: job.key, outcome });
  }
  post({ type: "done", request_id: m.request_id, ms: performance.now() - t0 });
}

// Requests run one at a time, in arrival order; `cancel` is handled at once so a running request notices it.
let chain: Promise<void> = Promise.resolve();
scope.onmessage = (ev) => {
  const m = ev.data;
  if (m.cmd === "cancel") {
    cancelled.add(m.request_id);
    return;
  }
  chain = chain
    .then(() => (m.cmd === "init" ? handleInit(m) : handleCheck(m)))
    .catch((e: unknown) => {
      post({ type: "error", request_id: m.request_id, message: e instanceof Error ? e.message : String(e) });
    });
};
