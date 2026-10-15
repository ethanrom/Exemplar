// Hand-written mirror of engine/exemplar/contracts/api.yaml (+ schemas/*.json). Keep in sync with the
// contract; the mock engine validates its responses against the YAML (`npm run mock:validate`).

export type SourceKind = 'ring' | 'ring_live' | 'upload' | 'meva' | 'fixture'
export type Provenance = 'example' | 'active' | 'random'
export type LabelValue = 'pos' | 'neg'
export type RuleStatus = 'candidate' | 'selected' | 'deployed' | 'retired'
export type RuleAction = 'ui' | 'webhook_out' | 'slack' | 'chime'

export interface ApiErrorBody {
  error: string
  code?: string | null
}

export interface RingAuthStatus {
  mode: 'playground' | 'oauth' | null
  connected: boolean
  expires_at_ms?: number | null
  issued_at_ms?: number | null
  user_name?: string | null
}

export interface Device {
  id: string
  name: string
  online?: boolean | null
  image_url?: string | null
  codecs?: string[]
  snapshot?: boolean
  chime?: boolean
}

export interface LabelSummary {
  concept_id: string
  clip_id: string
  value: LabelValue | null
  provenance: Provenance
  weight: number
}

export interface EventSummary {
  id: string
  clip_id: string
  source: SourceKind
  device_id?: string | null
  kind?: string | null
  sub_type?: string | null
  start_ms: number
  duration_ms?: number | null
  clip_status?: 'pending' | 'downloading' | 'ready' | 'not_found' | 'failed'
  trace_status: 'none' | 'ok' | 'perception_failed'
  summary?: string | null
  has_snapshot?: boolean
  attribution?: string | null
  label?: LabelSummary | null
}

export interface Entity {
  id: string
  type: 'person' | 'vehicle' | 'package' | 'animal' | 'object'
  attrs?: string[]
}

export interface Fact {
  pred: string
  args: string[]
  conf: 'low' | 'med' | 'high'
}

export interface Trace {
  clip_id: string
  source: SourceKind
  duration_ms: number
  status: 'ok' | 'perception_failed'
  error?: string | null
  entities: Entity[]
  frames: { t_ms: number; facts: Fact[] }[]
  summary: string
  perception?: { mode: string; model_alias?: string | null; n_frames: number; tokens_in: number; tokens_out: number; latency_ms: number } | null
}

export interface EventDetail extends EventSummary {
  trace?: Trace | null
  strong_trace?: Trace | null
  trace_text?: string | null
}

export interface Concept {
  id: string
  name: string
  nl_hint?: string | null
  alpha: number
  counts?: Partial<Record<'example_pos' | 'example_neg' | 'active_pos' | 'active_neg' | 'random_pos' | 'random_neg', number>>
  deployed_rule_id?: string | null
}

export interface Label {
  concept_id: string
  clip_id: string
  value: LabelValue
  provenance: Provenance
  weight: number
  created_at?: string
}

export interface Run {
  id: string
  concept_id: string
  status: 'running' | 'done' | 'failed' | 'cancelled'
  error?: string | null
  started_at_ms: number
  finished_at_ms?: number | null
}

export type RunEventType =
  | 'round_started' | 'sketch_proposed' | 'typecheck_failed' | 'solve_started' | 'solve_result'
  | 'differential_check' | 'counterexample' | 'candidates' | 'question_ready' | 'done' | 'error'

export interface RunEvent {
  seq: number
  at_ms: number
  type: RunEventType
  round?: number
  sketch?: string | null
  error?: string | null
  result?: 'sat' | 'unsat' | 'timeout' | 'grid_fallback' | null
  holes?: Record<string, number> | null
  margin?: number | null
  violated_clip_ids?: string[]
  rule_ids?: string[]
  message?: string | null
}

export interface Calibration {
  alpha: number
  n_random_neg: number
  n_random_pos?: number
  k?: number | null
  tau: number
  guarantee: boolean
  message?: string | null
  delta?: number
  recall?: number | null
  recall_ci95?: [number, number] | null
}

export interface RuleSummary {
  id: string
  concept_id: string
  sketch_text?: string
  dsl_text: string
  english: string
  holes?: Record<string, number>
  margin: number
  mdl: number
  violated_clip_ids?: string[]
  status: RuleStatus
  calibration?: Calibration | null
  actions?: RuleAction[]
}

export interface Question {
  concept_id: string
  clip_id: string
  event?: EventSummary
  p: number
  committee_size?: number
}

export interface WitnessSpan {
  path: string
  op: string
  text?: string
  t_start_ms: number
  t_end_ms: number
  rho: number
}

export interface Witness {
  rule_id: string
  clip_id: string
  score: number
  tau?: number
  margin?: number
  bindings: Record<string, string>
  entities?: Entity[]
  spans: WitnessSpan[]
  english?: string
}

export interface BacktestRow {
  clip_id: string
  event?: EventSummary
  score: number
  matched: boolean
  label?: LabelSummary | null
  witness?: Witness | null
}

export interface Backtest {
  rule_id: string
  rows: BacktestRow[]
  calibration: Calibration
  counts?: { tp?: number; fp?: number; fn?: number; tn?: number; unlabelled_matches?: number }
}

export interface FiringAction {
  action: string
  status: 'ok' | 'skipped' | 'failed'
  detail?: string | null
}

export interface Firing {
  id: string
  rule_id: string
  event_id: string
  stage: 0 | 1 | 2
  score?: number | null
  tau?: number | null
  fired: boolean
  witness?: Witness | null
  actions?: FiringAction[]
  created_at_ms: number
}

export type MonitorEventType =
  | 'event_ingested' | 'clip_ready' | 'trace_ready' | 'live_facts' | 'rule_fired' | 'rule_dropped'
  | 'escalated' | 'action_result' | 'cost_update' | 'auth_expiring' | 'error'

export interface LiveFact {
  t_ms: number
  pred: string
  args: string[]
  conf: string
}

export interface CostSummary {
  events: number
  stage0_dropped: number
  stage1_scored: number
  stage2_escalated: number
  tokens_in: number
  tokens_out: number
  usd_estimate?: number
  per_event_usd?: number
}

export interface MonitorEvent {
  type: MonitorEventType
  at_ms: number
  event_id?: string | null
  rule_id?: string | null
  firing?: Firing | null
  facts?: LiveFact[] | null
  cost?: CostSummary | null
  message?: string | null
}

export interface EvalRow {
  concept: string
  method: 'exemplar' | 'zero_shot_vlm' | 'knn_embed' | 'nova_video'
  k: number
  q: number
  seed: number
  f1?: number
  precision?: number
  recall?: number
  false_alarm_rate?: number
  tokens_per_event?: number
  usd_per_event?: number
  p50_latency_ms?: number
  escalated_fraction?: number
}

export interface EvalResults {
  generated_at: string
  alpha?: number
  rows: EvalRow[]
}
