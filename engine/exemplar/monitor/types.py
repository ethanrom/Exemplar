"""Value types of the online monitor (docs/streams/phase2-interfaces.md, E section)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from exemplar.contracts.dsl_ast import Rule
from exemplar.contracts.trace import Trace, TraceContext


@dataclass(frozen=True)
class EventInput:
    """One Ring event (or live capture / upload) to run through the deployed rules."""

    event_id: str
    clip_id: str
    clip_path: Optional[str]
    sub_type: Optional[str]                  # Ring smart-alert sub_type, "on_demand" for Playground events, or None
    device_id: Optional[str]
    context: TraceContext
    trace: Optional[Trace] = None            # a pre-computed fast trace skips stage-1 perception
    trace_cached: bool = False               # that trace was already paid for (cache hit / ledger written at ingest)


@dataclass
class DeployedRule:
    rule_id: str
    concept_id: str
    rule: Rule                               # closed
    tau: float                               # fire iff score > tau (Calibration.tau)
    delta: float = 0.1                       # escalation half-width (Calibration.delta)
    actions: tuple[str, ...] = ("ui",)       # subset of ui | webhook_out | slack | chime ("ui" always runs)
    english: str = ""                        # deterministic printer output; derived from `rule` when empty


@dataclass(frozen=True)
class FiringRecord:
    """The outcome for one (rule, event): fired or dropped, and the stage that decided it (api.yaml `Firing`)."""

    id: str
    rule_id: str
    event_id: str
    stage: int                               # 0 sub_type prefilter, 1 fast perception, 2 escalated
    score: Optional[float]
    tau: Optional[float]
    fired: bool
    witness: Optional[dict]
    actions: tuple[dict, ...]                # {"action", "status": ok|skipped|failed, "detail"}
    created_at_ms: int
    message: Optional[str] = None            # why it was dropped / how it was decided (not part of api.yaml `Firing`)

    def to_api(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "event_id": self.event_id,
            "stage": int(self.stage),
            "score": None if self.score is None else float(self.score),
            "tau": None if self.tau is None else float(self.tau),
            "fired": bool(self.fired),
            "witness": self.witness,
            "actions": [{"action": a["action"], "status": a["status"], "detail": a.get("detail")} for a in self.actions],
            "created_at_ms": int(self.created_at_ms),
        }
