"""Z3 encoding of the DSL semantics (PLAN.md section 2.3, docs/DSL.md).

For a *sketch* (a rule whose only free symbols are holes), labelled examples and a *margin level* ``m``, `Encoder`
builds, per example,

    GE = "score(rule, clip) >= m"        (the margin-m version of "the rule matches")
    LE = "score(rule, clip) <= -m"       (the margin-m version of "the rule does not match")

as Z3 formulas over the hole variables.  They are built by the recursion

    GE(phi, t, binding)  /  LE(phi, t, binding)   memoised on (node, relevant bindings), vectorised over t

so Z3 receives a DAG.  Every atom's robustness is a constant ``s(t) - 0.5`` read from the evaluator's own signal
index, and every robustness value is one of a few constants (min / max / negation only select among them).  The
margin is therefore not a Z3 variable but a constant *level* from `margin_levels()`: atoms fold to Python booleans,
the formulas only contain window comparisons on the holes, and `solve_sketch` maximises the margin by walking the
levels.  (This is the PLAN.md section 2.3 encoding with ``m`` specialised; it is much smaller than carrying ``m``
symbolically because ``rho(atom) <= -m`` is no longer a live constraint for every absent atom.)

Conventions that must match `exemplar.dsl.evaluator` exactly (and are property-tested against it):

* integer-ms time: window membership is ``a <= (t_j - t_i)/1000 <= b``.  Constant bounds are compared with the same
  float expression the evaluator uses (and its own window masks); hole bounds are compared as exact rationals;
* an empty ``eventually`` / ``always`` window has robustness ``-C`` (so ``m <= C`` is a hard bound on levels);
* ``then`` / ``holds_for`` search every start ``t1 >= t``; ``holds_for`` needs ``t1 + d <= t_end`` (last frame);
* context atoms are crisp ``+-C`` and missing context is false; ``exists`` is OR over type-correct bindings for GE
  and AND for LE; no bindings / no frames / failed perception give ``-C``.
"""
from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from typing import Optional, Sequence, Union

import z3

from ..contracts.dsl_ast import (Always, And, Atom, DeviceEq, Eventually, HoldsFor, Hole, HourIn, Not, Or, Rule,
                                 SubtypeEq, Then, children, holes as ast_holes)
from ..contracts.ontology import ABSENT_VALUE, CLAMP, CONF_VALUE, THRESHOLD
from ..dsl import prepare, typecheck, to_text
from ..dsl.evaluator import PreparedTrace, ctx_holds
from .types import Example, SketchError

Bx = Union[bool, z3.BoolRef]

C_FR = Fraction(CLAMP).limit_denominator(10**6)
THRESHOLD_FR = Fraction(THRESHOLD).limit_denominator(10**6)


@lru_cache(maxsize=4096)
def _rat(x: float) -> Fraction:
    """Exact rational of a float that is "a decimal with few digits" (0.6 -> 3/5)."""
    return Fraction(x).limit_denominator(10**9)


@lru_cache(maxsize=4096)
def _rho_const(s: float) -> Fraction:
    return _rat(s) - THRESHOLD_FR


# ============================================================================ boolean helpers (Python-folded)
class Bld:
    """Boolean connectives over Python bools and Z3 terms.  Constants are folded away, duplicates dropped, and the
    Z3 AST is built through the C API directly (z3py's coercing `And`/`Or` cost ~1 ms per call, which dominated
    encoding time)."""

    def __init__(self, ctx: z3.Context) -> None:
        self.ctx = ctx
        self.cref = ctx.ref()
        self._neg: dict[int, z3.BoolRef] = {}

    def _mk(self, f, xs: list) -> z3.BoolRef:
        n = len(xs)
        arr = (z3.Ast * n)(*[x.as_ast() for x in xs])
        return z3.BoolRef(f(self.cref, n, arr), self.ctx)

    def not_(self, x: Bx) -> Bx:
        if x is True:
            return False
        if x is False:
            return True
        i = x.ast.value
        r = self._neg.get(i)
        if r is None:
            r = z3.BoolRef(z3.Z3_mk_not(self.cref, x.as_ast()), self.ctx)
            self._neg[i] = r
            self._neg[r.ast.value] = x
        return r

    def and_(self, xs) -> Bx:
        out, seen = [], set()
        for x in xs:
            if x is True:
                continue
            if x is False:
                return False
            i = x.ast.value
            if i not in seen:
                seen.add(i)
                out.append(x)
        if not out:
            return True
        return out[0] if len(out) == 1 else self._mk(z3.Z3_mk_and, out)

    def or_(self, xs) -> Bx:
        out, seen = [], set()
        for x in xs:
            if x is False:
                continue
            if x is True:
                return True
            i = x.ast.value
            if i not in seen:
                seen.add(i)
                out.append(x)
        if not out:
            return False
        return out[0] if len(out) == 1 else self._mk(z3.Z3_mk_or, out)

    def implies(self, a: Bx, b: Bx) -> Bx:
        return self.or_([self.not_(a), b])


# ============================================================================ IR (hash-consed formula DAG)
class Ir:
    __slots__ = ("id", "op", "pred", "args", "a", "b", "kids", "free")

    def __init__(self, id, op, pred, args, a, b, kids, free):
        self.id, self.op, self.pred, self.args, self.a, self.b, self.kids, self.free = id, op, pred, args, a, b, kids, free


def _bnd(x) -> Union[float, str]:
    return x.name if isinstance(x, Hole) else float(x)


class _Lowering:
    def __init__(self, var_names: Sequence[str]) -> None:
        self.var_names = set(var_names)
        self.table: dict[tuple, Ir] = {}

    def mk(self, op, pred=None, args=(), a=None, b=None, kids=()) -> Ir:
        key = (op, pred, args, a, b, tuple(k.id for k in kids))
        n = self.table.get(key)
        if n is None:
            free = set(x for x in args if x in self.var_names)
            for k in kids:
                free.update(k.free)
            n = self.table[key] = Ir(len(self.table), op, pred, args, a, b, kids, tuple(sorted(free)))
        return n

    def lower(self, node) -> Ir:
        if isinstance(node, Atom):
            return self.mk("atom", pred=node.pred, args=tuple(node.args))
        if isinstance(node, Not):
            return self.mk("not", kids=(self.lower(node.arg),))
        if isinstance(node, And):
            return self.mk("and", kids=tuple(self.lower(c) for c in node.args))
        if isinstance(node, Or):
            return self.mk("or", kids=tuple(self.lower(c) for c in node.args))
        if isinstance(node, (Eventually, Always)):
            return self.mk(node.op, a=_bnd(node.a), b=_bnd(node.b), kids=(self.lower(node.arg),))
        if isinstance(node, Then):
            return self.mk("then", a=_bnd(node.a), b=_bnd(node.b), kids=(self.lower(node.left), self.lower(node.right)))
        if isinstance(node, HoldsFor):
            return self.mk("holds_for", a=_bnd(node.d), kids=(self.lower(node.arg),))
        raise SketchError(f"not a formula: {node!r}")


def hole_kinds(sketch: Rule) -> dict[str, str]:
    """name -> "time" (window bound / duration, seconds) or "hour" (0-23); a name used as both is an error."""
    kinds: dict[str, str] = {}

    def put(x, kind: str) -> None:
        if isinstance(x, Hole):
            if kinds.setdefault(x.name, kind) != kind:
                raise SketchError(f"hole ?{x.name} is used both as an hour and as a time; use two names")

    def walk(n) -> None:
        if isinstance(n, (Eventually, Always, Then)):
            put(n.a, "time")
            put(n.b, "time")
        elif isinstance(n, HoldsFor):
            put(n.d, "time")
        elif isinstance(n, HourIn):
            put(n.h1, "hour")
            put(n.h2, "hour")
        for c in children(n):
            walk(c)

    walk(sketch)
    return kinds


def lower_bound_holes(sketch: Rule) -> set[str]:
    """Holes that are the lower bound ``a`` of some eventually / always / then window."""
    out: set[str] = set()

    def walk(n) -> None:
        if isinstance(n, (Eventually, Always, Then)) and isinstance(n.a, Hole):
            out.add(n.a.name)
        for c in children(n):
            walk(c)

    walk(sketch)
    return out


def _windows(sketch: Rule) -> list[tuple]:
    out: list[tuple] = []

    def walk(n) -> None:
        if isinstance(n, (Eventually, Always, Then)) and (isinstance(n.a, Hole) or isinstance(n.b, Hole)):
            out.append((n.a, n.b))
        for c in children(n):
            walk(c)

    walk(sketch)
    return out


# ============================================================================ margin levels
def margin_levels() -> list[Fraction]:
    """The margins that can be optimal, ascending.

    Every robustness value is built from atom values ``s - 0.5`` (``s`` in the ontology's confidence values and the
    absent value), their negations and ``+-C`` by min / max / negation only, so ``|rho|`` is always one of these
    numbers and a violated/satisfied verdict at margin ``m`` only changes at them.  With the default ontology:
    0.1, 0.3, 0.45, 0.5.
    """
    vals = {abs(_rho_const(v)) for v in list(CONF_VALUE.values()) + [ABSENT_VALUE]}
    vals.add(C_FR)
    return sorted(v for v in vals if v > 0)


# ============================================================================ the encoder
class Encoder:
    """Holds one Z3 context, the hole variables and the per-example formulas of one sketch at one margin level."""

    def __init__(self, sketch: Rule, examples: Sequence[Example], margin: Fraction = Fraction(1, 10)) -> None:
        errs = typecheck(sketch)
        if errs:
            raise SketchError("sketch does not typecheck: " + "; ".join(errs))
        if not 0 <= margin <= C_FR:
            raise ValueError(f"margin must lie in [0, {C_FR}], got {margin}")
        self.sketch = sketch
        self.examples = list(examples)
        self.margin = Fraction(margin)
        self.ctx = z3.Context()
        self.B = Bld(self.ctx)
        self.preps: list[PreparedTrace] = [prepare(e.trace) for e in self.examples]
        self.hole_names: list[str] = ast_holes(sketch)
        self.kinds = hole_kinds(sketch)
        self.lower_holes = lower_bound_holes(sketch)
        self.var_names = tuple(v.name for v in sketch.vars)
        self.var_types = tuple(v.type for v in sketch.vars)
        self.ir = _Lowering(self.var_names).lower(sketch.body)
        ends = [max(p.trace.duration_ms, int(p.t_ms[-1]) if p.T else 0) for p in self.preps]
        self.clip_len_ms: int = max(ends) if ends and max(ends) > 0 else 1000
        self.clip_len: float = self.clip_len_ms / 1000

        c = self.ctx
        self.hv: dict[str, z3.ArithRef] = {}
        for h in self.hole_names:
            self.hv[h] = z3.Int(f"h_{h}", c) if self.kinds[h] == "hour" else z3.Real(f"h_{h}", c)
        self._rv: dict[Fraction, z3.ArithRef] = {}
        self._wa: dict[tuple, Bx] = {}
        self._cell: dict[tuple, Bx] = {}
        self._nonempty: dict[tuple, Bx] = {}
        self.domain: list[z3.BoolRef] = self._domain()
        self._formulas: dict[int, tuple[Bx, Bx]] = {}
        self._ex: dict[int, "_ExampleEncoder"] = {}

    # ------------------------------------------------------------------ constants / atoms
    def rv(self, x: Fraction) -> z3.ArithRef:
        r = self._rv.get(x)
        if r is None:
            r = self._rv[x] = z3.RealVal(f"{x.numerator}/{x.denominator}", self.ctx)
        return r

    def ge_const(self, c: Fraction) -> bool:
        """A constant robustness ``c`` satisfies ``rho >= m``."""
        return c >= self.margin

    def le_const(self, c: Fraction) -> bool:
        """A constant robustness ``c`` satisfies ``rho <= -m``."""
        return c <= -self.margin

    def _domain(self) -> list[z3.BoolRef]:
        d: list[z3.BoolRef] = []
        L = self.rv(Fraction(self.clip_len_ms, 1000))
        for h, v in self.hv.items():
            if self.kinds[h] == "hour":
                d += [v >= 0, v <= 23]
            else:
                d += [v >= 0, v <= L]
        for a, b in _windows(self.sketch):
            lo = self.hv[a.name] if isinstance(a, Hole) else self.rv(_rat(float(a)))
            hi = self.hv[b.name] if isinstance(b, Hole) else self.rv(_rat(float(b)))
            d.append(lo <= hi)
        return d

    # ------------------------------------------------------------------ window atoms
    def lower_ok(self, a: Union[float, str], diff_ms: int) -> Bx:
        """``a <= (diff_ms)/1000``."""
        if isinstance(a, str):
            if diff_ms < 0:
                return False
            key = ("lo", a, diff_ms)
            x = self._wa.get(key)
            if x is None:
                x = self._wa[key] = self.hv[a] <= self.rv(Fraction(diff_ms, 1000))
            return x
        return bool(a <= diff_ms / 1000)

    def upper_ok(self, b: Union[float, str], diff_ms: int) -> Bx:
        """``(diff_ms)/1000 <= b``."""
        if isinstance(b, str):
            if diff_ms <= 0:
                return True
            key = ("hi", b, diff_ms)
            x = self._wa.get(key)
            if x is None:
                x = self._wa[key] = self.hv[b] >= self.rv(Fraction(diff_ms, 1000))
            return x
        return bool(diff_ms / 1000 <= b)

    # ------------------------------------------------------------------ per-example formulas
    def example_encoder(self, k: int) -> "_ExampleEncoder":
        e = self._ex.get(k)
        if e is None:
            e = self._ex[k] = _ExampleEncoder(self, self.preps[k])
        return e

    def formulas(self, k: int) -> tuple[Bx, Bx]:
        """(GE, LE) of example ``k``: ``score >= m`` and ``score <= -m``."""
        f = self._formulas.get(k)
        if f is None:
            f = self._formulas[k] = self.example_encoder(k).top()
        return f

    def goal(self, k: int) -> Bx:
        """The constraint example ``k`` must satisfy: GE for a positive, LE for a negative."""
        ge, le = self.formulas(k)
        return ge if self.examples[k].positive else le

    # ------------------------------------------------------------------ model read-back / test hooks
    def read_holes(self, model: z3.ModelRef) -> dict[str, float]:
        out: dict[str, float] = {}
        for h, v in self.hv.items():
            val = model.eval(v, model_completion=True)
            out[h] = float(val.as_long()) if self.kinds[h] == "hour" else float(val.as_fraction())
        return out

    def hole_value_expr(self, h: str, x: float):
        """The Z3 constant for a float hole value.  A float is read as its shortest decimal, which is the rational
        the evaluator's float comparisons against multiples of 1/1000 are consistent with."""
        return int(round(x)) if self.kinds[h] == "hour" else self.rv(Fraction(repr(float(x))))

    def bind_holes(self, values: dict[str, float]) -> list[z3.BoolRef]:
        """Equalities fixing every hole to ``values``."""
        return [v == self.hole_value_expr(h, values[h]) for h, v in self.hv.items()]

    def context_expr(self, ctxs, context) -> Bx:
        out: list[Bx] = []
        for c in ctxs:
            if isinstance(c, HourIn) and (isinstance(c.h1, Hole) or isinstance(c.h2, Hole)):
                out.append(self._hour_expr(c, context.local_hour))
            else:
                out.append(bool(ctx_holds(c, context)))
        return self.B.and_(out)

    def _hour_expr(self, c: HourIn, hour: Optional[int]) -> Bx:
        if hour is None:
            return False
        h1 = self.hv[c.h1.name] if isinstance(c.h1, Hole) else z3.IntVal(c.h1, self.ctx)
        h2 = self.hv[c.h2.name] if isinstance(c.h2, Hole) else z3.IntVal(c.h2, self.ctx)
        return z3.Or(z3.And(h1 <= h2, h1 <= hour, hour <= h2), z3.And(h1 > h2, z3.Or(hour >= h1, hour <= h2)))


class _LazyRow:
    """Row ``i`` of a window matrix whose entries (Z3 terms over the hole variables) are built on first use."""
    __slots__ = ("enc", "dms", "a", "b", "cache")

    def __init__(self, enc: Encoder, dms: list[int], a, b) -> None:
        self.enc, self.dms, self.a, self.b, self.cache = enc, dms, a, b, {}

    def __getitem__(self, j: int) -> Bx:
        x = self.cache.get(j)
        if x is None:
            d = self.dms[j]
            key = (self.a, self.b, d)
            enc = self.enc
            x = enc._cell.get(key)
            if x is None:
                x = enc._cell[key] = enc.B.and_([enc.lower_ok(self.a, d), enc.upper_ok(self.b, d)])
            self.cache[j] = x
        return x


class _ExampleEncoder:
    """GE / LE of one example: the recursion over the formula, memoised on (node, relevant bindings)."""

    def __init__(self, enc: Encoder, prep: PreparedTrace) -> None:
        self.enc = enc
        self.prep = prep
        self.T = prep.T
        self.B = enc.B
        self.memo: dict[tuple, tuple[list, list]] = {}
        self._win: dict[tuple, list] = {}
        self._ne: dict[tuple, list[Bx]] = {}
        t = prep.t_ms
        self._dms = [[int(t[j] - t[i]) for j in range(prep.T)] for i in range(prep.T)]

    # ------------------------------------------------------------------ windows
    def window(self, a, b) -> list:
        """W[i][j] = ``a <= (t_j - t_i)/1000 <= b`` (constant windows come from the evaluator's own mask)."""
        key = (a, b)
        W = self._win.get(key)
        if W is None:
            if not isinstance(a, str) and not isinstance(b, str):
                W = self.prep.window(a, b)[0].tolist()
            else:
                W = [_LazyRow(self.enc, self._dms[i], a, b) for i in range(self.T)]
            self._win[key] = W
        return W

    def nonempty(self, a, b) -> list[Bx]:
        key = (a, b)
        ne = self._ne.get(key)
        if ne is None:
            W, B, T, enc = self.window(a, b), self.B, self.T, self.enc
            ne = []
            for i in range(T):
                if W[i][i] is True:                                  # t_i itself is in the window
                    ne.append(True)
                    continue
                rk = (a, b, tuple(self._dms[i])) if (isinstance(a, str) or isinstance(b, str)) else None
                x = enc._nonempty.get(rk) if rk is not None else None
                if x is None:
                    x = B.or_([W[i][j] for j in range(T)])
                    if rk is not None:
                        enc._nonempty[rk] = x
                ne.append(x)
            self._ne[key] = ne
        return ne

    # ------------------------------------------------------------------ the recursion
    def vec(self, n: Ir, bind: dict[str, str]) -> tuple[list, list]:
        key = (n.id, tuple(bind[v] for v in n.free))
        r = self.memo.get(key)
        if r is None:
            r = self.memo[key] = self._vec(n, bind)
        return r

    def _vec(self, n: Ir, bind: dict[str, str]) -> tuple[list, list]:
        enc, T, op, B = self.enc, self.T, n.op, self.B
        R = range(T)
        if op == "atom":
            sig = self.prep.signal(n.pred, tuple(bind.get(x, x) for x in n.args)).tolist()
            cs = [_rho_const(s) for s in sig]
            return [enc.ge_const(c) for c in cs], [enc.le_const(c) for c in cs]
        if op == "not":
            ge, le = self.vec(n.kids[0], bind)
            return le, ge
        if op == "and" or op == "or":
            vs = [self.vec(k, bind) for k in n.kids]
            if op == "and":
                return ([B.and_([v[0][i] for v in vs]) for i in R], [B.or_([v[1][i] for v in vs]) for i in R])
            return ([B.or_([v[0][i] for v in vs]) for i in R], [B.and_([v[1][i] for v in vs]) for i in R])
        if op == "eventually" or op == "always":
            gc, lc = self.vec(n.kids[0], bind)
            W = self.window(n.a, n.b)
            gj = [j for j in R if gc[j] is not False]          # frames that can witness GE
            lj = [j for j in R if lc[j] is not True]           # frames that can break LE
            if op == "eventually":
                ge = [B.or_([B.and_([W[i][j], gc[j]]) for j in gj]) for i in R]
                le = [B.and_([B.implies(W[i][j], lc[j]) for j in lj]) for i in R]
            else:
                ne = self.nonempty(n.a, n.b)
                gt = [j for j in R if gc[j] is not True]
                lf = [j for j in R if lc[j] is not False]
                ge = [B.and_([ne[i]] + [B.implies(W[i][j], gc[j]) for j in gt]) for i in R]
                le = [B.or_([B.not_(ne[i])] + [B.and_([W[i][j], lc[j]]) for j in lf]) for i in R]
            return ge, le
        if op == "then":
            gx, lx = self.vec(n.kids[0], bind)
            gy, ly = self.vec(n.kids[1], bind)
            W = self.window(n.a, n.b)
            gj = [j for j in R if gy[j] is not False]
            lj = [j for j in R if ly[j] is not True]
            gi = [B.and_([gx[i], B.or_([B.and_([W[i][j], gy[j]]) for j in gj])]) if gx[i] is not False else False
                  for i in R]
            li = [True if lx[i] is True else B.or_([lx[i], B.and_([B.implies(W[i][j], ly[j]) for j in lj])])
                  for i in R]
            return self._suffix(gi, B.or_), self._suffix(li, B.and_)
        if op == "holds_for":
            gc, lc = self.vec(n.kids[0], bind)
            d = n.a
            W = self.window(0.0, d)
            ne = self.nonempty(0.0, d)
            end_ms = int(self.prep.t_ms[T - 1])
            gt = [j for j in R if gc[j] is not True]
            lf = [j for j in R if lc[j] is not False]
            gi, li = [], []
            for i in R:
                if isinstance(d, str):
                    fits = enc.lower_ok(d, end_ms - int(self.prep.t_ms[i]))        # d <= (t_end - t_i)/1000
                else:
                    fits = bool(self.prep.to_end[i] >= d)
                valid = B.and_([fits, ne[i]])
                gi.append(B.and_([valid] + [B.implies(W[i][j], gc[j]) for j in gt]) if valid is not False else False)
                li.append(B.or_([B.not_(valid)] + [B.and_([W[i][j], lc[j]]) for j in lf]))
            return self._suffix(gi, B.or_), self._suffix(li, B.and_)
        raise SketchError(f"unsupported node {op}")  # pragma: no cover

    def _suffix(self, xs: list, combine) -> list:
        """out[i] = combine over i1 >= i of xs[i1]  (the search over every later start)."""
        out = [None] * self.T
        acc: Bx = combine == self.B.and_
        for i in range(self.T - 1, -1, -1):
            acc = combine([xs[i], acc])
            out[i] = acc
        return out

    # ------------------------------------------------------------------ the rule
    def top(self) -> tuple[Bx, Bx]:
        enc, prep, B = self.enc, self.prep, self.B
        if not prep.ok:
            return False, True                                        # score = -C
        bindings = prep.bindings(enc.var_types)
        if not bindings:
            return False, True
        ok = enc.context_expr(enc.sketch.when, prep.trace.context)
        if ok is False:
            return False, True
        ge_t, le_t = [], []
        for b in bindings:
            ge, le = self.vec(enc.ir, dict(zip(enc.var_names, b)))
            ge_t.append(B.or_(ge))
            le_t.append(B.and_(le))
        return B.and_([ok, B.or_(ge_t)]), B.or_([B.not_(ok), B.and_(le_t)])
