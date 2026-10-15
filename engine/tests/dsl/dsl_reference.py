"""Reference semantics, written as literally as possible from PLAN.md §2.2: scalar Python recursion, no
NumPy, no shared code with `exemplar.dsl.evaluator`. Slow; used to cross-check the vectorised evaluator."""
from __future__ import annotations

from exemplar.contracts.dsl_ast import Always, And, Atom, Eventually, HoldsFor, Not, Or, Rule, Then
from exemplar.contracts.ontology import CLAMP, THRESHOLD
from exemplar.contracts.trace import Trace

C = CLAMP


class Ref:
    def __init__(self, trace: Trace, binding: dict[str, str]):
        self.tr = trace
        self.binding = binding
        self.ts = [f.t_ms for f in trace.frames]
        self.T = len(self.ts)
        self.memo: dict = {}

    def delta(self, i: int, j: int) -> float:
        return (self.ts[j] - self.ts[i]) / 1000

    def window(self, i: int, a: float, b: float) -> list[int]:
        return [j for j in range(self.T) if a <= self.delta(i, j) <= b]

    def rho(self, n, t: int) -> float:
        key = (id(n), t)
        if key not in self.memo:
            self.memo[key] = self._rho(n, t)
        return self.memo[key]

    def _rho(self, n, t: int) -> float:
        T = self.T
        if isinstance(n, Atom):
            args = tuple(self.binding.get(a, a) for a in n.args)
            return float(self.tr.signal(n.pred, args)[t]) - THRESHOLD
        if isinstance(n, Not):
            return -self.rho(n.arg, t)
        if isinstance(n, And):
            return min(self.rho(c, t) for c in n.args)
        if isinstance(n, Or):
            return max(self.rho(c, t) for c in n.args)
        if isinstance(n, Eventually):
            vals = [self.rho(n.arg, j) for j in self.window(t, n.a, n.b)]
            return max(vals) if vals else -C
        if isinstance(n, Always):
            vals = [self.rho(n.arg, j) for j in self.window(t, n.a, n.b)]
            return min(vals) if vals else -C
        if isinstance(n, Then):
            best = -C
            for t1 in range(t, T):
                w = [self.rho(n.right, t2) for t2 in self.window(t1, n.a, n.b)]
                best = max(best, min(self.rho(n.left, t1), max(w) if w else -C))
            return best
        if isinstance(n, HoldsFor):
            best = -C
            for t1 in range(t, T):
                if self.delta(t1, T - 1) < n.d:               # t1 + d <= t_end
                    continue
                w = [self.rho(n.arg, t2) for t2 in self.window(t1, 0.0, n.d)]
                if w:
                    best = max(best, min(w))
            return best
        raise TypeError(n)


def ref_series(phi, trace: Trace, binding: dict[str, str]) -> list[float]:
    r = Ref(trace, binding)
    return [r.rho(phi, t) for t in range(r.T)]


def ref_score(rule: Rule, trace: Trace) -> float:
    if trace.status != "ok" or not trace.frames:
        return -C
    names = [v.name for v in rule.vars]
    best = -C
    ctx_ok = True
    from exemplar.dsl.evaluator import ctx_holds        # context atoms are trivial lookups; shared on purpose
    for c in rule.when:
        ctx_ok &= ctx_holds(c, trace.context)
    for b in trace.bindings(tuple(v.type for v in rule.vars)):
        r = Ref(trace, dict(zip(names, b)))
        for t in range(r.T):
            best = max(best, min(r.rho(rule.body, t), C if ctx_ok else -C))
    return best
