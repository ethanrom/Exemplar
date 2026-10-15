"""Plain boolean evaluator (one of the independent implementations of the semantics in docs/DSL.md).

Deliberately independent of the robustness evaluator: pure Python loops over frame indices, window
membership decided with ``a <= (t_ms[j] - t_ms[i]) / 1000 <= b`` on Python ints, atoms read through
`Trace.signal` (the contract) and true iff ``s(t) > 0.5``. Slower than `robustness`, used as the oracle
in property tests and wherever only a yes/no is needed.
"""
from __future__ import annotations

from typing import Mapping, Optional

from pydantic import BaseModel

from ..contracts.dsl_ast import Always, And, Atom, Eventually, HoldsFor, Not, Or, Rule, Then
from ..contracts.ontology import THRESHOLD
from ..contracts.trace import Trace
from .evaluator import PreparedTrace, ctx_holds
from .util import bound_value, resolve_holes


def _window(ts: list[int], i: int, a: float, b: float) -> list[int]:
    return [j for j in range(len(ts)) if a <= (ts[j] - ts[i]) / 1000 <= b]


def truth_series(phi: BaseModel, trace: Trace, binding: Mapping[str, str]) -> list[bool]:
    """Boolean truth of ``phi`` at every frame for one binding (closed formula)."""
    if isinstance(trace, PreparedTrace):
        trace = trace.trace
    ts = [f.t_ms for f in trace.frames]
    return _truth(phi, trace, ts, dict(binding))


def _truth(n, tr: Trace, ts: list[int], env: dict[str, str]) -> list[bool]:
    T = len(ts)
    if isinstance(n, Atom):
        args = tuple(env.get(a, a) for a in n.args)
        return [bool(v > THRESHOLD) for v in tr.signal(n.pred, args).tolist()]
    if isinstance(n, Not):
        return [not v for v in _truth(n.arg, tr, ts, env)]
    if isinstance(n, And):
        cols = [_truth(c, tr, ts, env) for c in n.args]
        return [all(col[i] for col in cols) for i in range(T)]
    if isinstance(n, Or):
        cols = [_truth(c, tr, ts, env) for c in n.args]
        return [any(col[i] for col in cols) for i in range(T)]
    if isinstance(n, Eventually):
        x = _truth(n.arg, tr, ts, env)
        a, b = bound_value(n.a, None), bound_value(n.b, None)
        return [any(x[j] for j in _window(ts, i, a, b)) for i in range(T)]
    if isinstance(n, Always):
        x = _truth(n.arg, tr, ts, env)
        a, b = bound_value(n.a, None), bound_value(n.b, None)
        out = []
        for i in range(T):
            w = _window(ts, i, a, b)
            out.append(bool(w) and all(x[j] for j in w))      # an empty window is false (non-vacuous)
        return out
    if isinstance(n, Then):
        x = _truth(n.left, tr, ts, env)
        y = _truth(n.right, tr, ts, env)
        a, b = bound_value(n.a, None), bound_value(n.b, None)
        inner = [x[i] and any(y[j] for j in _window(ts, i, a, b)) for i in range(T)]
        return [any(inner[i:]) for i in range(T)]
    if isinstance(n, HoldsFor):
        x = _truth(n.arg, tr, ts, env)
        d = bound_value(n.d, None)
        inner = []
        for i in range(T):
            w = _window(ts, i, 0.0, d)
            fits = (ts[-1] - ts[i]) / 1000 >= d                # t1 + d <= t_end
            inner.append(fits and bool(w) and all(x[j] for j in w))
        return [any(inner[i:]) for i in range(T)]
    raise TypeError(f"not a formula: {n!r}")


def evaluate_bool(rule: Rule, trace: Trace, holes: Optional[Mapping[str, float]] = None) -> bool:
    """Does ``rule`` hold on ``trace``? exists binding, exists t: body(t) and every context atom.

    Same window semantics as `robustness` but computed independently (it is *not* ``robustness > 0``).
    A failed or empty trace is False. Holes are filled from ``holes`` or `UnboundHoleError` is raised.
    """
    if isinstance(trace, PreparedTrace):
        trace = trace.trace
    rule = resolve_holes(rule, holes)
    if trace.status != "ok" or not trace.frames:
        return False
    if not all(ctx_holds(c, trace.context) for c in rule.when):
        return False
    ts = [f.t_ms for f in trace.frames]
    names = [v.name for v in rule.vars]
    for b in trace.bindings(tuple(v.type for v in rule.vars)):
        if any(_truth(rule.body, trace, ts, dict(zip(names, b)))):
            return True
    return False
