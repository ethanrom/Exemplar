// Types of every JSON file under apps/showcase/data/ (the export of apps/showcase/scripts/export/).
// Field for field, these mirror the strict pydantic models in scripts/export/schema.py (SPEC 4.4).
// Erasable TypeScript only: no enums, namespaces, parameter properties or decorators.

// ----------------------------------------------------------------------------------------------- manifest.json
export type Manifest = {
  schema: "exemplar.showcase/1";
  exported_on: string; // YYYY-MM-DD
  engine_commit: string;
  sources: { key: "recording" | "heldout" | "stills"; rows: Record<string, number> }[]; // counts only
  asserts: { id: string; ok: true; detail: string }[]; // A1..A11 (see the export report)
  counts: { library: number; playground: { package: number; vehicle: number; bird: number } };
  files: { path: string; bytes: number; sha256: string }[];
};

// ----------------------------------------------------------------------------------------------- library.json
export type ClipSource = "playground" | "cc_by" | "meva";
export type ClipClass = "pg_package" | "pg_vehicle" | "pg_bird" | "frollard" | "meva" | "ringtv_fox";
export type MediaMode = "frames" | "trace_only";

export type RecordedLabel = {
  concept: string; // concept slug: package | vehicle | theft
  label: "pos" | "neg";
  provenance: "example" | "active" | "random";
};

/** One clip of the library. `alias` is the only identifier the site ever shows or links. */
export type ClipCard = {
  alias: string; // e.g. pg-pkg-07, cc-frollard-15s
  title: string;
  source: ClipSource;
  class: ClipClass;
  duration_ms: number;
  recorded_on?: string; // YYYY-MM-DD (UTC), Playground recordings only
  summary: string; // Claude's trace summary, verbatim after the scrub
  credit: string; // key into credits.json
  media: MediaMode; // as exported (frames); see resolveMedia() for the SANDBOX_MEDIA=trace variant
  poster?: string; // /media/posters/<alias>.webp, 640 px wide
  sheet?: string; // /media/sheets/<alias>.webp, 4x4 grid of 320x180 frames, row-major, in time order
  sheet_times_ms: number[]; // the 16 frame times (== trace frame t_ms); sheet cell i is sheet_times_ms[i]
  curated?: number; // 0..7 when the clip is one of the Lab's free-play clips
  recorded_labels: RecordedLabel[];
};

// ----------------------------------------------------------------------------------------------- traces/<alias>.json
export type Conf = "low" | "med" | "high";
export type TraceJson = {
  schema_version: 1;
  clip_id: string; // the clip alias
  source: "ring" | "ring_live" | "upload" | "meva" | "fixture";
  duration_ms: number;
  status: "ok" | "perception_failed";
  error: string | null;
  entities: { id: string; type: "person" | "vehicle" | "package" | "animal" | "object"; attrs: string[] }[];
  frames: { t_ms: number; facts: { pred: string; args: string[]; conf: Conf }[] }[];
  context: { sub_type?: string; event_kind?: string; local_hour?: number; weekday?: number }; // no device, no start time
  summary: string;
  perception?: {
    mode: "fast" | "strong" | "fixture" | "manual";
    model_alias: string | null;
    n_frames: number;
    samples: number;
    tokens_in: number;
    tokens_out: number;
    latency_ms: number;
  };
};

// ----------------------------------------------------------------------------------------------- DSL abstract syntax
export type HoleRef = { op: "hole"; name: string };
export type Bound = number | HoleRef;
export type VarType = "Entity" | "Person" | "Vehicle" | "Package" | "Animal" | "Object" | "Carryable";
export type Phi =
  | { op: "atom"; pred: string; args: string[] }
  | { op: "not"; arg: Phi }
  | { op: "and"; args: Phi[] }
  | { op: "or"; args: Phi[] }
  | { op: "eventually"; a: Bound; b: Bound; arg: Phi }
  | { op: "always"; a: Bound; b: Bound; arg: Phi }
  | { op: "then"; a: Bound; b: Bound; left: Phi; right: Phi }
  | { op: "holds_for"; d: Bound; arg: Phi };
export type Ctx = { op: "hour_in"; h1: number | HoleRef; h2: number | HoleRef } | { op: "subtype_eq"; value: string };
export type RuleAst = { vars: { name: string; type: VarType }[]; body: Phi; when: Ctx[] };

// ----------------------------------------------------------------------------------------------- calibration and witness
export type CalibrationJson = {
  alpha: number;
  n_random_neg: number;
  n_random_pos: number;
  k: number | null; // ceil((n+1)(1-alpha)); null when k > n
  tau: number;
  guarantee: boolean;
  message: string | null; // e.g. "guarantee needs ≥ 9 random negatives (have 0)"
  delta: number;
  recall: number | null;
  recall_ci95: [number, number] | null;
};

export type WitnessSpan = {
  path: string; // AST path, e.g. body.arg
  op: string;
  text?: string;
  t_start_ms: number;
  t_end_ms: number;
  rho: number;
};
export type WitnessJson = {
  rule_id: string; // rule slug
  clip_id: string; // clip alias
  score: number;
  tau?: number;
  margin?: number; // score - tau
  bindings: Record<string, string>; // variable -> entity id of the trace
  entities?: TraceJson["entities"];
  spans: WitnessSpan[];
  english?: string;
};

// ----------------------------------------------------------------------------------------------- runs/<slug>.json
export type RunSlug = "p1-playground" | "vehicle" | "theft-a" | "theft-b";
export type RunEventType =
  | "round_started"
  | "sketch_proposed"
  | "typecheck_failed"
  | "solve_started"
  | "solve_result"
  | "differential_check"
  | "counterexample"
  | "candidates"
  | "question_ready"
  | "done"
  | "error";

/** api.yaml RunEvent: `at_ms` became `t_ms` (relative to the run start), ids became aliases and slugs. */
export type RunEvent = {
  seq: number;
  t_ms: number;
  type: RunEventType;
  round?: number;
  sketch?: string | null;
  error?: string | null;
  result?: "sat" | "unsat" | "timeout" | "grid_fallback" | null;
  holes?: Record<string, number> | null;
  margin?: number | null;
  violated_clip_ids?: string[]; // clip aliases
  rule_ids?: string[]; // rule slugs
  message?: string | null;
};

export type RunDoc = {
  slug: RunSlug;
  title: string;
  concept: { slug: string; name: string; nl_hint: string; alpha: number };
  source: "recording" | "heldout" | "stills";
  duration_ms: number;
  proposer_note: string;
  /** The examples the run started with: labels with provenance example or active, created before the run began. */
  examples: { alias: string; label: "pos" | "neg"; provenance: "example" | "active"; weight: number }[];
  events: RunEvent[];
  /** What a replay proposer returns per round; the back-fill round (backfill: true) holds the recorded template texts. */
  proposals_by_round: { round: number; backfill: boolean; texts: string[] }[];
  /** Rule slugs in the recorded `candidates` event order (rank = index + 1). */
  candidates: string[];
};

// ----------------------------------------------------------------------------------------------- rules/<slug>.json
export type RuleStatus = "deployed" | "candidate" | "retired";
export type RuleSelection = "chosen_by_user_and_deployed" | "selected_for_display_as_demo_equivalent";

export type RuleDoc = {
  slug: string; // package-deployed, vehicle-deployed, <run>-c<rank>, theft-retired-<n>
  run: string | null;
  concept: string;
  status: RuleStatus;
  /** Position in the recorded `candidates` event of the rule's own run. */
  recorded_rank: { run: string; position: number; of: number } | null;
  selection: RuleSelection | null;
  ast: RuleAst;
  sketch_text: string;
  dsl_text: string;
  english: string; // printed from the rule by code, never paraphrased
  holes: Record<string, number>;
  margin: number;
  mdl: number;
  violations: string[]; // clip aliases of the examples the rule misses
  tau: number | null; // as stored; null when the rule was never calibrated
  delta: number;
  calibration: CalibrationJson | null; // verbatim from the database
  /** Engine feasible interval of each hole of the rule's sketch ([lo, hi] seconds or hours). */
  box?: Record<string, [number, number]>;
  /**
   * Engine robustness of the rule on every library clip. `matched` is score > tau, where tau is the stored tau, or the
   * engine's calibrate() threshold for a rule that was never calibrated (0 when its concept has no random labels).
   */
  backtest: { alias: string; score: number; matched: boolean }[];
};

// ----------------------------------------------------------------------------------------------- live.json
export type LiveDecision = {
  rule: string; // rule slug (package-deployed | vehicle-deployed)
  stage: 0 | 1 | 2;
  score: number;
  tau: number;
  fired: boolean;
  witness: WitnessJson | null; // present exactly when fired
};
export type LiveDoc = {
  /** The five recorded two-rule events, in order: birds, vehicle, package, vehicle, package. */
  events: { alias: string; order: 1 | 2 | 3 | 4 | 5; class: "pg_package" | "pg_vehicle" | "pg_bird"; decisions: LiveDecision[] }[];
};

// ----------------------------------------------------------------------------------------------- calibration/package.json
export type CalDoc = {
  concept: "package";
  alpha: number;
  rule: "package-deployed";
  scope: "stage1_fast_perception";
  provenance: {
    random_labels: number;
    drawn_via: "random-sample endpoint";
    disjoint_from_examples: true;
    disjoint_from_curated: true;
  };
  random: { alias: string; label: "pos" | "neg"; score: number }[];
  calibration: CalibrationJson; // equals rules/package-deployed.json calibration
};

// ----------------------------------------------------------------------------------------------- credits.json
export type CreditEntry = {
  id: string; // referenced by ClipCard.credit
  group: "playground_frollard_derived" | "playground_other" | "cc_by" | "meva" | "software";
  title: string;
  author?: string;
  url?: string;
  licence: string;
  licence_url?: string;
  permission: {
    basis: "cc_by" | "own_work" | "ring_sandbox" | "open_source";
    status: "cleared" | "pending_user_decision";
    evidence: string; // a public URL plus the quoted field, or a repo-relative file plus the quoted field
    checked_on: string;
  };
  modification?: string; // what was changed: cut into windows, frames extracted
  note?: string;
  aliases: string[]; // the library clips that carry this credit
};

// ----------------------------------------------------------------------------------------------- claims.json
export type Claim = {
  id: string;
  display: string; // exactly as published
  source: { path: string; line: number; quote: string };
};
export type ClaimsDoc = { source: string; note: string; claims: Claim[] };

// ----------------------------------------------------------------------------------------------- lab/*.json
export type Tri = "pos" | "neg" | null;
export type CuratedDoc = { clips: string[]; default: Tri[] }; // clips[i] is bit i of a combination index
export type Sketch = { id: number; text: string; holes: string[]; from_runs: string[] };
