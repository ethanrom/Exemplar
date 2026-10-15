"""Row -> api.yaml JSON converters."""
from __future__ import annotations

import json
from typing import Any

from pydantic_core import to_jsonable_python

from exemplar.contracts.trace import Trace
from exemplar.store import EventView, LabelRow, RuleRow, Store
from exemplar.store.repos import ConceptRow

PROVENANCE_WEIGHT = {"example": 3.0, "active": 3.0, "random": 1.0}     # WEIGHT_CONFIRMED / WEIGHT_BULK (labels.py)
BULK_WEIGHT = 1.0


def _fallback(o: Any) -> Any:
    """json fallback for numpy scalars / arrays and other stray types in events coming from other modules."""
    if hasattr(o, "item") and callable(o.item):
        try:
            return o.item()
        except (ValueError, TypeError):
            pass
    if hasattr(o, "tolist"):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(o)


def jsonable(obj: Any) -> Any:
    """Plain JSON types (dataclasses, pydantic models, tuples, numpy scalars all handled)."""
    return to_jsonable_python(obj, fallback=_fallback)


def label_summary(label: LabelRow | None) -> dict[str, Any] | None:
    return label.to_api() if label else None


def event_summary(v: EventView) -> dict[str, Any]:
    return {
        "id": v.id, "clip_id": v.clip_id, "source": v.source, "device_id": v.device_id, "kind": v.kind,
        "sub_type": v.sub_type, "start_ms": v.start_ms, "duration_ms": v.duration_ms,
        "clip_status": v.clip_status, "trace_status": v.trace_status,
        "summary": v.summary if v.trace_status == "ok" else None,
        "has_snapshot": v.has_snapshot, "attribution": v.attribution, "label": label_summary(v.label),
    }


def rule_summary(r: RuleRow) -> dict[str, Any]:
    return {
        "id": r.id, "concept_id": r.concept_id, "sketch_text": r.sketch_text, "dsl_text": r.dsl_text,
        "english": r.english, "ast": json.loads(r.ast_json), "holes": r.holes, "margin": r.margin, "mdl": r.mdl,
        "violated_clip_ids": r.violated_clip_ids, "status": r.status, "calibration": r.calibration,
        "actions": list(r.actions),
    }


def concept_view(store: Store, c: ConceptRow) -> dict[str, Any]:
    dep = store.rules.deployed_for_concept(c.id)
    return {"id": c.id, "name": c.name, "nl_hint": c.nl_hint, "alpha": c.alpha, "counts": store.concepts.counts(c.id),
            "deployed_rule_id": dep.id if dep else None}


def trace_text_fallback(trace: Trace) -> str:
    """Compact rendering used when `exemplar.synth.render_trace_text` is not available: one line per frame."""
    lines = [f"clip {trace.clip_id} ({trace.duration_ms / 1000:.1f} s): {trace.summary}".rstrip(": ")]
    if trace.entities:
        lines.append("entities: " + " ".join(
            f"{e.id}:{e.type}" + (f"[{','.join(e.attrs)}]" if e.attrs else "") for e in trace.entities))
    for fr in trace.frames:
        facts = " ".join(f"{f.pred}({','.join(f.args)})@{f.conf}" for f in fr.facts)
        lines.append(f"t={fr.t_ms / 1000:.1f}s {facts}".rstrip())
    return "\n".join(lines)
