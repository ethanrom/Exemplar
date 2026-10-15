"""The online monitor: stage 0 prune -> stage 1 fast score -> stage 2 escalation -> fire or drop.

For each event and every deployed rule exactly one `FiringRecord` is produced:

    stage 0  Ring sub_type makes the rule impossible (no perception at all)        -> rule_dropped (stage 0)
    stage 1  one fast trace per event, shared by all remaining rules; score each    -> fire iff score > tau
    stage 2  if |score - tau| <= delta for any rule, ONE strong trace per event;    -> fire iff strong score > tau
             those rules are re-scored on it (the decision uses the strong score)

A fired rule carries `exemplar.dsl.witness(rule, trace)` plus ``rule_id``, ``tau`` and ``margin = score - tau``
(computed on the trace that decided it), then runs its actions. MonitorEvents emitted through ``on_event``:
``escalated``, ``rule_fired`` (by the ui action), ``rule_dropped``, ``action_result``, ``cost_update`` (once per
event) and ``error`` (escalation failed).

Failure policy (the monitor never raises for perception problems):

* stage-1 perception raises or returns a ``perception_failed`` trace: every remaining rule is dropped at stage 1
  with the reason as the message.
* stage-2 (strong) perception fails: the rules keep their stage-1 decision (the calibrated one, whose false-alarm
  bound is the one proved); the message says so and an ``error`` event is emitted. Falling back instead of dropping
  avoids silently losing a borderline true positive.
* ``on_event`` / ``on_firing`` callbacks that raise are logged and ignored.

``perceive_fast`` / ``perceive_strong`` may return a `Trace` or a `PerceptionResult` (anything with ``.trace``
and ``.cached``); cached results add no tokens to the cost meter.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import time
from typing import Any, Callable, Optional

from exemplar.contracts.dsl_ast import holes as ast_holes
from exemplar.contracts.trace import Trace
from exemplar.dsl import CompiledRule, compile_rule, prepare, to_english, witness as dsl_witness

from .actions import ActionContext, ActionRunner
from .cost import CostMeter, Prices
from .stage0 import stage0_reason
from .types import DeployedRule, EventInput, FiringRecord

log = logging.getLogger("exemplar.monitor")

BAND_EPS = 1e-9          # |score - tau| <= delta is inclusive; absorbs float noise like 0.6 - 0.5


def _noop(_: dict) -> None:
    return None


def _unwrap(res: Any) -> tuple[Trace, bool]:
    """(trace, cached) from a Trace or a PerceptionResult-like object."""
    if isinstance(res, Trace):
        return res, False
    tr = getattr(res, "trace", None)
    if isinstance(tr, Trace):
        return tr, bool(getattr(res, "cached", False))
    raise TypeError(f"perceive_* must return a Trace or a PerceptionResult, got {type(res).__name__}")


def _effective_actions(names: tuple[str, ...]) -> list[str]:
    out = ["ui"]                                     # the in-app notification is always on and always first
    for n in names:
        if n not in out:                             # each action runs at most once per firing
            out.append(n)
    return out


class Monitor:
    def __init__(self, *, perceive_fast: Callable[[EventInput], Any], perceive_strong: Callable[[EventInput], Any],
                 on_firing: Callable[[FiringRecord], None], on_event: Callable[[dict], None] = _noop,
                 actions: Optional[ActionRunner] = None, prices: Optional[Prices] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._fast, self._strong = perceive_fast, perceive_strong
        self._on_firing, self._on_event = on_firing, on_event
        self._actions = actions if actions is not None else ActionRunner()
        self._meter = CostMeter(prices)
        self._clock = clock
        self._lock = threading.RLock()
        self._rules: dict[str, tuple[DeployedRule, CompiledRule]] = {}

    # ------------------------------------------------------------------ deployment
    def deploy(self, r: DeployedRule) -> None:
        """Start monitoring with ``r`` (replaces a rule with the same id). The rule must be closed."""
        left = ast_holes(r.rule)
        if left:
            raise ValueError(f"cannot deploy rule {r.rule_id!r}: unfilled holes {left}")
        if not r.english:
            r = dataclasses.replace(r, english=to_english(r.rule))
        compiled = compile_rule(r.rule)
        with self._lock:
            self._rules[r.rule_id] = (r, compiled)

    def undeploy(self, rule_id: str) -> None:
        with self._lock:
            self._rules.pop(rule_id, None)

    def deployed(self) -> list[DeployedRule]:
        with self._lock:
            return [r for r, _ in self._rules.values()]

    def cost(self) -> dict:
        """api.yaml `CostSummary`."""
        return self._meter.snapshot()

    # ------------------------------------------------------------------ plumbing
    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    def _emit(self, event: dict) -> None:
        event.setdefault("at_ms", self._now_ms())
        try:
            self._on_event(event)
        except Exception:
            log.exception("on_event callback raised (ignored)")

    def _record(self, dr: DeployedRule, ev: EventInput, stage: int, score: Optional[float], fired: bool,
                witness: Optional[dict] = None, message: Optional[str] = None) -> FiringRecord:
        return FiringRecord(id=f"fir_{dr.rule_id}_{ev.event_id}", rule_id=dr.rule_id, event_id=ev.event_id, stage=stage,
                            score=score, tau=dr.tau, fired=fired, witness=witness, actions=(),
                            created_at_ms=self._now_ms(), message=message)

    def _finish(self, rec: FiringRecord) -> FiringRecord:
        try:
            self._on_firing(rec)
        except Exception:
            log.exception("on_firing callback raised (ignored)")
        return rec

    def _drop(self, dr: DeployedRule, ev: EventInput, stage: int, score: Optional[float], message: str) -> FiringRecord:
        rec = self._record(dr, ev, stage, score, False, message=message)
        self._emit({"type": "rule_dropped", "event_id": ev.event_id, "rule_id": dr.rule_id, "firing": rec.to_api(),
                    "message": message})
        return self._finish(rec)

    @staticmethod
    def _with_context(trace: Trace, ev: EventInput) -> Trace:
        """The trace with the event's context overlaid (non-None fields of ``ev.context``, sub_type, device_id)."""
        upd = {k: v for k, v in ev.context.model_dump().items() if v is not None}
        if ev.sub_type is not None:
            upd["sub_type"] = ev.sub_type
        if ev.device_id is not None:
            upd["device_id"] = ev.device_id
        ctx = trace.context.model_copy(update=upd)
        return trace if ctx == trace.context else trace.model_copy(update={"context": ctx})

    def _perceive(self, fn: Callable[[EventInput], Any], ev: EventInput, tier: str) -> Trace:
        """Run a perceiver and book its tokens. Raises on exceptions and on perception_failed traces."""
        trace, cached = _unwrap(fn(ev))
        if not cached:
            self._meter.add_tokens(tier, trace.perception)
        if trace.status != "ok":
            raise _PerceptionFailed(trace.error or "perception_failed")
        return trace

    # ------------------------------------------------------------------ the funnel
    def process(self, ev: EventInput) -> list[FiringRecord]:
        """Run one event through every deployed rule; returns one record per rule (fired or dropped)."""
        with self._lock:
            rules = list(self._rules.values())
        self._meter.add(events=1)
        out: dict[str, FiringRecord] = {}

        live: list[tuple[DeployedRule, CompiledRule]] = []
        for dr, cr in rules:                                                       # stage 0
            reason = stage0_reason(dr.rule, ev.sub_type)
            if reason:
                self._meter.add(stage0_dropped=1)
                out[dr.rule_id] = self._drop(dr, ev, 0, None, f"stage 0: {reason}")
            else:
                live.append((dr, cr))
        if live:
            self._stage1_and_2(ev, live, out)
        self._emit({"type": "cost_update", "event_id": ev.event_id, "cost": self.cost()})
        return [out[dr.rule_id] for dr, _ in rules]

    def _stage1_and_2(self, ev: EventInput, live: list[tuple[DeployedRule, CompiledRule]],
                      out: dict[str, FiringRecord]) -> None:
        try:                                                                       # stage 1
            if ev.trace is not None:
                trace = ev.trace
                if not ev.trace_cached:
                    self._meter.add_tokens("fast", trace.perception)
                if trace.status != "ok":
                    raise _PerceptionFailed(trace.error or "perception_failed")
            else:
                trace = self._perceive(self._fast, ev, "fast")
        except Exception as e:
            log.warning("stage-1 perception failed for event %s: %s: %s", ev.event_id, type(e).__name__, e)
            for dr, _ in live:
                out[dr.rule_id] = self._drop(dr, ev, 1, None, f"stage 1: perception failed ({_why(e)})")
            return
        fast = self._with_context(trace, ev)
        prep = prepare(fast)
        scored = []
        for dr, cr in live:
            self._meter.add(stage1_scored=1)
            scored.append((dr, cr, cr.score(prep)))

        band = [(dr, cr, s) for dr, cr, s in scored if abs(s - dr.tau) <= dr.delta + BAND_EPS]
        strong: Optional[Trace] = None
        strong_note = ""
        if band:                                                                   # stage 2
            self._meter.add(stage2_escalated=len(band))
            for dr, _, s in band:
                self._emit({"type": "escalated", "event_id": ev.event_id, "rule_id": dr.rule_id,
                            "message": f"score {s:+.2f} is within {dr.delta:g} of tau {dr.tau:g}: escalating to the strong model"})
            try:
                strong = self._with_context(self._perceive(self._strong, ev, "strong"), ev)
            except Exception as e:
                log.warning("stage-2 perception failed for event %s: %s: %s", ev.event_id, type(e).__name__, e)
                strong_note = f"escalation failed ({_why(e)}); decided on the stage-1 score"
                self._emit({"type": "error", "event_id": ev.event_id,
                            "message": f"strong perception failed for event {ev.event_id}: {_why(e)}"})
        strong_prep = prepare(strong) if strong is not None else None
        in_band = {dr.rule_id for dr, _, _ in band}

        for dr, cr, s1 in scored:
            if strong_prep is not None and dr.rule_id in in_band:
                s2 = cr.score(strong_prep)
                out[dr.rule_id] = self._decide(dr, ev, strong, s2, 2, f"stage 1 score {s1:+.2f}, strong score {s2:+.2f}")
            else:
                note = strong_note if dr.rule_id in in_band else ""
                out[dr.rule_id] = self._decide(dr, ev, fast, s1, 1, note)

    def _decide(self, dr: DeployedRule, ev: EventInput, trace: Trace, score: float, stage: int, note: str) -> FiringRecord:
        if not score > dr.tau:
            msg = f"stage {stage}: score {score:+.2f} <= tau {dr.tau:g}" + (f" ({note})" if note else "")
            return self._drop(dr, ev, stage, score, msg)
        w = dsl_witness(dr.rule, trace)
        w.update(rule_id=dr.rule_id, tau=dr.tau, margin=score - dr.tau)
        msg = f"stage {stage}: score {score:+.2f} > tau {dr.tau:g}" + (f" ({note})" if note else "")
        rec = self._record(dr, ev, stage, score, True, witness=w, message=msg)
        results = self._actions.run(_effective_actions(dr.actions), ActionContext(
            rule=dr, record=rec, event=ev, trace=trace, emit=self._emit))
        return self._finish(dataclasses.replace(rec, actions=tuple(results)))


class _PerceptionFailed(RuntimeError):
    """A trace with status 'perception_failed' (perception exhausted its retries)."""


def _why(e: BaseException) -> str:
    return str(e) if isinstance(e, _PerceptionFailed) else f"{type(e).__name__}: {e}"
