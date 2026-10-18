"""Strict pydantic mirror of the data contract (SPEC 4.4). Every object forbids unknown keys, so a stray field such as a
device id or a cache key fails validation. Until the zod contract lands this is the key check for the export; it
matches lib/data/types.ts field for field."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from exemplar.contracts.dsl_ast import Rule
from exemplar.contracts.trace import Trace


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ------------------------------------------------------------------------------------------------ manifest
class FileEntry(_M):
    path: str
    bytes: int
    sha256: str


class SourceCounts(_M):
    key: Literal["recording", "heldout", "stills"]
    rows: dict[str, int]


class AssertEntry(_M):
    id: str
    ok: Literal[True]
    detail: str


class PgCounts(_M):
    package: int
    vehicle: int
    bird: int


class Counts(_M):
    library: int
    playground: PgCounts


class Manifest(_M):
    schema_: Literal["exemplar.showcase/1"] = Field(alias="schema")
    exported_on: str
    engine_commit: str
    sources: list[SourceCounts]
    asserts: list[AssertEntry]
    counts: Counts
    files: list[FileEntry]


# ------------------------------------------------------------------------------------------------ shared
class Calibration(_M):
    alpha: float
    n_random_neg: int
    n_random_pos: int
    k: Optional[int]
    tau: float
    guarantee: bool
    message: Optional[str]
    delta: float
    recall: Optional[float]
    recall_ci95: Optional[list[float]]


class Span(_M):
    path: str
    op: str
    text: Optional[str] = None
    t_start_ms: int
    t_end_ms: int
    rho: float


class Witness(_M):
    rule_id: str
    clip_id: str
    score: float
    tau: Optional[float] = None
    margin: Optional[float] = None
    bindings: dict[str, str]
    entities: list[dict[str, Any]] = []
    spans: list[Span]
    english: Optional[str] = None


# ------------------------------------------------------------------------------------------------ library
class RecordedLabel(_M):
    concept: str
    label: Literal["pos", "neg"]
    provenance: Literal["example", "active", "random"]


class ClipCard(_M):
    alias: str
    title: str
    source: Literal["playground", "cc_by", "meva"]
    class_: Literal["pg_package", "pg_vehicle", "pg_bird", "frollard", "meva", "ringtv_fox"] = Field(alias="class")
    duration_ms: int
    recorded_on: Optional[str] = None
    summary: str
    credit: str
    media: Literal["frames", "trace_only"]
    poster: Optional[str] = None
    sheet: Optional[str] = None
    sheet_times_ms: list[int]
    curated: Optional[int] = None
    recorded_labels: list[RecordedLabel]


# ------------------------------------------------------------------------------------------------ runs
class RunConcept(_M):
    slug: str
    name: str
    nl_hint: str
    alpha: float


class RunExample(_M):
    alias: str
    label: Literal["pos", "neg"]
    provenance: Literal["example", "active"]
    weight: float


class RunEvent(_M):
    seq: int
    t_ms: int
    type: Literal["round_started", "sketch_proposed", "typecheck_failed", "solve_started", "solve_result",
                  "differential_check", "counterexample", "candidates", "question_ready", "done", "error"]
    round: Optional[int] = None
    sketch: Optional[str] = None
    error: Optional[str] = None
    result: Optional[Literal["sat", "unsat", "timeout", "grid_fallback"]] = None
    holes: Optional[dict[str, float]] = None
    margin: Optional[float] = None
    violated_clip_ids: Optional[list[str]] = None
    rule_ids: Optional[list[str]] = None
    message: Optional[str] = None


class Proposals(_M):
    round: int
    backfill: bool
    texts: list[str]


class RunDoc(_M):
    slug: str
    title: str
    concept: RunConcept
    source: Literal["recording", "heldout", "stills"]
    duration_ms: int
    proposer_note: str
    examples: list[RunExample]
    events: list[RunEvent]
    proposals_by_round: list[Proposals]
    candidates: list[str]


# ------------------------------------------------------------------------------------------------ rules
class RecordedRank(_M):
    run: str
    position: int
    of: int


class BacktestRow(_M):
    alias: str
    score: float
    matched: bool


class RuleDoc(_M):
    slug: str
    run: Optional[str]
    concept: str
    status: Literal["deployed", "candidate", "retired"]
    recorded_rank: Optional[RecordedRank]
    selection: Optional[Literal["chosen_by_user_and_deployed", "selected_for_display_as_demo_equivalent"]]
    ast: dict[str, Any]
    sketch_text: str
    dsl_text: str
    english: str
    holes: dict[str, float]
    margin: float
    mdl: float
    violations: list[str]
    tau: Optional[float]
    delta: float
    calibration: Optional[Calibration]
    box: Optional[dict[str, list[float]]] = None
    backtest: list[BacktestRow]

    def check_ast(self) -> None:
        Rule.model_validate(self.ast)


# ------------------------------------------------------------------------------------------------ live / calibration
class Decision(_M):
    rule: str
    stage: Literal[0, 1, 2]
    score: float
    tau: float
    fired: bool
    witness: Optional[Witness]


class LiveEvent(_M):
    alias: str
    order: Literal[1, 2, 3, 4, 5]
    class_: Literal["pg_package", "pg_vehicle", "pg_bird"] = Field(alias="class")
    decisions: list[Decision]


class LiveDoc(_M):
    events: list[LiveEvent]


class CalProvenance(_M):
    random_labels: int
    drawn_via: Literal["random-sample endpoint"]
    disjoint_from_examples: Literal[True]
    disjoint_from_curated: Literal[True]


class CalPoint(_M):
    alias: str
    label: Literal["pos", "neg"]
    score: float


class CalDoc(_M):
    concept: Literal["package"]
    alpha: float
    rule: Literal["package-deployed"]
    scope: Literal["stage1_fast_perception"]
    provenance: CalProvenance
    random: list[CalPoint]
    calibration: Calibration


# ------------------------------------------------------------------------------------------------ credits / claims / lab
class Permission(_M):
    basis: Literal["cc_by", "own_work", "ring_sandbox", "open_source"]
    status: Literal["cleared", "pending_user_decision"]
    evidence: str
    checked_on: str


class CreditEntry(_M):
    id: str
    group: Literal["playground_frollard_derived", "playground_other", "cc_by", "meva", "software"]
    title: str
    author: Optional[str] = None
    url: Optional[str] = None
    licence: str
    licence_url: Optional[str] = None
    permission: Permission
    modification: Optional[str] = None
    note: Optional[str] = None
    aliases: list[str]


class ClaimSource(_M):
    path: str
    line: int
    quote: str


class Claim(_M):
    id: str
    display: str
    source: ClaimSource


class ClaimsDoc(_M):
    source: str
    note: str
    claims: list[Claim]


class CuratedDoc(_M):
    clips: list[str]
    default: list[Optional[Literal["pos", "neg"]]]


class Sketch(_M):
    id: int
    text: str
    holes: list[str]
    from_runs: list[str]


def validate_trace(d: dict) -> None:
    Trace.model_validate(d)
