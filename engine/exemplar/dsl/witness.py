"""Witness extraction: why a rule scored what it did (PLAN.md §2.6, api.yaml `Witness`).

Deterministic: ties go to the first binding (in `Trace.bindings` order) and the earliest frame.

Result (api.yaml `Witness` minus ``rule_id`` / ``tau`` / ``margin``, which the monitor adds)::

    {"clip_id": str, "score": float, "bindings": {var: entity_id}, "entities": [Entity as dict],
     "spans": [{"path": "body.left", "op": "atom", "text": "picks_up(p, k)",
                "t_start_ms": int, "t_end_ms": int, "rho": float}, ...],
     "english": str}

``spans`` is pre-order. It covers the nodes the argmax descends through: every temporal node
(eventually / always / then / holds_for), every atom reached (the evidence facts), every ``not`` reached
(a point span at the evaluation time, with the positive robustness of the absence; the descent stops
there), and the body root when it is an and / or (covering all the times its evidence spans touch).

Times per op:  atom, not -> the frame; eventually -> the chosen frame t' (argmax of the operand in the
window); always -> first..last frame of the window, descending into the weakest frame; then -> from the
chosen t1 to the chosen t2; holds_for -> from t1 to the last frame in [t1, t1 + d], descending into the
weakest frame; or -> descends into the best branch; and -> descends into all branches.
"""
from __future__ import annotations

from typing import Mapping, Optional

import numpy as np

from ..contracts.dsl_ast import Rule
from ..contracts.ontology import CLAMP
from ..contracts.trace import Trace
from .english import to_english
from .evaluator import CompiledRule, PreparedTrace, _Ev, _eval, ctx_value, prepare
from .printer import to_text
from .util import resolve_holes

C = CLAMP


def witness(rule: Rule, trace: Trace, holes: Optional[Mapping[str, float]] = None) -> dict:
    """Witness for ``rule`` on ``trace`` (the argmax binding and the times behind the score).

    Works for non-matching clips too (the witness then shows the closest the rule got). With no
    bindings or a failed trace: score -C, empty bindings and spans.
    """
    rule = resolve_holes(rule, holes)
    prep = prepare(trace)
    tr = prep.trace
    out = {"clip_id": tr.clip_id, "score": -C, "bindings": {}, "entities": [], "spans": [],
           "english": to_english(rule)}
    cr = CompiledRule(rule)
    bindings = prep.bindings(cr.types) if prep.ok else []
    if not bindings:
        return out
    env = prep.env(("T", cr.names, cr.types), cr.names, bindings)
    body = _eval(cr.ir, _Ev(prep, env, None))                       # (B, T)
    flat = int(np.argmax(body))                                     # first binding, then earliest frame
    bi, ti = divmod(flat, body.shape[1])
    ctx = ctx_value(cr.when, tr.context)
    out["score"] = min(float(body[bi, ti]), ctx)
    chosen = bindings[bi]
    out["bindings"] = dict(zip(cr.names, chosen))
    out["entities"] = [tr.entity(e).model_dump(mode="json") for e in chosen if tr.entity(e) is not None]

    env1 = prep.env(("B", cr.names, chosen), cr.names, [chosen])
    ev = _Ev(prep, env1, None, record=True)
    _eval(cr.ir, ev)
    spans: list[dict] = []
    _explain(cr.ir, ti, "body", ev, prep, spans)
    if cr.ir.op in ("and", "or"):          # root span covers everything its evidence touches
        root = _span("body", cr.ir, ti, ti, float(ev.memo[id(cr.ir)][0, ti]), prep)
        root["t_start_ms"] = min(sp["t_start_ms"] for sp in spans)
        root["t_end_ms"] = max(sp["t_end_ms"] for sp in spans)
        spans.insert(0, root)
    out["spans"] = spans
    return out


def _span(path: str, n, i: int, j: int, rho: float, prep: PreparedTrace) -> dict:
    return {"path": path, "op": n.op, "text": to_text(n.node),
            "t_start_ms": int(prep.t_ms[i]), "t_end_ms": int(prep.t_ms[j]), "rho": float(rho)}


def _first_at_or_after(inner: np.ndarray, t: int, val: float) -> int:
    """Earliest frame t1 >= t whose inner value attains ``val`` (the max over t1 >= t)."""
    tail = inner[t:]
    hit = np.flatnonzero(tail == val)
    return t + int(hit[0] if hit.size else np.argmax(tail))


def _explain(n, t: int, path: str, ev: _Ev, prep: PreparedTrace, spans: list[dict]) -> None:
    """Append spans for node ``n`` evaluated at frame index ``t`` and recurse into its evidence."""
    series = lambda k: ev.memo[id(k)][0]
    val = float(series(n)[t])
    op = n.op
    if op in ("atom", "not"):
        spans.append(_span(path, n, t, t, val, prep))
    elif op == "and":
        for i, k in enumerate(n.kids):
            _explain(k, t, f"{path}.args[{i}]", ev, prep, spans)
    elif op == "or":
        vals = [float(series(k)[t]) for k in n.kids]
        j = int(np.argmax(vals))                                    # first best branch
        _explain(n.kids[j], t, f"{path}.args[{j}]", ev, prep, spans)
    elif op in ("eventually", "always"):
        M, _ = prep.window(_hv(n.a, ev), _hv(n.b, ev))
        idx = np.flatnonzero(M[t])
        if idx.size == 0:                                           # empty window: nothing to point at
            spans.append(_span(path, n, t, t, val, prep))
            return
        x = series(n.kids[0])[idx]
        if op == "eventually":
            j = int(idx[np.argmax(x)])
            spans.append(_span(path, n, j, j, val, prep))
        else:
            j = int(idx[np.argmin(x)])
            spans.append(_span(path, n, int(idx[0]), int(idx[-1]), val, prep))
        _explain(n.kids[0], j, f"{path}.arg", ev, prep, spans)
    elif op == "then":
        inner = ev.extra[id(n)][0]
        t1 = _first_at_or_after(inner, t, val)
        M, _ = prep.window(_hv(n.a, ev), _hv(n.b, ev))
        idx = np.flatnonzero(M[t1])
        if idx.size == 0:
            spans.append(_span(path, n, t1, t1, val, prep))
            _explain(n.kids[0], t1, f"{path}.left", ev, prep, spans)
            return
        y = series(n.kids[1])[idx]
        t2 = int(idx[np.argmax(y)])
        spans.append(_span(path, n, t1, t2, val, prep))
        _explain(n.kids[0], t1, f"{path}.left", ev, prep, spans)
        _explain(n.kids[1], t2, f"{path}.right", ev, prep, spans)
    elif op == "holds_for":
        inner = ev.extra[id(n)][0]
        t1 = _first_at_or_after(inner, t, val)
        M, _ = prep.window(0.0, _hv(n.a, ev))
        idx = np.flatnonzero(M[t1])
        if idx.size == 0:
            spans.append(_span(path, n, t1, t1, val, prep))
            return
        j = int(idx[np.argmin(series(n.kids[0])[idx])])             # weakest frame of the run
        spans.append(_span(path, n, t1, int(idx[-1]), val, prep))
        _explain(n.kids[0], j, f"{path}.arg", ev, prep, spans)


def _hv(x, ev: _Ev) -> float:
    return float(x) if not isinstance(x, str) else float(ev.holes[x])
