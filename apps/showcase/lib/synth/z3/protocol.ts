// Messages between the page and the Z3 worker (worker.ts). Every message carries the `request_id` of the request it
// belongs to; the page drops any message that is not for the request it is waiting on.

import type { Trace } from "../../dsl/index.ts";
import type { Z3SolveResult } from "./solve.ts";

/** The z3-solver release the assets are copied from; part of the asset path (/z3/5.3.1/). */
export const Z3_VERSION = "5.3.1";

/** One labelled clip, as the worker needs it. */
export interface WireExample {
  readonly clip_id: string;
  readonly positive: boolean;
  readonly weight: number;
  readonly trace: Trace;
}

/** One sketch to solve; `key` identifies it for the page. */
export interface WireJob {
  readonly key: string;
  /** DSL text of the sketch (with holes). */
  readonly sketch: string;
  /** The hole values the page shows for it; the worker checks them with the evaluator (see Z3SolveResult.referenceVerified). */
  readonly referenceHoles?: Readonly<Record<string, number>>;
}

export type Z3Request =
  | { readonly cmd: "init"; readonly request_id: number; readonly base?: string }
  | { readonly cmd: "check"; readonly request_id: number; readonly examples: readonly WireExample[]; readonly jobs: readonly WireJob[]; readonly timeoutMs?: number }
  | { readonly cmd: "cancel"; readonly request_id: number };

/** What came of one sketch. `unsupported` means "not checked by Z3" (the encoder cannot take the sketch). */
export type Z3Outcome =
  | { readonly kind: "solved"; readonly result: Z3SolveResult }
  | { readonly kind: "unsupported"; readonly reason: string }
  | { readonly kind: "error"; readonly message: string };

export interface ReadyInfo {
  /** Time from `init` to ready, in the worker: importScripts, module init, warm-up solve. */
  readonly importMs: number;
  readonly initMs: number;
  readonly warmupMs: number;
  readonly totalMs: number;
  readonly z3Version: string;
  readonly crossOriginIsolated: boolean;
}

export type Z3Message =
  | { readonly type: "ready"; readonly request_id: number; readonly info: ReadyInfo }
  | { readonly type: "item"; readonly request_id: number; readonly key: string; readonly outcome: Z3Outcome }
  | { readonly type: "done"; readonly request_id: number; readonly ms: number }
  | { readonly type: "error"; readonly request_id: number; readonly message: string };
