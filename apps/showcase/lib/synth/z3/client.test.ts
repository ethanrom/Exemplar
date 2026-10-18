// The page side of the Z3 worker, against a fake worker: one worker, request ids, stale replies, the watchdog, worker errors,
// termination and restart. No Z3 and no DOM are involved.
import { test } from "node:test";
import assert from "node:assert/strict";
import { RECYCLE_AFTER_SOLVES, Z3Cancelled, Z3Client, Z3Failure } from "./client.ts";
import type { WorkerLike } from "./client.ts";
import type { ReadyInfo, Z3Message, Z3Outcome, Z3Request } from "./protocol.ts";

const READY: ReadyInfo = { importMs: 1, initMs: 2, warmupMs: 3, totalMs: 6, z3Version: "5.3.1", crossOriginIsolated: true };
const UNSUPPORTED: Z3Outcome = { kind: "unsupported", reason: "x" };
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

class FakeWorker implements WorkerLike {
  sent: Z3Request[] = [];
  terminated = 0;
  onmessage: WorkerLike["onmessage"] = null;
  onerror: WorkerLike["onerror"] = null;
  onmessageerror: WorkerLike["onmessageerror"] = null;
  postMessage(m: Z3Request): void {
    this.sent.push(m);
  }
  terminate(): void {
    this.terminated += 1;
  }
  emit(m: Z3Message): void {
    this.onmessage?.({ data: m });
  }
  last<T extends Z3Request["cmd"]>(cmd: T): Extract<Z3Request, { cmd: T }> {
    return [...this.sent].reverse().find((m) => m.cmd === cmd) as Extract<Z3Request, { cmd: T }>;
  }
}

function setup(opts: { initTimeoutMs?: number; requestTimeoutMs?: number } = {}) {
  const workers: FakeWorker[] = [];
  let urls: string[] = [];
  const client = new Z3Client({
    workerUrl: "/z3/5.3.1/z3-worker.abc.js",
    createWorker: (url) => {
      urls.push(url);
      const w = new FakeWorker();
      workers.push(w);
      return w;
    },
    ...opts,
  });
  return { client, workers, urls: () => urls };
}

async function ready(s: ReturnType<typeof setup>): Promise<FakeWorker> {
  const p = s.client.start();
  const w = s.workers[s.workers.length - 1] as FakeWorker;
  w.emit({ type: "ready", request_id: w.last("init").request_id, info: READY });
  await p;
  return w;
}

test("nothing is created until start(); start() creates exactly one worker, however often it is called", async () => {
  const s = setup();
  assert.equal(s.workers.length, 0);
  assert.equal(s.client.getState().phase, "idle");
  const a = s.client.start();
  const b = s.client.start();
  assert.equal(a, b);
  assert.equal(s.workers.length, 1);
  assert.deepEqual(s.urls(), ["/z3/5.3.1/z3-worker.abc.js"]);
  assert.equal(s.client.getState().phase, "loading");
  const w = s.workers[0] as FakeWorker;
  w.emit({ type: "ready", request_id: w.last("init").request_id, info: READY });
  assert.deepEqual(await a, READY);
  assert.equal(s.client.getState().phase, "ready");
  await s.client.start(); // still the same worker
  assert.equal(s.workers.length, 1);
  assert.equal(s.client.workersCreated, 1);
});

test("a check carries a request_id, delivers each item and resolves when done", async () => {
  const s = setup();
  const w = await ready(s);
  const got: string[] = [];
  const h = s.client.check({ examples: [], jobs: [{ key: "a", sketch: "s1" }, { key: "b", sketch: "s2" }] }, (k) => got.push(k));
  const req = w.last("check");
  assert.equal(req.request_id, h.request_id);
  assert.deepEqual(req.jobs.map((j) => j.key), ["a", "b"]);
  w.emit({ type: "item", request_id: h.request_id, key: "a", outcome: UNSUPPORTED });
  w.emit({ type: "item", request_id: h.request_id, key: "b", outcome: UNSUPPORTED });
  w.emit({ type: "done", request_id: h.request_id, ms: 12 });
  assert.deepEqual(await h.done, { ms: 12 });
  assert.deepEqual(got, ["a", "b"]);
});

test("request ids increase, and a reply for any other request is dropped", async () => {
  const s = setup();
  const w = await ready(s);
  const got: string[] = [];
  const h1 = s.client.check({ examples: [], jobs: [{ key: "old", sketch: "s" }] }, (k) => got.push(k));
  const h2 = s.client.check({ examples: [], jobs: [{ key: "new", sketch: "s" }] }, (k) => got.push(k));
  assert.ok(h2.request_id > h1.request_id);
  await assert.rejects(h1.done, Z3Cancelled);
  assert.deepEqual(w.sent.filter((m) => m.cmd === "cancel").map((m) => m.request_id), [h1.request_id]);
  w.emit({ type: "item", request_id: h1.request_id, key: "old", outcome: UNSUPPORTED }); // a late reply to the superseded request
  w.emit({ type: "item", request_id: 9999, key: "bogus", outcome: UNSUPPORTED });
  w.emit({ type: "item", request_id: h2.request_id, key: "new", outcome: UNSUPPORTED });
  w.emit({ type: "done", request_id: h2.request_id, ms: 1 });
  await h2.done;
  assert.deepEqual(got, ["new"]);
});

test("cancel() drops the running check and tells the worker", async () => {
  const s = setup();
  const w = await ready(s);
  const h = s.client.check({ examples: [], jobs: [{ key: "a", sketch: "s" }] }, () => assert.fail("no item may arrive"));
  h.cancel();
  await assert.rejects(h.done, Z3Cancelled);
  assert.equal(w.last("cancel").request_id, h.request_id);
  w.emit({ type: "item", request_id: h.request_id, key: "a", outcome: UNSUPPORTED });
  assert.equal(s.client.getState().phase, "ready"); // cancelling is not a failure
});

test("a check before the worker is ready is refused, not queued", async () => {
  const s = setup();
  const h = s.client.check({ examples: [], jobs: [] }, () => {});
  await assert.rejects(h.done, Z3Failure);
  assert.equal(s.workers.length, 0);
});

test("watchdog: a silent worker is terminated, the check fails with a plain message, the client is restartable", async () => {
  const s = setup({ requestTimeoutMs: 40 });
  const w = await ready(s);
  const h = s.client.check({ examples: [], jobs: [{ key: "a", sketch: "s" }] }, () => {});
  await assert.rejects(h.done, (e: Error) => e instanceof Z3Failure && /stopped responding for/.test(e.message));
  assert.equal(w.terminated, 1);
  const st = s.client.getState();
  assert.equal(st.phase, "failed");
  assert.match(st.failure ?? "", /stopped responding/);
  const w2 = await ready(s); // "Try again": a new worker
  assert.equal(s.workers.length, 2);
  assert.notEqual(w2, w);
  assert.equal(s.client.getState().phase, "ready");
});

test("watchdog: progress (an item) restarts the clock", async () => {
  const s = setup({ requestTimeoutMs: 60 });
  const w = await ready(s);
  const h = s.client.check({ examples: [], jobs: [{ key: "a", sketch: "s" }, { key: "b", sketch: "s" }, { key: "c", sketch: "s" }] }, () => {});
  for (const k of ["a", "b", "c"]) {
    await sleep(40);
    w.emit({ type: "item", request_id: h.request_id, key: k, outcome: UNSUPPORTED });
  }
  w.emit({ type: "done", request_id: h.request_id, ms: 120 });
  await h.done; // 120 ms in total, never 60 ms of silence
  assert.equal(w.terminated, 0);
});

test("watchdog: a worker that never becomes ready is terminated after the longer start-up allowance", async () => {
  const s = setup({ initTimeoutMs: 40 });
  const p = s.client.start();
  await assert.rejects(p, Z3Failure);
  assert.equal((s.workers[0] as FakeWorker).terminated, 1);
  assert.equal(s.client.getState().phase, "failed");
});

test("worker.onerror (a script or wasm that fails to load) fails the client and terminates the worker", async () => {
  const s = setup();
  const p = s.client.start();
  const w = s.workers[0] as FakeWorker;
  w.onerror?.({ message: "Failed to load /z3/5.3.1/z3-built.js" });
  await assert.rejects(p, (e: Error) => e instanceof Z3Failure && /failed to load/i.test(e.message));
  assert.equal(w.terminated, 1);
  assert.match(s.client.getState().failure ?? "", /Failed to load/);
});

test("worker.onerror during a check fails that check", async () => {
  const s = setup();
  const w = await ready(s);
  const h = s.client.check({ examples: [], jobs: [{ key: "a", sketch: "s" }] }, () => {});
  w.onerror?.({ message: "out of memory" });
  await assert.rejects(h.done, Z3Failure);
  assert.equal(s.client.getState().phase, "failed");
  assert.equal(w.terminated, 1);
});

test("an error message from the worker for the current request fails the client", async () => {
  const s = setup();
  const p = s.client.start();
  const w = s.workers[0] as FakeWorker;
  w.emit({ type: "error", request_id: w.last("init").request_id, message: "this page is not cross-origin isolated" });
  await assert.rejects(p, /could not start: this page is not cross-origin isolated/);
  assert.equal(s.client.getState().phase, "failed");
});

test("a worker that cannot be created fails the client without throwing", async () => {
  const client = new Z3Client({ workerUrl: "/x.js", createWorker: () => { throw new Error("blocked by the content security policy"); } });
  await assert.rejects(client.start(), /blocked by the content security policy/);
  assert.equal(client.getState().phase, "failed");
});

test("dispose() terminates the worker (memory released) and a later start() makes a new one", async () => {
  const s = setup();
  const w = await ready(s);
  const h = s.client.check({ examples: [], jobs: [{ key: "a", sketch: "s" }] }, () => {});
  s.client.dispose();
  await assert.rejects(h.done, Z3Cancelled);
  assert.equal(w.terminated, 1);
  assert.equal(s.client.getState().phase, "idle");
  const w2 = await ready(s);
  assert.notEqual(w2, w);
  assert.equal(s.client.workersCreated, 2);
});

test("subscribers hear every state change", async () => {
  const s = setup();
  const phases: string[] = [];
  const off = s.client.subscribe(() => phases.push(s.client.getState().phase));
  await ready(s);
  s.client.dispose();
  off();
  s.client.dispose();
  assert.deepEqual(phases, ["loading", "ready", "idle"]);
});

test("after many solves the page recycles the worker before the next check", async () => {
  const s = setup();
  const w = await ready(s);
  assert.equal(s.client.needsRecycle(), false);
  const jobs = Array.from({ length: RECYCLE_AFTER_SOLVES }, (_, i) => ({ key: `k${i}`, sketch: "s" }));
  const h = s.client.check({ examples: [], jobs }, () => {});
  for (const j of jobs) w.emit({ type: "item", request_id: h.request_id, key: j.key, outcome: UNSUPPORTED });
  w.emit({ type: "done", request_id: h.request_id, ms: 1 });
  await h.done;
  assert.equal(s.client.needsRecycle(), true);
  const p = s.client.recycle();
  const w2 = s.workers[1] as FakeWorker;
  assert.equal(w.terminated, 1);
  w2.emit({ type: "ready", request_id: w2.last("init").request_id, info: READY });
  await p;
  assert.equal(s.client.needsRecycle(), false);
  assert.equal(s.client.getState().phase, "ready");
});
