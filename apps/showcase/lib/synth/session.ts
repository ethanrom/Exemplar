// The Lab's requests, as pure functions and a cancellable request runner (SPEC 7.1, 7.2, 7.5).
//
//   freePlay(data, states)   the tri-state free-play pipeline: examples at weight 3.0 in curated order, a `RunState`
//                            with k = 6, every bank sketch submitted in order and solved exhaustively, then
//                            `candidates()[:6]`. No proposer, no rounds, no back-fill - exactly what the grid's engine
//                            path does, so the grid is the ground truth.
//   runPreset(data, run)     the recorded proposals replayed through the CEGIS loop (`runReplay`).
//
// `LabSession` wraps both for a worker: every request carries a monotonically increasing `request_id`; a new request
// supersedes the running one, which is abandoned at the next check-point (between sketches, and every 1,000 hole
// points through `cancelFlag` when the page is cross-origin isolated); events and results are only posted for the
// current request. It never reads the grid or any recorded result (SPEC 6.5).

import type { Trace } from "../dsl/index.ts";
import { runReplay } from "./replay.ts";
import type { RecordedRound } from "./replay.ts";
import { RunState } from "./state.ts";
import type { RunEvent } from "./state.ts";
import { Cancelled, makeExample } from "./types.ts";
import type { Candidate, Example, SolveResult } from "./types.ts";

export const WEIGHT = 3.0; // every user label weighs 3.0 (Label.weight of a user-confirmed example)
export const K = 6;

export interface LabData {
  /** The curated clips in bit order: index 0 is the least significant digit of the slot number. */
  curated: { alias: string; trace: Trace }[];
  /** The recorded sketch bank, in sketches.json order. */
  sketches: { id: number; text: string }[];
}

/** 0 not used, 1 yes (positive), 2 no (negative) per curated clip. */
export type States = readonly (0 | 1 | 2)[];

export function slotOf(states: States): number {
  let s = 0;
  for (let i = states.length - 1; i >= 0; i--) s = s * 3 + (states[i] as number);
  return s;
}

export function statesOf(slot: number, n = 8): (0 | 1 | 2)[] {
  const out: (0 | 1 | 2)[] = [];
  for (let i = 0; i < n; i++) {
    out.push((slot % 3) as 0 | 1 | 2);
    slot = Math.floor(slot / 3);
  }
  return out;
}

/** Valid: at least one yes and at least one no. */
export function isValid(states: States): boolean {
  return states.includes(1) && states.includes(2);
}

export function examplesOf(data: LabData, states: States): Example[] {
  const out: Example[] = [];
  data.curated.forEach((c, i) => {
    const st = states[i] ?? 0;
    if (st !== 0) out.push(makeExample(c.trace, st === 1, WEIGHT, c.alias));
  });
  return out;
}

export interface CandidateItem {
  rank: number;
  sketch_id: number;
  sketch_text: string;
  dsl_text: string;
  english: string;
  holes: Record<string, number>;
  margin: number;
  mdl: number;
  violated_clip_ids: string[];
}

export interface SketchOutcome {
  sketch_id: number;
  /** "rejected" when the sketch does not typecheck / parse, else the solver's status. */
  status: SolveResult["status"] | "rejected";
  result: SolveResult | null;
}

export interface FreePlayResult {
  items: CandidateItem[];
  outcomes: SketchOutcome[];
  state: RunState;
}

const itemOf = (c: Candidate, rank: number, ids: Map<string, number>): CandidateItem => ({
  rank, sketch_id: ids.get(c.sketch_text) as number, sketch_text: c.sketch_text, dsl_text: c.dsl_text, english: c.english,
  holes: { ...c.holes }, margin: c.margin, mdl: c.mdl, violated_clip_ids: [...c.violated_clip_ids],
});

/** The free-play pipeline as a generator: yields after every sketch (a check-point for the caller). */
export function* freePlayGen(
  data: LabData, states: States, emit: (e: RunEvent) => void, opts: { isCancelled?: () => boolean; maxClasses?: number } = {},
): Generator<void, FreePlayResult, void> {
  const examples = examplesOf(data, states);
  const ids = new Map(data.sketches.map((s) => [s.text, s.id] as const));
  const state = new RunState(examples, emit, { k: K, isCancelled: opts.isCancelled, maxClasses: opts.maxClasses });
  const canons: { id: number; canon: string | null }[] = [];
  for (const s of data.sketches) {
    const r = state.submit(s.text);
    canons.push({ id: s.id, canon: r.accepted ? r.canon : null });
  }
  const outcomes: SketchOutcome[] = [];
  for (const { id, canon } of canons) {
    if (canon === null) {
      outcomes.push({ sketch_id: id, status: "rejected", result: null });
      continue;
    }
    const rec = state.solve(canon);
    outcomes.push({ sketch_id: id, status: rec.result ? rec.result.status : "rejected", result: rec.result });
    yield;
  }
  const items = state.candidates().slice(0, K).map((c, i) => itemOf(c, i + 1, ids));
  emit({ type: "candidates", round: state.round, rule_ids: [], message: `${items.length} candidate(s)` });
  return { items, outcomes, state };
}

/** The free-play pipeline for one label combination. Throws `Cancelled` if `isCancelled()` turns true. */
export function freePlay(
  data: LabData, states: States, emit: (e: RunEvent) => void = () => {}, opts: { isCancelled?: () => boolean; maxClasses?: number } = {},
): FreePlayResult {
  const g = freePlayGen(data, states, emit, opts);
  for (;;) {
    const n = g.next();
    if (n.done) return n.value;
  }
}

export interface PresetRun {
  /** Examples of the run: clip alias, label, weight. */
  examples: { alias: string; positive: boolean; weight: number }[];
  rounds: RecordedRound[];
  k?: number;
}

export interface PresetResult {
  items: CandidateItem[];
  state: RunState | null;
  events: RunEvent[];
}

export function runPreset(
  data: LabData & { traces?: Record<string, Trace> }, run: PresetRun, emit: (e: RunEvent) => void = () => {},
  opts: { isCancelled?: () => boolean; maxClasses?: number } = {},
): PresetResult {
  const traces = new Map<string, Trace>(data.curated.map((c) => [c.alias, c.trace] as const));
  for (const [a, t] of Object.entries(data.traces ?? {})) traces.set(a, t);
  const examples = run.examples.map((e) => {
    const t = traces.get(e.alias);
    if (t === undefined) throw new Error(`no trace for ${e.alias}`);
    return makeExample(t, e.positive, e.weight, e.alias);
  });
  const events: RunEvent[] = [];
  const out = runReplay(examples, run.rounds, (e) => {
    events.push(e);
    emit(e);
  }, { k: run.k ?? K, isCancelled: opts.isCancelled, maxClasses: opts.maxClasses });
  const items = out.candidates.map((c, i) => ({
    rank: i + 1, sketch_id: -1, sketch_text: c.sketch_text, dsl_text: c.dsl_text, english: c.english, holes: { ...c.holes },
    margin: c.margin, mdl: c.mdl, violated_clip_ids: [...c.violated_clip_ids],
  }));
  return { items, state: out.state, events };
}

// ----------------------------------------------------------------------------- worker protocol (I6)

export type WorkerRequest =
  | { type: "init"; data: LabData & { traces?: Record<string, Trace> }; cancelFlag?: Int32Array }
  | { type: "free"; request_id: number; states: States }
  | { type: "preset"; request_id: number; run: PresetRun }
  | { type: "cancel"; request_id: number };

export type WorkerMessage =
  | { type: "event"; request_id: number; event: RunEvent }
  | { type: "candidates"; request_id: number; items: CandidateItem[] }
  | { type: "outcomes"; request_id: number; outcomes: SketchOutcome[] }
  | { type: "done"; request_id: number; backend_status: { backend: "exhaustive"; solved: number; budget_exceeded: number } }
  | { type: "error"; request_id: number; message: string };

const yieldToEventLoop = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

/**
 * Cancellable request runner. `post` sends a message to the page; `session.handle(msg)` is the worker's `onmessage`.
 * Requests are processed one at a time; a newer `request_id` supersedes the running one.
 */
export class LabSession {
  private data: (LabData & { traces?: Record<string, Trace> }) | null = null;
  private current = 0;
  private cancelled = new Set<number>();
  private flag: Int32Array | null = null;
  private readonly post: (m: WorkerMessage) => void;

  constructor(post: (m: WorkerMessage) => void) {
    this.post = post;
  }

  private stale(id: number): boolean {
    return this.current !== id || this.cancelled.has(id) || (this.flag !== null && Atomics.load(this.flag, 0) > id);
  }

  async handle(msg: WorkerRequest): Promise<void> {
    if (msg.type === "init") {
      this.data = msg.data;
      this.flag = msg.cancelFlag ?? null;
      return;
    }
    if (msg.type === "cancel") {
      this.cancelled.add(msg.request_id);
      return;
    }
    const id = msg.request_id;
    if (id < this.current) return; // an older request that arrived late
    this.current = id;
    if (this.data === null) {
      this.post({ type: "error", request_id: id, message: "the Lab data has not been sent to the worker" });
      return;
    }
    const isCancelled = (): boolean => this.stale(id);
    const emit = (event: RunEvent): void => {
      if (!this.stale(id)) this.post({ type: "event", request_id: id, event });
    };
    try {
      await yieldToEventLoop(); // let a newer message in before any work starts
      if (isCancelled()) return;
      if (msg.type === "free") {
        // sketches are solved one at a time with an event-loop turn in between, so a newer request is noticed
        const r = await this.freePlayAsync(this.data, msg.states, emit, isCancelled);
        if (r === null || isCancelled()) return;
        this.post({ type: "candidates", request_id: id, items: r.items });
        const budget = r.outcomes.filter((o) => o.status === "budget_exceeded").length;
        this.post({ type: "outcomes", request_id: id, outcomes: r.outcomes });
        this.post({ type: "done", request_id: id, backend_status: { backend: "exhaustive", solved: r.outcomes.length - budget, budget_exceeded: budget } });
      } else {
        const r = runPreset(this.data, msg.run, emit, { isCancelled });
        if (isCancelled()) return;
        this.post({ type: "candidates", request_id: id, items: r.items });
        const solved = r.state ? r.state.solved().length : 0;
        this.post({ type: "done", request_id: id, backend_status: { backend: "exhaustive", solved, budget_exceeded: 0 } });
      }
    } catch (e) {
      if (e instanceof Cancelled) return;
      this.post({ type: "error", request_id: id, message: (e as Error).message });
    }
  }

  private async freePlayAsync(
    data: LabData, states: States, emit: (e: RunEvent) => void, isCancelled: () => boolean,
  ): Promise<FreePlayResult | null> {
    const g = freePlayGen(data, states, emit, { isCancelled });
    for (;;) {
      const n = g.next();
      if (n.done) return n.value;
      await yieldToEventLoop(); // a newer message can arrive here
      if (isCancelled()) return null;
    }
  }
}
