"""Hole solving: MaxSMT + max-margin over the Z3 encoding, temporal-slack placement, differential check.

`solve_sketch` is the entry point the agent and the API use; `hole_box` is what the active-learning committee uses.

Pipeline for one sketch (PLAN.md section 2.3, docs/DSL.md "Hole placement"):

1. `Encoder` builds GE/LE per example; ``z3.Optimize`` minimises the violated weight, then maximises the margin
   ``m`` (lexicographic).  Timeout/unknown -> grid search on a 0.5 s grid scored with the NumPy evaluator.
2. The Z3 model point is differentially checked against `exemplar.dsl` (two-sided, per example).
3. Temporal slack: with the satisfied set and ``m*`` fixed, each hole's feasible interval comes from Z3 min/max
   (`hole_box`); lower window bounds go to 0 when feasible, every other hole to its interval centre; values are
   snapped to the 0.5 s grid (hours: integers) and re-verified with the evaluator; a failing point is pulled back
   along the segment towards the Z3 model point.
4. The returned rule is evaluated once more and any disagreement raises `EncoderMismatch`.
"""
from __future__ import annotations

import itertools
import logging
import math
import time
from fractions import Fraction
from typing import Optional, Sequence

import z3

from ..contracts.dsl_ast import Rule, fill_holes
from ..contracts.ontology import CLAMP
from ..dsl import compile_rule, to_text
from .types import EncoderMismatch, Example, SketchError, SolveResult
from .z3enc import Bx, Encoder, margin_levels

log = logging.getLogger(__name__)
EPS = 1e-6          # tolerance of the mandatory differential check (spec)
GRID_STEP = 0.5     # temporal-slack / fallback grid (seconds)
PLACEMENT_BUDGET_S = 5.0


class InfeasibleBox(ValueError):
    """`hole_box` was asked for a satisfied set / margin no hole assignment achieves."""


# ============================================================================ helpers
def _is_true(model: z3.ModelRef, g: Bx) -> bool:
    if g is True or g is False:
        return g
    return z3.is_true(model.eval(g, model_completion=True))


def _score_all(cr, preps, point: dict[str, float]) -> list[float]:
    return [cr.score(p, point) for p in preps]


def _holds(positive: bool, score: float, m: float, eps: float) -> bool:
    """Margin-m satisfaction in the evaluator's terms."""
    return score >= m - eps if positive else score <= -m + eps


def _label_ok(positive: bool, score: float) -> bool:
    return (score > 0) == positive


def _grid_in(lo: float, hi: float, step: float = GRID_STEP) -> list[float]:
    a, b = math.ceil(lo / step - 1e-12), math.floor(hi / step + 1e-12)
    return [k * step for k in range(a, b + 1)]


# ============================================================================ the exact optimum
def _maxsmt(enc: Encoder, timeout_s: float):
    """MaxSMT at the encoder's margin level: minimise the violated example weight.  Returns (status, model|None)."""
    opt = z3.Optimize(ctx=enc.ctx)
    opt.set("timeout", max(1, int(timeout_s * 1000)))
    opt.add(*enc.domain)
    for k, ex in enumerate(enc.examples):
        g = enc.goal(k)
        if g is True or g is False:
            continue                                    # constant outcome: contributes the same to every model
        opt.add_soft(g, f"{ex.weight:.6g}", "viol")
    res = opt.check()
    if res == z3.sat:
        return "sat", opt.model()
    if res == z3.unsat:
        return "unsat", None
    return "unknown", None


def _violated_weight(enc: Encoder, model: z3.ModelRef) -> float:
    return sum(ex.weight for k, ex in enumerate(enc.examples) if not _is_true(model, enc.goal(k)))


def _diff_check_point(enc: Encoder, cr, holes: dict[str, float], m_star: float, z3_ok: list[bool]) -> list[float]:
    """Two-sided differential check at the Z3 model point: for every example, Z3's verdict "margin m* achieved"
    must equal the evaluator's.  Raises `EncoderMismatch`; returns the evaluator's scores."""
    scores = _score_all(cr, enc.preps, holes)
    for k, ex in enumerate(enc.examples):
        np_ok = _holds(ex.positive, scores[k], m_star, 1e-9)
        if np_ok != z3_ok[k]:
            raise EncoderMismatch(
                f"Z3 and the NumPy evaluator disagree on clip {ex.clip_id!r} ({'positive' if ex.positive else 'negative'}) "
                f"for sketch `{to_text(enc.sketch)}` at holes {holes}, margin {m_star}: Z3 says "
                f"{'satisfied' if z3_ok[k] else 'violated'}, evaluator score is {scores[k]:+.4f}")
    return scores


def _extremum(enc: Encoder, hard: list, h: str, direction: str, timeout_s: float) -> Optional[float]:
    opt = z3.Optimize(ctx=enc.ctx)
    opt.set("timeout", max(1, int(timeout_s * 1000)))
    opt.add(*hard)
    (opt.minimize if direction == "min" else opt.maximize)(enc.hv[h])
    r = opt.check()
    if r != z3.sat:
        return None
    return enc.read_holes(opt.model())[h]


def _box(enc: Encoder, idx: Sequence[int], timeout_s: float) -> dict[str, tuple[float, float]]:
    hard: list = list(enc.domain)
    for k in idx:
        g = enc.goal(k)
        if g is False:
            raise InfeasibleBox(f"example {enc.examples[k].clip_id!r} cannot satisfy the sketch at any hole value")
        if g is not True:
            hard.append(g)
    probe = z3.Solver(ctx=enc.ctx)
    probe.set("timeout", max(1, int(timeout_s * 1000)))
    probe.add(*hard)
    if probe.check() == z3.unsat:
        raise InfeasibleBox("no hole assignment satisfies the given examples at the given margin")
    per = timeout_s / max(1, 2 * len(enc.hole_names))
    out: dict[str, tuple[float, float]] = {}
    for h in enc.hole_names:
        hour = enc.kinds[h] == "hour"
        dom = (0.0, 23.0) if hour else (0.0, enc.clip_len)
        lo = _extremum(enc, hard, h, "min", per)
        hi = _extremum(enc, hard, h, "max", per)
        out[h] = (dom[0] if lo is None else lo, dom[1] if hi is None else hi)
    return out


def hole_box(sketch: Rule, examples: Sequence[Example], *, satisfied: Sequence[str], margin: float,
             timeout_s: float = 10.0) -> dict[str, tuple[float, float]]:
    """Feasible interval ``(lo, hi)`` of every hole: Z3 min/max with the ``satisfied`` examples (clip ids) required to
    hold at ``margin`` and every other example unconstrained (PLAN.md section 2.4, the box the committee samples).

    Pass the same ``examples`` list that was given to `solve_sketch` (the hole domain ``[0, clip_len]`` is derived
    from it).  A query that times out falls back to the hole's full domain for that side.  Raises `InfeasibleBox`
    when the satisfied set is not achievable at that margin.  Every point of the true feasible set lies in the box,
    but not every point of the box is feasible, so callers re-check samples with the evaluator.
    """
    m = min(max(Fraction(float(margin)).limit_denominator(10**6), Fraction(0)), margin_levels()[-1])
    enc = Encoder(sketch, examples, m)
    sat = set(satisfied)
    idx = [k for k, ex in enumerate(enc.examples) if ex.clip_id in sat]
    return _box(enc, idx, timeout_s)


# ============================================================================ temporal-slack placement
def _targets(enc: Encoder, box: dict[str, tuple[float, float]]) -> dict[str, float]:
    """Unsnapped placement targets: lower bounds -> 0 when feasible else centre; everything else -> centre."""
    out = {}
    for h, (lo, hi) in box.items():
        if h in enc.lower_holes and lo <= 0.0 <= hi:
            out[h] = 0.0
        else:
            out[h] = (lo + hi) / 2
    return out


def _snap(enc: Encoder, h: str, x: float, box: dict[str, tuple[float, float]]) -> float:
    """Nearest grid value (0.5 s; hours: integers) inside the hole's interval; the plain value if there is none."""
    lo, hi = box[h]
    if enc.kinds[h] == "hour":
        v = min(max(int(round(x)), int(math.ceil(lo - 1e-9))), int(math.floor(hi + 1e-9)))
        return float(v)
    cands = _grid_in(lo, hi)
    if cands:
        return min(cands, key=lambda g: (abs(g - x), g))
    return float(repr(round(min(max(x, lo), hi), 3)))


def _place(enc: Encoder, cr, p0: dict[str, float], m_star: float, sat_idx: list[int],
           timeout_s: float) -> tuple[dict[str, float], str]:
    """Pick the hole values of the returned rule.  Returns (holes, how)."""
    if not enc.hole_names:
        return {}, "no holes"
    sat_preps = [(enc.preps[k], enc.examples[k].positive) for k in sat_idx]

    def verify(pt: dict[str, float]) -> bool:
        return all(_holds(pos, cr.score(p, pt), m_star, 1e-9) and _label_ok(pos, cr.score(p, pt))
                   for p, pos in sat_preps)

    try:
        box = _box(enc, sat_idx, timeout_s)
    except InfeasibleBox:                                    # numerically odd; keep the Z3 point
        box = {h: (v, v) for h, v in p0.items()}
    target = _targets(enc, box)
    hour = {h: enc.kinds[h] == "hour" for h in enc.hole_names}

    def snapped(pt: dict[str, float]) -> dict[str, float]:
        return {h: _snap(enc, h, x, box) for h, x in pt.items()}

    def rounded(pt: dict[str, float]) -> dict[str, float]:
        return {h: (float(int(round(x))) if hour[h] else float(repr(round(x, 3)))) for h, x in pt.items()}

    cand = snapped(target)
    if verify(cand):
        return cand, "slack-centre"
    for s in (0.75, 0.5, 0.25, 0.125):                       # step back from the target towards the Z3 point
        pt = {h: p0[h] + s * (target[h] - p0[h]) for h in p0}
        for variant, name in ((snapped(pt), "slack-stepback-grid"), (rounded(pt), "slack-stepback")):
            if verify(variant):
                return variant, f"{name}({s})"
    for variant, name in ((snapped(p0), "model-grid"), (rounded(p0), "model-rounded")):
        if verify(variant):
            return variant, name
    return dict(p0), "model"


# ============================================================================ grid fallback
def _grid_search(sketch: Rule, examples: Sequence[Example], enc: Encoder, budget_s: float) -> Optional[dict]:
    """Best point of a 0.5 s grid over the holes, scored with the evaluator.  Not exact; used when Z3 times out.

    Enumerates the full grid when it fits the time budget, otherwise a coarse grid followed by 0.5 s
    coordinate refinement around the best points.  Returns {"holes", "score" key, ...} or None.
    """
    t0 = time.perf_counter()
    cr = compile_rule(sketch)
    names = enc.hole_names
    preps = enc.preps
    L = enc.clip_len
    full = {h: (list(map(float, range(24))) if enc.kinds[h] == "hour" else _grid_in(0.0, L)) for h in names}
    # windows need lo <= hi; evaluated points that violate it are skipped
    from ..contracts.dsl_ast import Hole, Eventually, Always, Then, children

    pairs: list[tuple] = []

    def walk(n) -> None:
        if isinstance(n, (Eventually, Always, Then)):
            pairs.append((n.a, n.b))
        for c in children(n):
            walk(c)

    walk(sketch)

    def ordered(pt: dict[str, float]) -> bool:
        for a, b in pairs:
            lo = pt[a.name] if isinstance(a, Hole) else a
            hi = pt[b.name] if isinstance(b, Hole) else b
            if lo > hi:
                return False
        return True

    best: list = []                                           # (key, pt, scores)

    def key_of(scores: list[float]) -> tuple:
        viol = sum(ex.weight for ex, s in zip(examples, scores) if not _label_ok(ex.positive, s))
        marg = min([abs(s) for ex, s in zip(examples, scores) if _label_ok(ex.positive, s)] or [CLAMP])
        return (viol, -marg)

    def consider(pt: dict[str, float]) -> None:
        if not ordered(pt):
            return
        sc = _score_all(cr, preps, pt)
        best.append((key_of(sc), dict(pt), sc))
        if len(best) > 64:
            best.sort(key=lambda t: t[0])
            del best[16:]

    def time_left() -> bool:
        return time.perf_counter() - t0 < budget_s

    n_full = 1
    for h in names:
        n_full *= len(full[h])
    n_budget = max(200, int(budget_s / max(1e-4, 0.0001 * len(examples) + 1e-4)))
    if n_full <= n_budget:
        for combo in itertools.product(*(full[h] for h in names)):
            if not time_left():
                break
            consider(dict(zip(names, combo)))
    else:
        coarse = {}
        for h in names:
            vals = full[h]
            stride = max(1, len(vals) // max(2, int(round(n_budget ** (1 / max(1, len(names)))))))
            coarse[h] = vals[::stride]
        for combo in itertools.product(*(coarse[h] for h in names)):
            if not time_left():
                break
            consider(dict(zip(names, combo)))
        best.sort(key=lambda t: t[0])
        frontier = [pt for _, pt, _ in best[:4]]
        for _ in range(3):
            for pt in list(frontier):
                for h in names:
                    vals = full[h]
                    if not vals:
                        continue
                    for v in vals:
                        if not time_left():
                            break
                        q = dict(pt)
                        q[h] = v
                        consider(q)
            best.sort(key=lambda t: t[0])
            frontier = [pt for _, pt, _ in best[:4]]
    if not best:
        return None
    best.sort(key=lambda t: t[0])
    k, pt, sc = best[0]
    return {"holes": pt, "scores": sc, "key": k}


# ============================================================================ public: solve_sketch
def _best_level(levels: list[Fraction], lower_bound: float) -> int:
    """Index of the largest margin level that is <= ``lower_bound`` (0 if none)."""
    best = 0
    for i, lv in enumerate(levels):
        if float(lv) <= lower_bound + 1e-9:
            best = i
    return best


def solve_sketch(sketch: Rule, examples: Sequence[Example], *, timeout_s: float = 10.0) -> SolveResult:
    """Fill the holes of ``sketch`` so that it matches the positive examples and none of the negative ones.

    Minimises the violated example weight, then maximises the margin (the least |robustness| over the satisfied
    examples), then places the holes with temporal slack (see module docstring).  Raises `SketchError` for an
    ill-typed sketch and `EncoderMismatch` if the Z3 encoding and the NumPy evaluator ever disagree.

    Algorithm: MaxSMT at the lowest margin level (= sign-correctness) gives the minimal violated weight W*; the
    margin levels above it (see `margin_levels`) are then tried in ascending order, each with its own MaxSMT, and
    the highest level that still achieves W* wins.  ``timeout_s`` bounds the whole solve (the placement step gets
    its own `PLACEMENT_BUDGET_S`).
    """
    t0 = time.perf_counter()
    examples = list(examples)
    levels = margin_levels()
    enc = Encoder(sketch, examples, levels[0])
    cr = compile_rule(sketch)
    ms = lambda: int((time.perf_counter() - t0) * 1000)       # noqa: E731
    left = lambda: max(0.5, timeout_s - (time.perf_counter() - t0))   # noqa: E731
    log.debug("stage 1 encoded in %d ms", ms())
    status, model = _maxsmt(enc, left())
    log.debug("stage 1 %s at %d ms", status, ms())

    if status == "unsat":                                      # the hole domain itself is empty (e.g. eventually[10, ?b] on a 4 s clip)
        return SolveResult("unsat", sketch, None, {}, 0.0, tuple(e.clip_id for e in examples if e.positive), (),
                           True, ms(), note="no hole assignment is admissible for this sketch on these clips")

    if status == "unknown":
        res = _grid_search(sketch, examples, enc, budget_s=min(timeout_s, 10.0))
        if res is None:
            return SolveResult("timeout", sketch, None, {}, 0.0, tuple(e.clip_id for e in examples), (), True, ms(),
                               note="Z3 timed out")
        sc = res["scores"]
        ok = [_label_ok(ex.positive, s) for ex, s in zip(examples, sc)]
        if not any(o for o, ex in zip(ok, examples) if ex.positive) and any(ex.positive for ex in examples):
            return SolveResult("timeout", sketch, None, {}, 0.0, tuple(e.clip_id for e in examples), (), True, ms(),
                               note="Z3 timed out; grid search found no rule matching a positive")
        margin = min([abs(s) for s, o in zip(sc, ok) if o] or [CLAMP])
        rule = fill_holes(sketch, res["holes"])
        return SolveResult("grid_fallback", sketch, rule, dict(res["holes"]), margin,
                           tuple(ex.clip_id for ex, o in zip(examples, ok) if not o),
                           tuple(ex.clip_id for ex, o in zip(examples, ok) if o), True, ms(),
                           note="Z3 timed out; best point of a 0.5 s grid search")

    # ---- stage 1 done: W* and a witness point; stage 2: climb the margin levels
    assert model is not None
    w_star = _violated_weight(enc, model)
    p1 = enc.read_holes(model)
    s1 = _score_all(cr, enc.preps, p1)
    z3_ok1 = [_is_true(model, enc.goal(k)) for k in range(len(examples))]
    sat1 = [k for k, o in enumerate(z3_ok1) if o]
    has_pos = any(ex.positive for ex in examples)
    if not sat1 or (has_pos and not any(examples[k].positive for k in sat1)):
        _diff_check_point(enc, cr, p1, float(enc.margin), z3_ok1)
        return SolveResult("unsat", sketch, None, {}, 0.0, tuple(e.clip_id for e, o in zip(examples, z3_ok1) if not o),
                           tuple(e.clip_id for e, o in zip(examples, z3_ok1) if o), True, ms(),
                           note="the best assignment fits no positive example")
    best_enc, best_model = enc, model
    start = _best_level(levels, min(abs(s1[k]) for k in sat1))
    note_extra = ""
    if start > 0:                                              # the witness already achieves a higher level
        e2 = Encoder(sketch, examples, levels[start])
        st2, m2 = _maxsmt(e2, left())
        if st2 == "sat" and _violated_weight(e2, m2) <= w_star + 1e-9:
            best_enc, best_model = e2, m2
        else:                                                  # cannot happen unless Z3 timed out
            note_extra = "; margin level not proven"
    cur = start if best_enc is not enc else 0
    for i in range(cur + 1, len(levels)):
        if time.perf_counter() - t0 >= timeout_s:
            note_extra = "; margin maximisation stopped by the timeout"
            break
        e2 = Encoder(sketch, examples, levels[i])
        st2, m2 = _maxsmt(e2, left())
        if st2 == "unknown":
            note_extra = "; margin maximisation stopped by the timeout"
            break
        if st2 == "sat" and _violated_weight(e2, m2) <= w_star + 1e-9:
            best_enc, best_model = e2, m2
        else:
            break

    enc, model = best_enc, best_model
    log.debug("margin %s found at %d ms", enc.margin, ms())
    m_star = float(enc.margin)
    p0 = enc.read_holes(model)
    z3_ok = [_is_true(model, enc.goal(k)) for k in range(len(examples))]
    _diff_check_point(enc, cr, p0, m_star, z3_ok)              # raises EncoderMismatch
    sat_idx = [k for k, o in enumerate(z3_ok) if o]

    # ---- temporal-slack placement, then the mandatory differential check on the returned rule
    holes, how = _place(enc, cr, p0, m_star, sat_idx, min(timeout_s, PLACEMENT_BUDGET_S))
    log.debug("placed (%s) at %d ms", how, ms())
    scores = _score_all(cr, enc.preps, holes)
    for k in sat_idx:
        ex = examples[k]
        if not _label_ok(ex.positive, scores[k]) or not _holds(ex.positive, scores[k], m_star, EPS):
            raise EncoderMismatch(
                f"placed rule `{to_text(fill_holes(sketch, holes))}` fails on clip {ex.clip_id!r}: evaluator score "
                f"{scores[k]:+.4f}, expected {'>=' if ex.positive else '<='} {m_star if ex.positive else -m_star:+.4f}")
    rule = fill_holes(sketch, holes)
    ok = [_label_ok(ex.positive, s) for ex, s in zip(examples, scores)]
    return SolveResult("sat", sketch, rule, dict(holes), m_star,
                       tuple(ex.clip_id for ex, o in zip(examples, ok) if not o),
                       tuple(ex.clip_id for ex, o in zip(examples, ok) if o), True, ms(),
                       note=f"placement: {how}{note_extra}")
