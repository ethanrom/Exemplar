# Phase 2 interfaces (D synth/agent · E active/calibrate/monitor · H api/store)

Written by the integrator before Phase 2 branched. D, E and H build in parallel, so each codes against these signatures. If one must change, keep the old name working as an adapter and say so in your final report. Everything below is Python in `engine/exemplar/`. Types come from `exemplar.contracts` (`Trace`, `Rule`, `Label`, …) and the merged streams: A is `exemplar.ring`, B is `exemplar.perception`, C is `exemplar.dsl`.

Shared value types are plain frozen dataclasses (or pydantic), defined by the stream that owns the module. Their `.to_api()` returns the matching `api.yaml` schema dict.

## D: `exemplar.synth`, `exemplar.agent`
```python
# synth/
@dataclass(frozen=True)
class Example:                 # one labelled clip given to the solver
    trace: Trace               # (or a PreparedTrace from exemplar.dsl.prepare)
    positive: bool
    weight: float              # Label.weight (1 bulk, 3 user-confirmed)
    clip_id: str

@dataclass(frozen=True)
class SolveResult:
    status: Literal["sat", "unsat", "timeout", "grid_fallback"]
    sketch: Rule               # with holes
    rule: Rule | None          # closed, after temporal-slack placement (None if unsat)
    holes: dict[str, float]
    margin: float              # m*
    violated: tuple[str, ...]  # clip_ids of violated examples ("perception suspect?")
    satisfied: tuple[str, ...]
    diff_check_ok: bool        # NumPy re-evaluation agreed (a mismatch must raise, so this is True when returned)
    solve_ms: int

def solve_sketch(sketch: Rule, examples: list[Example], *, timeout_s: float = 10.0) -> SolveResult: ...
def hole_box(sketch: Rule, examples: list[Example], *, satisfied: Sequence[str], margin: float,
             timeout_s: float = 10.0) -> dict[str, tuple[float, float]]: ...   # Z3 min/max per hole (§2.4); E's committee uses it
def mdl(rule: Rule, violations: int, *, lam: float = 4.0) -> float: ...
def render_trace_text(trace: Trace) -> str: ...      # compact rendering shown to the sketch LLM and in EventDetail.trace_text

@dataclass(frozen=True)
class Candidate:
    sketch_text: str; dsl_text: str; english: str     # english/dsl_text come from exemplar.dsl printers
    rule: Rule; holes: dict[str, float]; margin: float; mdl: float
    violated_clip_ids: tuple[str, ...]
    def to_api(self, *, id: str, concept_id: str, status: str = "candidate") -> dict: ...   # RuleSummary

# agent/
def run_cegis(examples: list[Example], *, nl_hint: str | None, emit: Callable[[dict], None],
              k: int = 6, max_rounds: int = 4, model=None, cancel: threading.Event | None = None) -> list[Candidate]: ...
# emit(...) receives RunEvent dicts (api.yaml RunEvent, without seq/at_ms; H adds those):
#   {"type": "sketch_proposed", "round": 1, "sketch": "..."} | {"type": "typecheck_failed", "sketch": ..., "error": ...}
#   | {"type": "solve_result", "result": "sat", "holes": {...}, "margin": .., "violated_clip_ids": [...]} | ...
# Candidates are ranked by MDL ascending, then margin descending. `model=None` builds the Strands BedrockModel from settings;
# tests pass a fake proposer.
```

## E: `exemplar.active`, `exemplar.calibrate`, `exemplar.monitor`
```python
# active/
@dataclass(frozen=True)
class Committee:
    members: tuple[tuple[Rule, float], ...]   # closed rules, normalised weights ∝ exp(−MDL)

def build_committee(candidates: list[Candidate], examples: list[Example], *,
                    box_fn: Callable[..., dict[str, tuple[float, float]]] = None,   # defaults to exemplar.synth.hole_box
                    n_samples: int = 200, seed: int = 0) -> Committee: ...
def select_query(committee: Committee, unlabelled: list[Trace], *, k: int = 1) -> list[Question]: ...
@dataclass(frozen=True)
class Question:
    clip_id: str; p: float; committee_size: int
    def to_api(self, *, concept_id: str, event: dict | None = None) -> dict: ...

# calibrate/
def conformal_threshold(neg_scores: Sequence[float], alpha: float) -> Calibration: ...   # §2.5, k = ceil((n+1)(1−α))
def recall_ci(pos_scores: Sequence[float], tau: float, *, level: float = 0.95) -> tuple[float | None, tuple[float, float] | None]: ...
def calibrate(rule: Rule, random_labelled: list[tuple[Trace, Label]], alpha: float) -> Calibration: ...   # scores with exemplar.dsl
@dataclass(frozen=True)
class Calibration:   # fields = api.yaml Calibration; .to_api()
    alpha: float; n_random_neg: int; n_random_pos: int; k: int | None; tau: float; guarantee: bool
    message: str | None; delta: float; recall: float | None; recall_ci95: tuple[float, float] | None

# monitor/
@dataclass
class DeployedRule:
    rule_id: str; concept_id: str; rule: Rule; tau: float; delta: float; actions: tuple[str, ...]; english: str

class Monitor:
    def __init__(self, *, perceive_fast: Callable[[EventInput], Trace], perceive_strong: Callable[[EventInput], Trace],
                 on_firing: Callable[[FiringRecord], None], on_event: Callable[[dict], None] = lambda e: None,
                 actions: ActionRunner | None = None): ...
    def deploy(self, r: DeployedRule) -> None: ...
    def undeploy(self, rule_id: str) -> None: ...
    def process(self, ev: EventInput) -> list[FiringRecord]: ...    # sync; H runs it in a worker thread
    def cost(self) -> dict: ...                                     # api.yaml CostSummary
@dataclass(frozen=True)
class EventInput:
    event_id: str; clip_id: str; clip_path: str | None; sub_type: str | None; device_id: str | None
    context: TraceContext; trace: Trace | None = None   # a pre-computed fast trace skips stage-1 perception
@dataclass(frozen=True)
class FiringRecord:      # one per (rule, event): api.yaml Firing; .to_api()
    id: str; rule_id: str; event_id: str; stage: int; score: float | None; tau: float | None; fired: bool
    witness: dict | None; actions: tuple[dict, ...]; created_at_ms: int
# on_event(...) receives MonitorEvent dicts (api.yaml MonitorEvent): escalated, rule_fired, rule_dropped, action_result, cost_update.
# Witness = exemplar.dsl.witness(rule, trace) + {"rule_id", "tau", "margin": score − tau}.
```

## H: `exemplar.store`, `exemplar.api`
- `exemplar.store.Store(db_path)`: sqlite3 over `contracts/schema.sql`. Repositories for every table, JSON columns holding `model_dump_json()`. It backs A's `TokenStore` (`ring_auth`) and `WebhookDeduper.claim` (`INSERT OR IGNORE` into `webhook_deliveries`).
- `exemplar.api.app` is the FastAPI app implementing every path in `contracts/api.yaml`. `uv run --project engine python -m exemplar.api` serves it on `settings.engine_host:engine_port` (127.0.0.1:8787).
- Ingest pipeline: Ring history poll (A `history`, every 15 s while a token is valid) or webhook → event row → wait for clip end + 5 s → `download_event_video`/`download_event_snapshot` → clip row → B `perceive_detailed` (fast; write the cost ledger unless `cached`) → trace row → `Monitor.process` for deployed rules. Fill `TraceContext.sub_type` (`"on_demand"` for Playground events), `event_kind`, `local_hour`, `weekday`, `device_id` and `started_at_ms` at ingest.
- `POST /uploads`: cut windows with ffmpeg (`imageio_ffmpeg`), source `upload`, `source_ref` and `attribution` on the clip.
- Teach: `run_cegis` in a worker thread. Each `emit` gets `seq`/`at_ms`, is stored in `run_events`, and is pushed to `/runs/{id}/stream`. Candidates go to `rules`.
- Question: `build_committee` + `select_query` over unlabelled traced clips. Backtest: `exemplar.dsl.robustness` per traced clip, `calibrate` on `random` labels only, `witness` for matches.
- Live: `POST /live/frames` stores JPEGs per session. `finish` builds a `ring_live` clip (frames → mp4 via ffmpeg, or a frame-list trace input), then perception, then the monitor.
- In tests, D's and E's functions are injected (FastAPI dependencies or a `Services` container), so H can run against fakes until D and E merge.
