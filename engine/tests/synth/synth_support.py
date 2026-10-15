"""Support for the synthesis property tests: small random instances and an exhaustive reference solver.

The reference solver enumerates every *equivalence class* of hole values: window membership only depends on how a
hole compares with the pairwise frame offsets Delta(i, j), so the candidates are 0, L, every offset and the midpoint
between consecutive ones (hours: 0..23).  Everything is scored with the DSL evaluator, so it is independent of Z3.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from fractions import Fraction

from hypothesis import strategies as st

from dsl_strategies import CONFS, LABELS, POOL, _candidate_facts, rules
from exemplar.contracts.dsl_ast import Always, Eventually, Hole, Rule, Then, children, holes as ast_holes
from exemplar.contracts.trace import Entity, Fact, Frame, Trace, TraceContext
from exemplar.dsl import compile_rule, prepare
from exemplar.synth import Example
from exemplar.synth.z3enc import hole_kinds, margin_levels

GAPS = (500, 1000, 2000)


@st.composite
def small_traces(draw, max_frames: int = 6, clip_id: str = "t") -> Trace:
    n_ent = draw(st.integers(1, 3))
    picked = draw(st.lists(st.sampled_from(POOL), min_size=n_ent, max_size=n_ent, unique=True))
    entities = [Entity(id=i, type=t, attrs=tuple(draw(st.lists(st.sampled_from(LABELS), max_size=1, unique=True))))
                for i, t in picked]
    cands = _candidate_facts(entities)
    n = draw(st.integers(1, max_frames))
    gaps = draw(st.lists(st.sampled_from(GAPS), min_size=n, max_size=n))
    ts = [draw(st.sampled_from([0, 0, 500]))]
    for g in gaps[1:]:
        ts.append(ts[-1] + g)
    # favour facts the rule strategies mention: few predicates, dense
    triples = draw(st.lists(st.tuples(st.integers(0, n - 1), st.integers(0, len(cands) - 1), st.integers(0, 2)),
                            max_size=4 * n))
    by_frame: list[list[Fact]] = [[] for _ in range(n)]
    for fi, ci, cf in triples:
        pred, args = cands[ci]
        by_frame[fi].append(Fact(pred=pred, args=args, conf=CONFS[cf]))
    frames = [Frame(t_ms=t, facts=tuple(fs)) for t, fs in zip(ts, by_frame)]
    ctx = TraceContext(sub_type=draw(st.one_of(st.none(), st.sampled_from(["human", "vehicle"]))),
                       local_hour=draw(st.one_of(st.none(), st.integers(0, 23))))
    return Trace(clip_id=clip_id, source="fixture", duration_ms=ts[-1] + draw(st.sampled_from([0, 500, 2000])),
                 entities=tuple(entities), frames=tuple(frames), context=ctx)


@st.composite
def instances(draw, max_frames: int = 6, max_holes: int = 3, n_examples=(2, 4), min_holes: int = 1):
    """(sketch with 1..max_holes holes, examples) over small traces."""
    k = draw(st.integers(*n_examples))
    traces_ = [draw(small_traces(max_frames=max_frames, clip_id=f"c{i}")) for i in range(k)]
    sketch = draw(rules(trace=traces_[0], holes=True, context=True, max_leaves=5))
    hs = ast_holes(sketch)
    if not (min_holes <= len(hs) <= max_holes):
        from hypothesis import reject
        reject()
    labels = draw(st.lists(st.booleans(), min_size=k, max_size=k))
    weights = draw(st.lists(st.sampled_from([1.0, 3.0]), min_size=k, max_size=k))
    return sketch, [Example(t, l, w, f"c{i}") for i, (t, l, w) in enumerate(zip(traces_, labels, weights))]


def _windows_with_holes(rule: Rule) -> list[tuple]:
    out = []

    def walk(n):
        if isinstance(n, (Eventually, Always, Then)):
            out.append((n.a, n.b))
        for c in children(n):
            walk(c)

    walk(rule)
    return out


def _nodes(sketch: Rule, examples) -> list[Fraction]:
    """Offsets a time hole can be compared with: 0, the clip length, every pairwise frame offset and every constant
    window bound of the sketch (a hole is also ordered against those).  Between two nodes all values are equivalent."""
    deltas = {Fraction(0)}
    L = 0
    for ex in examples:
        t = [f.t_ms for f in prepare(ex.trace).trace.frames]
        L = max(L, ex.trace.duration_ms, t[-1] if t else 0)
        deltas |= {Fraction(b - a, 1000) for a in t for b in t if b >= a}
    deltas.add(Fraction(L, 1000))
    for lo, hi in _windows_with_holes(sketch):
        for x in (lo, hi):
            if not isinstance(x, Hole) and Fraction(x).limit_denominator(10**6) <= Fraction(L, 1000):
                deltas.add(Fraction(x).limit_denominator(10**6))
    return sorted(deltas)


def node_values(sketch: Rule, examples) -> list[float]:
    return [float(v) for v in _nodes(sketch, examples)]


def hole_candidates(sketch: Rule, examples) -> dict[str, list[float]]:
    """Per hole, one representative of every equivalence class: each node and the midpoint of consecutive nodes."""
    kinds = hole_kinds(sketch)
    s = _nodes(sketch, examples)
    vals = sorted(set(s) | {(x + y) / 2 for x, y in zip(s, s[1:])})
    out = {}
    for h in ast_holes(sketch):
        out[h] = [float(h_) for h_ in range(24)] if kinds[h] == "hour" else [float(v) for v in vals]
    return out


@dataclass
class Brute:
    points: list          # (holes, scores per example)
    w_star: float
    levels: list
    m_star: float


def _holds(positive, score, m, eps=1e-9):
    return score >= m - eps if positive else score <= -m + eps


def brute_force(sketch: Rule, examples, *, max_points: int = 40_000):
    cands = hole_candidates(sketch, examples)
    names = list(cands)
    total = 1
    for n in names:
        total *= len(cands[n])
    if total > max_points:
        return None
    cr = compile_rule(sketch)
    preps = [prepare(e.trace) for e in examples]
    wins = _windows_with_holes(sketch)

    def ordered(pt):
        for a, b in wins:
            lo = pt[a.name] if isinstance(a, Hole) else a
            hi = pt[b.name] if isinstance(b, Hole) else b
            if lo > hi:
                return False
        return True

    pts = []
    for combo in itertools.product(*(cands[n] for n in names)):
        pt = dict(zip(names, combo))
        if not ordered(pt):
            continue
        pts.append((pt, [cr.score(p, pt) for p in preps]))
    levels = [float(x) for x in margin_levels()]
    if not pts:                                  # the hole domain itself is empty (e.g. window [10, ?b] on a 4 s clip)
        return Brute([], float('inf'), levels, 0.0)

    def weight(scores, m):
        return sum(e.weight for e, s in zip(examples, scores) if not _holds(e.positive, s, m))

    w_star = min(weight(sc, levels[0]) for _, sc in pts)
    m_star = levels[0]
    for lv in levels[1:]:
        if min(weight(sc, lv) for _, sc in pts) <= w_star + 1e-9:
            m_star = lv
        else:
            break
    return Brute(pts, w_star, levels, m_star)
