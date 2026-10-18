// Trace: the symbolic output of perception for one clip (engine/exemplar/contracts/trace.py).
//
// Time is integer milliseconds from clip start. The shapes below accept the engine's JSON (the `trace_json`
// column, the scrubbed `public/data/traces/*.json`) as-is; every field the evaluator does not read is optional
// so that scrubbed traces (no device_id, no cache_key) are valid too.

import type { Conf, EntityType, SubType } from "./ontology.ts";

export interface Entity {
  readonly id: string;
  readonly type: EntityType;
  /** Clip-level open-vocab labels, e.g. delivery_uniform, hi_vis. */
  readonly attrs?: readonly string[];
}

export interface Fact {
  readonly pred: string;
  readonly args: readonly string[];
  readonly conf: Conf;
}

export interface Frame {
  readonly t_ms: number;
  readonly facts?: readonly Fact[];
}

/** Context signals. Context atoms in rules read these; all optional (a missing value makes the atom false). */
export interface TraceContext {
  readonly sub_type?: SubType | null;
  readonly event_kind?: "motion" | "ding" | "on_demand" | "live" | "upload" | null;
  readonly local_hour?: number | null;
  readonly weekday?: number | null;
  readonly device_id?: string | null;
  readonly started_at_ms?: number | null;
}

export interface PerceptionMeta {
  readonly mode: "fast" | "strong" | "fixture" | "manual";
  readonly model_alias?: string | null;
  readonly n_frames?: number;
  readonly samples?: number;
  readonly tokens_in?: number;
  readonly tokens_out?: number;
  readonly latency_ms?: number;
  readonly cache_key?: string | null;
}

export interface Trace {
  readonly schema_version?: 1;
  readonly clip_id: string;
  readonly source?: "ring" | "ring_live" | "upload" | "meva" | "fixture";
  readonly duration_ms?: number;
  readonly status: "ok" | "perception_failed";
  readonly error?: string | null;
  readonly entities: readonly Entity[];
  readonly frames: readonly Frame[];
  readonly context?: TraceContext;
  readonly summary?: string;
  readonly perception?: PerceptionMeta | null;
}
