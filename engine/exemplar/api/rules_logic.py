"""Rule lifecycle: calibration, backtest, deploy.

Calibration uses ONLY `random`-provenance labels (docs/DSL.md): actively chosen or hand-picked
clips are not exchangeable with deployment events, so including them would void the conformal guarantee.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from exemplar.contracts.dsl_ast import Rule
from exemplar.contracts.labels import Label
from exemplar.contracts.trace import Trace
from exemplar.dsl import prepare, robustness, witness
from exemplar.store import LabelRow, RuleRow

from .serialize import event_summary, jsonable

if TYPE_CHECKING:  # pragma: no cover
    from .state import AppState

log = logging.getLogger("exemplar.api.rules")

CALIBRATION_PROVENANCE = ("random",)


def to_label(row: LabelRow) -> Label:
    return Label(concept_id=row.concept_id, clip_id=row.clip_id, value=row.value, provenance=row.provenance,  # type: ignore[arg-type]
                 weight=row.weight, created_at=datetime.fromtimestamp(row.created_at_ms / 1000, tz=timezone.utc))


def calibration_set(state: "AppState", concept_id: str) -> list[tuple[Trace, Label]]:
    """(trace, label) for the concept's random-provenance labels whose clips have an ok trace."""
    rows = state.store.labels.list(concept_id, provenance=CALIBRATION_PROVENANCE)
    traces = state.store.traces.primary_ok_for([r.clip_id for r in rows])
    pairs = [(traces[r.clip_id], to_label(r)) for r in rows if r.clip_id in traces]
    assert all(l.provenance == "random" for _, l in pairs), "calibration must use random labels only"
    return pairs


def calibrate_rule(state: "AppState", row: RuleRow) -> dict[str, Any]:
    """Run `calibrate` on the random labels, store tau/delta/calibration_json, refresh a deployed monitor."""
    calibrate = state.services.calibrate
    concept = state.store.concepts.get(row.concept_id)
    assert concept is not None
    rule = Rule.model_validate_json(row.ast_json)
    cal = calibrate(rule, calibration_set(state, concept.id), concept.alpha)
    api = jsonable(cal.to_api())
    state.store.rules.set_calibration(row.id, tau=float(api["tau"]), delta=float(api.get("delta", row.delta)),
                                      calibration=api)
    fresh = state.store.rules.get(row.id)
    if fresh is not None and fresh.status == "deployed" and state.monitor_if_ready() is not None:
        state.deploy_rule(fresh)                       # monitor picks up the new tau / delta
    return api


def backtest(state: "AppState", row: RuleRow) -> dict[str, Any]:
    """Score every traced clip with the DSL's `robustness`; calibration from random labels; witnesses for matches."""
    cal = calibrate_rule(state, row)
    tau = float(cal["tau"])
    rule = Rule.model_validate_json(row.ast_json)
    labels = {l.clip_id: l for l in state.store.labels.list(row.concept_id)}
    traces = state.store.traces.list_primary_ok()
    views = state.store.events.views_by_clips([cid for cid, _ in traces], row.concept_id)
    rows: list[dict[str, Any]] = []
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "unlabelled_matches": 0}
    for clip_id, trace in traces:
        score = float(robustness(rule, prepare(trace)))
        matched = score > tau
        lab = labels.get(clip_id)
        w = None
        if matched:
            w = jsonable(witness(rule, trace))
            w.update(rule_id=row.id, tau=tau, margin=score - tau)
        if lab is None:
            counts["unlabelled_matches"] += int(matched)
        elif lab.value == "pos":
            counts["tp" if matched else "fn"] += 1
        else:
            counts["fp" if matched else "tn"] += 1
        view = views.get(clip_id)
        rows.append({"clip_id": clip_id, "event": event_summary(view) if view else None, "score": score,
                     "matched": matched, "label": lab.to_api() if lab else None, "witness": w})
    rows.sort(key=lambda r: (-r["score"], r["clip_id"]))
    for r in rows:
        if r["event"] is None:
            del r["event"]
    return {"rule_id": row.id, "rows": rows, "calibration": cal, "counts": counts}


def set_deployed(state: "AppState", row: RuleRow) -> RuleRow:
    """status -> deployed: calibrate if needed, retire the concept's previous deployment, register with the monitor."""
    state.services.monitor_cls            # 503 before touching the DB when E is missing
    state.services.deployed_rule_cls
    if row.tau is None:
        calibrate_rule(state, row)
    for other in state.store.rules.list_for_concept(row.concept_id):
        if other.status == "deployed" and other.id != row.id:
            state.store.rules.update(other.id, status="selected")
            state.undeploy_rule(other.id)
    state.store.rules.update(row.id, status="deployed")
    fresh = state.store.rules.get(row.id)
    assert fresh is not None
    state.deploy_rule(fresh)
    return fresh
