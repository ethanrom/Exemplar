// Page side of the Z3 worker: starts exactly one worker on request, sends requests with a request_id, drops stale
// replies, watches for a hung or crashed worker and terminates it. No Z3 bytes are touched until `start()`.
//
// Failure never breaks the page: every failure ends the worker (`terminate()`), rejects what was pending with a
// `Z3Failure` carrying a plain message, and leaves the client restartable.
//
//   - `worker.onerror` (a missing wasm / pthread script arrives here, not as a rejected promise) fails the client;
//   - a watchdog fails the client when the worker is silent for `requestTimeoutMs` (15 s) while a request is pending;
//     the first request (download + start) gets the longer `initTimeoutMs`;
//   - a stale reply (an older request_id) is ignored;
//   - `dispose()` terminates the worker and frees its memory.
//
// Pure TypeScript (no DOM types beyond the minimal worker shape below) so Node can test it with a fake worker.

import type { ReadyInfo, WireExample, WireJob, Z3Message, Z3Outcome, Z3Request } from "./protocol.ts";

/** The part of `Worker` the client uses. */
export interface WorkerLike {
  postMessage(message: Z3Request): void;
  terminate(): void;
  onmessage: ((ev: { data: Z3Message }) => void) | null;
  onerror: ((ev: { message?: string }) => void) | null;
  onmessageerror?: ((ev: unknown) => void) | null;
}

export type Z3Phase = "idle" | "loading" | "ready" | "failed";

export interface Z3State {
  readonly phase: Z3Phase;
  /** Plain-language reason when phase is "failed", a fragment that completes "Z3 could not run here (...)". */
  readonly failure: string | null;
  readonly info: ReadyInfo | null;
}

/** A failure of the Z3 machinery (not of a sketch): the worker is gone, the page still works. */
export class Z3Failure extends Error {
  constructor(message: string) {
    super(message);
    this.name = "Z3Failure";
  }
}

/** The request was dropped (cancelled, superseded or the client was disposed). */
export class Z3Cancelled extends Error {
  constructor() {
    super("cancelled");
    this.name = "Z3Cancelled";
  }
}

export interface Z3ClientOptions {
  /** URL of the classic worker script, e.g. /z3/5.3.1/z3-worker.<hash>.js. */
  workerUrl: string;
  /** Default: `new Worker(url)`. A test passes a fake. */
  createWorker?: (url: string) => WorkerLike;
  /** Silence allowed while waiting for the worker to download and start (default 45 s). */
  initTimeoutMs?: number;
  /** Silence allowed while a check is running (default 15 s); reset by every reply. */
  requestTimeoutMs?: number;
}

export const INIT_TIMEOUT_MS = 45_000;
export const REQUEST_TIMEOUT_MS = 15_000;
/**
 * z3-solver never returns memory from its fixed 2 GB heap, and the heap fills slowly with every solve (about 0.7 MB per
 * solve on the Lab's problems; one Node process survives about 2,500). Past this many solves the page restarts the worker
 * before its next check instead of risking an out-of-memory abort in the middle of one.
 */
export const RECYCLE_AFTER_SOLVES = 1000;

interface Pending {
  readonly id: number;
  readonly kind: "init" | "check";
  readonly resolve: (v: ReadyInfo | { ms: number }) => void;
  readonly reject: (e: Error) => void;
  readonly onItem?: (key: string, outcome: Z3Outcome) => void;
  timer: ReturnType<typeof setTimeout> | null;
}

export interface CheckHandle {
  readonly request_id: number;
  /** Resolves with the worker's time when every sketch has been answered; rejects with `Z3Failure` / `Z3Cancelled`. */
  readonly done: Promise<{ ms: number }>;
  cancel(): void;
}

export class Z3Client {
  private readonly opts: Required<Omit<Z3ClientOptions, "createWorker">> & Pick<Z3ClientOptions, "createWorker">;
  private worker: WorkerLike | null = null;
  private starting: Promise<ReadyInfo> | null = null;
  private nextId = 0;
  private pending: Pending | null = null;
  private state: Z3State = { phase: "idle", failure: null, info: null };
  private readonly listeners = new Set<() => void>();
  /** Workers created so far (a test asserts it never exceeds the number of start() calls after a failure or dispose). */
  workersCreated = 0;
  /** Sketches the current worker has solved. */
  solvesDone = 0;

  constructor(opts: Z3ClientOptions) {
    this.opts = {
      workerUrl: opts.workerUrl,
      createWorker: opts.createWorker,
      initTimeoutMs: opts.initTimeoutMs ?? INIT_TIMEOUT_MS,
      requestTimeoutMs: opts.requestTimeoutMs ?? REQUEST_TIMEOUT_MS,
    };
  }

  // ------------------------------------------------------------------ observable state
  getState = (): Z3State => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  private setState(s: Z3State): void {
    this.state = s;
    for (const l of [...this.listeners]) l();
  }

  // ------------------------------------------------------------------ lifecycle
  /** Create the worker (once), download Z3 and wait until it is ready. Idempotent while loading or ready. */
  start(): Promise<ReadyInfo> {
    if (this.starting !== null) return this.starting;
    let worker: WorkerLike;
    try {
      worker = this.opts.createWorker !== undefined ? this.opts.createWorker(this.opts.workerUrl) : (new Worker(this.opts.workerUrl) as unknown as WorkerLike);
    } catch (e) {
      const failure = new Z3Failure(`the worker could not be created: ${e instanceof Error ? e.message : String(e)}`);
      this.setState({ phase: "failed", failure: failure.message, info: null });
      return Promise.reject(failure);
    }
    this.workersCreated += 1;
    this.solvesDone = 0;
    this.worker = worker;
    worker.onmessage = (ev) => this.onMessage(ev.data);
    worker.onerror = (ev) => this.fail(`the worker failed to run${ev.message ? `: ${ev.message}` : ""}`);
    worker.onmessageerror = () => this.fail("the worker sent a message the page could not read");
    this.setState({ phase: "loading", failure: null, info: null });
    const p = new Promise<ReadyInfo>((resolve, reject) => {
      this.begin({ id: ++this.nextId, kind: "init", resolve: resolve as Pending["resolve"], reject, timer: null }, this.opts.initTimeoutMs, {
        cmd: "init", request_id: this.nextId,
      });
    });
    p.catch(() => {}); // the caller handles it; never an unhandled rejection
    if (this.worker === worker) this.starting = p; // not when begin() already failed and tore the worker down
    return p;
  }

  /** Send one check. Replies for older requests are ignored; a newer `check` supersedes this one. */
  check(req: { readonly examples: readonly WireExample[]; readonly jobs: readonly WireJob[]; readonly timeoutMs?: number },
    onItem: (key: string, outcome: Z3Outcome) => void): CheckHandle {
    if (this.state.phase !== "ready" || this.worker === null) {
      const done = Promise.reject(new Z3Failure("Z3 is not ready"));
      done.catch(() => {});
      return { request_id: -1, done, cancel: () => {} };
    }
    if (this.pending !== null) this.supersede(this.pending);
    const id = ++this.nextId;
    const done = new Promise<{ ms: number }>((resolve, reject) => {
      this.begin({ id, kind: "check", resolve: resolve as Pending["resolve"], reject, onItem, timer: null }, this.opts.requestTimeoutMs, {
        cmd: "check", request_id: id, examples: req.examples, jobs: req.jobs, timeoutMs: req.timeoutMs,
      });
    });
    done.catch(() => {});
    return { request_id: id, done, cancel: () => this.cancelRequest(id) };
  }

  /** True when the worker has solved enough that its heap should be reset before the next check. */
  needsRecycle(): boolean {
    return this.solvesDone >= RECYCLE_AFTER_SOLVES;
  }

  /** Replace the worker by a fresh one (frees its memory); resolves when the new one is ready. */
  recycle(): Promise<ReadyInfo> {
    this.teardown(new Z3Cancelled());
    return this.start();
  }

  /** Terminate the worker and free its memory. The client can be started again. */
  dispose(): void {
    this.teardown(new Z3Cancelled());
    this.setState({ phase: "idle", failure: null, info: null });
  }

  // ------------------------------------------------------------------ internals
  private begin(p: Pending, timeoutMs: number, msg: Z3Request): void {
    this.pending = p;
    this.arm(p, timeoutMs);
    try {
      (this.worker as WorkerLike).postMessage(msg);
    } catch (e) {
      this.fail(`a message to the worker could not be sent: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  private arm(p: Pending, ms: number): void {
    if (p.timer !== null) clearTimeout(p.timer);
    p.timer = setTimeout(() => {
      this.fail(`it stopped responding for ${Math.round(ms / 1000)} s`);
    }, ms);
  }

  private clearTimer(p: Pending): void {
    if (p.timer !== null) clearTimeout(p.timer);
    p.timer = null;
  }

  private onMessage(m: Z3Message): void {
    const p = this.pending;
    if (p === null || m.request_id !== p.id) return; // stale: for a request that is no longer the one waited on
    if (m.type === "error") {
      this.fail(p.kind === "init" ? `it could not start: ${m.message}` : `it stopped with an error: ${m.message}`);
      return;
    }
    if (p.kind === "init" && m.type === "ready") {
      this.clearTimer(p);
      this.pending = null;
      this.setState({ phase: "ready", failure: null, info: m.info });
      p.resolve(m.info);
    } else if (p.kind === "check" && m.type === "item") {
      this.arm(p, this.opts.requestTimeoutMs); // progress: restart the watchdog
      this.solvesDone += 1;
      p.onItem?.(m.key, m.outcome);
    } else if (p.kind === "check" && m.type === "done") {
      this.clearTimer(p);
      this.pending = null;
      p.resolve({ ms: m.ms });
    }
  }

  private supersede(p: Pending): void {
    this.clearTimer(p);
    this.pending = null;
    this.worker?.postMessage({ cmd: "cancel", request_id: p.id });
    p.reject(new Z3Cancelled());
  }

  private cancelRequest(id: number): void {
    const p = this.pending;
    if (p === null || p.id !== id) return;
    this.supersede(p);
  }

  /** Terminate the worker, reject what is pending, and mark the client failed. */
  private fail(message: string): void {
    this.teardown(new Z3Failure(message));
    this.setState({ phase: "failed", failure: message, info: null });
  }

  private teardown(reason: Error): void {
    const p = this.pending;
    this.pending = null;
    if (p !== null) {
      this.clearTimer(p);
      p.reject(reason);
    }
    const w = this.worker;
    this.worker = null;
    this.starting = null;
    if (w !== null) {
      w.onmessage = null;
      w.onerror = null;
      w.onmessageerror = null;
      try {
        w.terminate();
      } catch {
        // already gone
      }
    }
  }
}
