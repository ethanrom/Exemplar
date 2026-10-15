"""Quantitative (robustness) evaluator; semantics in docs/DSL.md.

Vectorised with NumPy over (bindings x frames) arrays. Window offsets are computed once per trace as
``D[i, j] = (t_ms[j] - t_ms[i]) / 1000`` (integer ms, a single correctly-rounded division) and compared
with the bounds, never as differences of float seconds.

Public entry points: `prepare`, `rho`, `robustness`, `evaluate`, `compile_rule` / `CompiledRule`.
Evaluators require *closed*, well-typed rules (`typecheck` first if the rule came from an LLM).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Mapping, Optional, Union

import numpy as np
from pydantic import BaseModel

from ..contracts.dsl_ast import (Always, And, Atom, DeviceEq, Eventually, HoldsFor, Hole, HourIn, Not, Or, Rule,
                                 SubtypeEq, Then, holes as ast_holes)
from ..contracts.ontology import ABSENT_VALUE, CLAMP, CONF_VALUE, THRESHOLD
from ..contracts.trace import Trace, TraceContext
from .errors import UnboundHoleError
from .util import bound_value

C = CLAMP
_NEG = -np.inf
_POS = np.inf

HoleValues = Mapping[str, float]


# =========================================================================== prepared traces
class _Env:
    """Variable -> entity assignments for one batch of bindings."""
    __slots__ = ("eid", "names", "idx", "bindings")

    def __init__(self, eid: int, names: tuple[str, ...], bindings: list[tuple[str, ...]]) -> None:
        self.eid = eid
        self.names = names
        self.idx = {n: i for i, n in enumerate(names)}
        self.bindings = bindings


class PreparedTrace:
    """A `Trace` plus the arrays every evaluation needs: the pairwise offset matrix, a one-pass signal
    index, and caches for window masks, bindings and atom matrices. Build once per trace (`prepare`) and
    reuse it across many rule / hole evaluations; the instance is read-only apart from its caches.
    """

    def __init__(self, trace: Trace) -> None:
        self.trace = trace
        frames = trace.frames
        T = len(frames)
        self.T = T
        self.ok = trace.status == "ok" and T > 0
        self.t_ms = np.fromiter((f.t_ms for f in frames), dtype=np.int64, count=T)
        # D[i, j] = (t_j - t_i) / 1000 : one division of exact integers (docs/DSL.md "Time is integer ms").
        self.D = (self.t_ms[None, :] - self.t_ms[:, None]) / 1000
        # to_end[i] = (t_end - t_i) / 1000 with t_end the last frame's time.
        self.to_end = self.D[:, T - 1].copy() if T else np.zeros(0)
        self._absent = np.full(T, ABSENT_VALUE)
        self._absent.flags.writeable = False
        self._sig: Optional[dict] = None
        self._masks: dict = {}
        self._bindings: dict = {}
        self._envs: dict = {}
        self._atoms: dict = {}

    # ------------------------------------------------------------------ signals
    def _build_signals(self) -> dict:
        """One pass over all facts; must agree exactly with `Trace.signal` (tested)."""
        n, tr = self.T, self.trace
        idx: dict[tuple, np.ndarray] = {}

        def put(key: tuple, i: int, v: float) -> None:
            arr = idx.get(key)
            if arr is None:
                arr = idx[key] = np.full(n, ABSENT_VALUE)
            if v > arr[i]:
                arr[i] = v

        for i, fr in enumerate(tr.frames):
            for f in fr.facts:
                v = CONF_VALUE[f.conf]
                put((f.pred, f.args), i, v)
                for a in f.args:                      # presence of an entity is implied by any fact on it
                    put(("present", (a,)), i, v)
        floor = CONF_VALUE["med"]
        for e in tr.entities:                          # clip-level attrs hold in every frame
            for label in e.attrs:
                key = ("attr", (e.id, label))
                arr = idx.get(key)
                if arr is None:
                    idx[key] = np.full(n, floor)
                else:
                    np.maximum(arr, floor, out=arr)
        for arr in idx.values():
            arr.flags.writeable = False
        return idx

    def signal(self, pred: str, args: tuple[str, ...]) -> np.ndarray:
        """Same values as `Trace.signal(pred, args)`; the returned array is shared and read-only."""
        if self._sig is None:
            self._sig = self._build_signals()
        return self._sig.get((pred, args), self._absent)

    # ------------------------------------------------------------------ windows, bindings
    def window(self, a: float, b: float) -> tuple[np.ndarray, np.ndarray]:
        """(mask, nonempty): mask[i, j] = a <= (t_j - t_i)/1000 <= b; nonempty[i] = mask[i].any()."""
        key = (a, b)
        m = self._masks.get(key)
        if m is None:
            M = (self.D >= a) & (self.D <= b)
            m = (M, M.any(axis=1))
            if len(self._masks) > 4096:
                self._masks.clear()
            self._masks[key] = m
        return m

    def bindings(self, var_types: tuple[str, ...]) -> list[tuple[str, ...]]:
        b = self._bindings.get(var_types)
        if b is None:
            b = self._bindings[var_types] = self.trace.bindings(var_types)
        return b

    def env(self, key: tuple, names: tuple[str, ...], bindings: list[tuple[str, ...]]) -> _Env:
        e = self._envs.get(key)
        if e is None:
            e = self._envs[key] = _Env(len(self._envs), names, bindings)
        return e

    def atom_rho(self, env: _Env, pred: str, args: tuple[str, ...]) -> np.ndarray:
        """(B, T) array of s(t) - 0.5 for the atom under each binding of ``env``."""
        key = (env.eid, pred, args)
        m = self._atoms.get(key)
        if m is None:
            idx = env.idx
            slots = [idx.get(a) for a in args]
            rows = []
            for b in env.bindings:
                rows.append(self.signal(pred, tuple(a if s is None else b[s] for a, s in zip(args, slots))))
            m = np.stack(rows) - THRESHOLD
            if len(self._atoms) > 8192:
                self._atoms.clear()
            self._atoms[key] = m
        return m


_CACHE_MAX = 256
_cache: "OrderedDict[int, PreparedTrace]" = OrderedDict()
_lock = threading.Lock()


def prepare(trace: Union[Trace, PreparedTrace]) -> PreparedTrace:
    """Return the `PreparedTrace` for ``trace`` (cached by object identity, LRU of 256)."""
    if isinstance(trace, PreparedTrace):
        return trace
    k = id(trace)
    with _lock:
        p = _cache.get(k)
        if p is not None and p.trace is trace:
            _cache.move_to_end(k)
            return p
    p = PreparedTrace(trace)
    with _lock:
        _cache[k] = p
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return p


# =========================================================================== lowering (AST -> small IR)
class _N:
    """IR node. ``a``/``b`` are floats or (for holes) the hole name; holds_for keeps its d in ``a``."""
    __slots__ = ("op", "pred", "args", "a", "b", "kids", "node")

    def __init__(self, op, node, pred=None, args=(), a=None, b=None, kids=()):
        self.op, self.node, self.pred, self.args, self.a, self.b, self.kids = op, node, pred, args, a, b, kids


def _bnd(x):
    return x.name if isinstance(x, Hole) else float(x)


def _lower(node) -> _N:
    if isinstance(node, Atom):
        return _N("atom", node, pred=node.pred, args=node.args)
    if isinstance(node, Not):
        return _N("not", node, kids=(_lower(node.arg),))
    if isinstance(node, And):
        return _N("and", node, kids=tuple(_lower(c) for c in node.args))
    if isinstance(node, Or):
        return _N("or", node, kids=tuple(_lower(c) for c in node.args))
    if isinstance(node, Eventually):
        return _N("eventually", node, a=_bnd(node.a), b=_bnd(node.b), kids=(_lower(node.arg),))
    if isinstance(node, Always):
        return _N("always", node, a=_bnd(node.a), b=_bnd(node.b), kids=(_lower(node.arg),))
    if isinstance(node, Then):
        return _N("then", node, a=_bnd(node.a), b=_bnd(node.b), kids=(_lower(node.left), _lower(node.right)))
    if isinstance(node, HoldsFor):
        return _N("holds_for", node, a=_bnd(node.d), kids=(_lower(node.arg),))
    raise TypeError(f"not a formula: {node!r}")


def _val(x, holes: Optional[HoleValues]) -> float:
    if isinstance(x, str):
        if holes is None or x not in holes:
            raise UnboundHoleError([x])
        return float(holes[x])
    return x


# =========================================================================== core evaluation
class _Ev:
    __slots__ = ("prep", "env", "holes", "memo", "extra")

    def __init__(self, prep: PreparedTrace, env: _Env, holes: Optional[HoleValues], record: bool = False) -> None:
        self.prep, self.env, self.holes = prep, env, holes
        self.memo: Optional[dict] = {} if record else None     # id(_N) -> (B, T) array (witness extraction)
        self.extra: Optional[dict] = {} if record else None    # id(_N) -> inner array for then / holds_for


def _rev_cummax(x: np.ndarray) -> np.ndarray:
    """max over t1 >= t, for every t (along the last axis)."""
    return np.maximum.accumulate(x[:, ::-1], axis=1)[:, ::-1]


def _eval(n: _N, ev: _Ev) -> np.ndarray:
    """rho of ``n`` at every frame, for every binding of ``ev.env``: shape (B, T)."""
    op = n.op
    prep = ev.prep
    if op == "atom":
        r = prep.atom_rho(ev.env, n.pred, n.args)
    elif op == "not":
        r = -_eval(n.kids[0], ev)
    elif op == "and":
        r = _eval(n.kids[0], ev)
        for k in n.kids[1:]:
            r = np.minimum(r, _eval(k, ev))
    elif op == "or":
        r = _eval(n.kids[0], ev)
        for k in n.kids[1:]:
            r = np.maximum(r, _eval(k, ev))
    elif op == "eventually" or op == "always":
        x = _eval(n.kids[0], ev)
        M, has = prep.window(_val(n.a, ev.holes), _val(n.b, ev.holes))
        xb = x[:, None, :]
        if op == "eventually":
            r = np.where(M, xb, _NEG).max(axis=2)
        else:
            r = np.where(M, xb, _POS).min(axis=2)
        r = np.where(has, r, -C)                        # empty window -> -C (both operators, by design)
    elif op == "then":
        x = _eval(n.kids[0], ev)
        y = _eval(n.kids[1], ev)
        M, has = prep.window(_val(n.a, ev.holes), _val(n.b, ev.holes))
        ymax = np.where(has, np.where(M, y[:, None, :], _NEG).max(axis=2), -C)
        inner = np.minimum(x, ymax)
        if ev.extra is not None:
            ev.extra[id(n)] = inner
        r = _rev_cummax(inner)
    elif op == "holds_for":
        x = _eval(n.kids[0], ev)
        d = _val(n.a, ev.holes)
        M, has = prep.window(0.0, d)
        xmin = np.where(M, x[:, None, :], _POS).min(axis=2)
        valid = (prep.to_end >= d) & has                # t1 + d <= t_end  (one-division offsets)
        inner = np.where(valid, xmin, -C)
        if ev.extra is not None:
            ev.extra[id(n)] = inner
        r = _rev_cummax(inner)
    else:  # pragma: no cover
        raise ValueError(op)
    if ev.memo is not None:
        ev.memo[id(n)] = r
    return r


# =========================================================================== context atoms (crisp)
def ctx_holds(c, context: TraceContext, values: Optional[HoleValues] = None) -> bool:
    """Truth of one context atom. Missing context (None) makes the atom false."""
    if isinstance(c, HourIn):
        h = context.local_hour
        if h is None:
            return False
        h1, h2 = bound_value(c.h1, values, hour=True), bound_value(c.h2, values, hour=True)
        return (h1 <= h <= h2) if h1 <= h2 else (h >= h1 or h <= h2)       # h1 > h2 wraps past midnight
    if isinstance(c, SubtypeEq):
        return context.sub_type == c.value
    if isinstance(c, DeviceEq):
        return context.device_id == c.value
    raise TypeError(f"not a context atom: {c!r}")


def ctx_value(ctxs, context: TraceContext, values: Optional[HoleValues] = None) -> float:
    """Context atoms are crisp +-C and combine with min (and): +C if all hold or there are none, else -C."""
    for c in ctxs:
        if not ctx_holds(c, context, values):
            return -C
    return C


# =========================================================================== rules
class CompiledRule:
    """A rule lowered once for repeated evaluation (e.g. a sketch with holes at many hole points).

        cr = compile_rule(sketch)
        for point in points:
            cr.score(trace, point)            # no pydantic copies, no re-lowering
    """

    def __init__(self, rule: Rule) -> None:
        self.rule = rule
        self.names = tuple(v.name for v in rule.vars)
        self.types = tuple(v.type for v in rule.vars)
        self.ir = _lower(rule.body)
        self.when = tuple(rule.when)
        self.holes = tuple(ast_holes(rule))

    def _check(self, holes: Optional[HoleValues]) -> None:
        missing = [h for h in self.holes if holes is None or h not in holes]
        if missing:
            raise UnboundHoleError(missing)

    def score(self, trace: Union[Trace, PreparedTrace], holes: Optional[HoleValues] = None) -> float:
        """robustness of the rule on the trace, with ``holes`` substituted (hours round to int)."""
        self._check(holes)
        prep = prepare(trace)
        if not prep.ok:
            return -C
        bindings = prep.bindings(self.types)
        if not bindings:
            return -C
        if ctx_value(self.when, prep.trace.context, holes) < 0:
            return -C
        env = prep.env(("T", self.names, self.types), self.names, bindings)
        body = _eval(self.ir, _Ev(prep, env, holes))
        return min(float(body.max()), C)

    def scores(self, traces, holes: Optional[HoleValues] = None) -> np.ndarray:
        return np.array([self.score(t, holes) for t in traces], dtype=np.float64)


def compile_rule(rule: Rule) -> CompiledRule:
    return CompiledRule(rule)


def robustness(rule: Rule, trace: Union[Trace, PreparedTrace], holes: Optional[HoleValues] = None) -> float:
    """score(rule, clip) = max over type-correct bindings of max over t of rho(body AND context).

    No bindings, an empty / failed trace, or a false context atom gives -C (= -0.5). The result lies in
    [-C, C]; the rule matches when it is > 0. A closed rule is required: pass ``holes`` to fill any
    holes (same as ``fill_holes`` first), otherwise `UnboundHoleError` is raised.
    """
    return CompiledRule(rule).score(trace, holes)


def evaluate(rule: Rule, trace: Union[Trace, PreparedTrace], holes: Optional[HoleValues] = None) -> float:
    """Robustness of ``fill_holes(rule, holes)`` on ``trace`` (the hole-point helper D calls)."""
    return robustness(rule, trace, holes)


def rho(phi: BaseModel, trace: Union[Trace, PreparedTrace], binding: Mapping[str, str],
        holes: Optional[HoleValues] = None) -> np.ndarray:
    """rho(phi, t) at every frame t for one binding (variable name -> entity id); shape (T,), float64.

    Arguments of atoms that are not keys of ``binding`` are literals (zones, labels).
    """
    left = [h for h in ast_holes(phi) if holes is None or h not in holes]
    if left:
        raise UnboundHoleError(left)
    prep = prepare(trace)
    if prep.T == 0:
        return np.zeros(0)
    names = tuple(binding)
    vals = tuple(binding[n] for n in names)
    env = prep.env(("B", names, vals), names, [vals])
    return _eval(_lower(phi), _Ev(prep, env, holes))[0].copy()
