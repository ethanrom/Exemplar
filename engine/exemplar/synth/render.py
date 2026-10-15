"""Compact, deterministic text rendering of a `Trace` for the sketch LLM and the UI (``EventDetail.trace_text``).

Example::

    clip theft_a: 20.0 s, 9 frames (ok)
    context: sub_type=human, local_hour=14
    entities: p1 person {hoodie}; k1 package {box}
    t=0s: in_zone(k1,porch)[high]
    t=2s: in_zone(k1,porch)[high] enters(p1,porch)[med]
    t=4s..8s (3 frames, same facts): ...
    t=16s: (no facts)
"""
from __future__ import annotations

from ..contracts.ontology import PREDICATES
from ..contracts.trace import Fact, Trace
from ..dsl.util import fmt_num

_PRED_ORDER = {p: i for i, p in enumerate(PREDICATES)}


def _t(ms: int) -> str:
    return fmt_num(ms / 1000) + "s"


def _fact_key(f: Fact) -> tuple:
    return (_PRED_ORDER.get(f.pred, 99), f.pred, f.args, f.conf)


def _fact_text(f: Fact) -> str:
    return f"{f.pred}({','.join(f.args)})[{f.conf}]"


def render_trace_text(trace: Trace) -> str:
    """Entities with their attributes, then one line per run of identical frames: ``t=<s>: pred(args)[conf] ...``.

    Facts are sorted by (ontology predicate order, args), so equal traces always render identically.
    ``present(e)`` is implied by any other fact on ``e`` and is only shown when asserted explicitly.
    """
    head = f"clip {trace.clip_id}: {fmt_num(trace.duration_ms / 1000)} s, {len(trace.frames)} frames ({trace.status})"
    lines = [head]
    if trace.status != "ok":
        lines.append(f"perception failed: {trace.error or 'unknown error'}")
        return "\n".join(lines)
    ctx = trace.context
    bits = []
    for name in ("sub_type", "event_kind", "local_hour", "weekday", "device_id"):
        v = getattr(ctx, name)
        if v is not None:
            bits.append(f"{name}={v}")
    if bits:
        lines.append("context: " + ", ".join(bits))
    if trace.entities:
        lines.append("entities: " + "; ".join(
            f"{e.id} {e.type}" + (" {" + ", ".join(e.attrs) + "}" if e.attrs else "") for e in trace.entities))
    else:
        lines.append("entities: (none)")
    frames = [(f.t_ms, tuple(sorted(set(f.facts), key=_fact_key))) for f in trace.frames]
    i = 0
    while i < len(frames):
        j = i
        while j + 1 < len(frames) and frames[j + 1][1] == frames[i][1]:
            j += 1
        facts = " ".join(_fact_text(f) for f in frames[i][1]) or "(no facts)"
        if j == i:
            lines.append(f"t={_t(frames[i][0])}: {facts}")
        else:
            lines.append(f"t={_t(frames[i][0])}..{_t(frames[j][0])} ({j - i + 1} frames, same facts): {facts}")
        i = j + 1
    if trace.summary:
        lines.append(f"summary: {trace.summary}")
    return "\n".join(lines)
