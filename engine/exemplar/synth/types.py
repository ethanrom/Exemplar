"""Value types shared by the synthesis layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

from ..contracts.dsl_ast import Rule
from ..contracts.trace import Trace
from ..dsl import PreparedTrace, to_english, to_text

SolveStatus = Literal["sat", "unsat", "timeout", "grid_fallback"]


class SketchError(ValueError):
    """The sketch cannot be encoded (ill-typed, or a hole used as both an hour and a time)."""


class EncoderMismatch(AssertionError):
    """The Z3 encoding and the NumPy evaluator disagree.  This is an encoder (or evaluator) bug and must
    never be swallowed: every rule returned by `solve_sketch` has passed the differential check."""


@dataclass(frozen=True)
class Example:
    """One labelled clip given to the solver."""
    trace: Union[Trace, PreparedTrace]
    positive: bool
    weight: float = 1.0                 # Label.weight (1 bulk, 3 user-confirmed)
    clip_id: str = ""                   # defaults to trace.clip_id

    def __post_init__(self) -> None:
        if not self.clip_id:
            tr = self.trace.trace if isinstance(self.trace, PreparedTrace) else self.trace
            object.__setattr__(self, "clip_id", tr.clip_id)
        if not self.weight > 0:
            raise ValueError(f"example weight must be positive, got {self.weight}")

    @classmethod
    def from_label(cls, trace: Union[Trace, PreparedTrace], label) -> "Example":
        """Build from a `contracts.labels.Label` (clip_id comes from the label)."""
        return cls(trace=trace, positive=label.positive, weight=label.weight, clip_id=label.clip_id)


@dataclass(frozen=True)
class SolveResult:
    """Outcome of solving one sketch.

    status
      * ``sat``           the best MaxSMT assignment beats the trivial rule that never fires (its violated weight is
                          below the total positive weight), so it fits at least one positive example. ``rule`` is the
                          closed, temporal-slack-placed, differentially checked rule; ``violated`` lists the examples
                          it misses (empty = fully consistent, otherwise perception-suspect clips). Exact: the violated
                          weight is minimal and the margin maximal among minimal-weight assignments.
      * ``unsat``         even the best assignment is no better than "never fires": the sketch cannot express the
                          concept on these clips. ``rule`` is None.
      * ``timeout``       Z3 timed out and the grid fallback found nothing useful. ``rule`` is None.
      * ``grid_fallback`` Z3 timed out; ``rule`` is the best point of a 0.5 s grid search scored with the
                          NumPy evaluator (not guaranteed optimal).
    """
    status: SolveStatus
    sketch: Rule
    rule: Rule | None
    holes: dict[str, float]
    margin: float
    violated: tuple[str, ...]
    satisfied: tuple[str, ...]
    diff_check_ok: bool
    solve_ms: int
    note: str = ""

    @property
    def consistent(self) -> bool:
        """Rule found and no example violated."""
        return self.rule is not None and not self.violated


@dataclass(frozen=True)
class Candidate:
    """A ranked rule: what the agent returns and what the API stores (``RuleSummary``)."""
    sketch_text: str
    dsl_text: str                       # closed rule, from exemplar.dsl.to_text
    english: str                        # exemplar.dsl.to_english: deterministic, never an LLM paraphrase
    rule: Rule                          # CLOSED: holes filled, after temporal-slack placement
    holes: dict[str, float]
    margin: float
    mdl: float
    violated_clip_ids: tuple[str, ...]
    sketch: Rule | None = None          # the sketch with its holes (parsed from `sketch_text` when not given)

    def __post_init__(self) -> None:
        if self.sketch is None:
            from ..dsl import parse
            object.__setattr__(self, "sketch", parse(self.sketch_text))

    def to_api(self, *, id: str, concept_id: str, status: str = "candidate") -> dict:
        """api.yaml ``RuleSummary``."""
        return {
            "id": id, "concept_id": concept_id, "sketch_text": self.sketch_text, "dsl_text": self.dsl_text,
            "english": self.english, "ast": self.rule.model_dump(mode="json"),
            "holes": {k: float(v) for k, v in self.holes.items()}, "margin": float(self.margin),
            "mdl": float(self.mdl), "violated_clip_ids": list(self.violated_clip_ids), "status": status,
            "calibration": None, "actions": [],
        }

    @classmethod
    def from_result(cls, res: SolveResult, mdl_value: float) -> "Candidate":
        if res.rule is None:
            raise ValueError("cannot build a Candidate from a result without a rule")
        return cls(sketch_text=to_text(res.sketch), dsl_text=to_text(res.rule), english=to_english(res.rule),
                   rule=res.rule, holes=dict(res.holes), margin=res.margin, mdl=mdl_value,
                   violated_clip_ids=tuple(res.violated), sketch=res.sketch)
