"""Tie annotation of the Lab grid (SPEC 4.5): for every slot and sketch, `alternatives` = the number of distinct optimal
satisfied example sets at the optimal (violated weight, margin), as enumerated by `synth_support.brute_force`; -1 when
that brute force is beyond its budget (`max_points = 40_000`), 0 when the hole domain is empty.

`reference_alternatives` calls `brute_force` directly for one slot.  `ties_for_sketch` produces the same numbers for
all 6,050 slots of one sketch much faster: the score of a hole point on a clip does not depend on the labels, so the
(point x clip) score table is built once per (sketch, used-clip subset) and every labeling of that subset only needs
vectorised comparisons.  When the sketch's candidate set over all eight clips is small enough, one universe table is
built and restricted per subset to the points that lie inside that subset's domain (a finer partition of the same
equivalence classes, so the set of reachable outcomes is identical); `selfcheck` compares both against `brute_force`.
"""
from __future__ import annotations

import itertools
from typing import Optional

import numpy as np

import gridlib as G

MAX_POINTS = 40_000            # synth_support.brute_force default
UNIVERSE_MAX = 100_000
EPS = 1e-9


def _levels() -> list[float]:
    from exemplar.synth.z3enc import margin_levels
    return [float(x) for x in margin_levels()]


def count_alternatives(S: np.ndarray, pos: np.ndarray, weights: np.ndarray, levels: list[float]) -> tuple[int, int]:
    """S: unique score rows [r x u]; pos: bool[u]; weights: float[u].  Mirrors `Brute` + the optimal-set count.
    Returns (optimal satisfied sets at the optimal margin m*, optimal satisfied sets at the lowest margin level).  The
    second number is the tie count of an `unsat` entry: the engine returns the stage-1 witness there, before it climbs
    the margin levels."""
    if S.shape[0] == 0:
        return 0, 0
    holds = []
    wts = []
    for lv in levels:
        h = np.where(pos, S >= lv - EPS, S <= -lv + EPS)
        holds.append(h)
        wts.append((~h) @ weights)
    w_star = wts[0].min()
    m_idx = 0
    for i in range(1, len(levels)):
        if wts[i].min() <= w_star + EPS:
            m_idx = i
        else:
            break
    sel = wts[m_idx] <= w_star + EPS
    sel0 = wts[0] <= w_star + EPS
    return (int(np.unique(holds[m_idx][sel], axis=0).shape[0]),
            int(np.unique(holds[0][sel0], axis=0).shape[0]))


def _subset_examples(cur, U: int, positive: bool = True):
    from exemplar.synth import Example
    return [Example(c.trace, positive, G.WEIGHT, c.alias) for i, c in enumerate(cur) if U >> i & 1]


def brute_alternatives(sk, ex, level0: bool = False) -> int:
    """`brute_force` as written in the test suite, counted per the SPEC definition: -1 beyond its budget, 0 for an
    empty hole domain (``level0``: count at the lowest margin level instead of m*)."""
    from synth_support import brute_force
    br = brute_force(sk, ex, max_points=MAX_POINTS)
    if br is None:
        return -1
    if not br.points:
        return 0

    def holds(positive, s, m):
        return s >= m - EPS if positive else s <= -m + EPS

    m = br.levels[0] if level0 else br.m_star
    sets = set()
    for _, sc in br.points:
        if sum(e.weight for e, s in zip(ex, sc) if not holds(e.positive, s, m)) <= br.w_star + EPS:
            sets.add(frozenset(k for k, (e, s) in enumerate(zip(ex, sc)) if holds(e.positive, s, m)))
    return len(sets)


def reference_alternatives(cur, sketch_text: str, slot: int, level0: bool = False) -> int:
    """`brute_alternatives` for one grid slot."""
    from exemplar.dsl import parse
    from exemplar.synth import Example
    states = G.decode_slot(slot)
    ex = [Example(c.trace, st == 1, G.WEIGHT, c.alias) for c, st in zip(cur, states) if st != 0]
    return brute_alternatives(parse(sketch_text), ex, level0)


def _subsets() -> list[int]:
    return [U for U in range(1, 1 << G.N_CLIPS) if bin(U).count("1") >= 2]


def _labelings(U: int):
    """(slot, [clip indices], positive flags) for every labeling of used subset U with >= 1 yes and >= 1 no."""
    idx = [i for i in range(G.N_CLIPS) if U >> i & 1]
    for bits in range(1, (1 << len(idx)) - 1):
        pos = [bool(bits >> j & 1) for j in range(len(idx))]
        states = [0] * G.N_CLIPS
        for i, p in zip(idx, pos):
            states[i] = 1 if p else 2
        yield G.encode_slot(states), idx, pos


def ties_for_sketch(sketch_id: int, universe_only: Optional[bool] = None) -> dict[int, tuple[int, int]]:
    """slot -> (alternatives at m*, alternatives at the lowest level) for one sketch (all valid slots); (-1, -1) beyond
    the brute-force budget."""
    from exemplar.contracts.dsl_ast import Hole, holes as ast_holes
    from exemplar.dsl import compile_rule, parse, prepare
    from exemplar.synth.z3enc import hole_kinds
    from synth_support import _windows_with_holes, hole_candidates

    lib = G.library()
    cur = G.curated(lib)
    bank = G.sketch_bank()
    sk = parse(bank[sketch_id]["text"])
    names = ast_holes(sk)
    kinds = hole_kinds(sk)
    wins = _windows_with_holes(sk)
    cr = compile_rule(sk)
    preps = [prepare(c.trace) for c in cur]
    levels = _levels()
    lens = [max(c.trace.duration_ms, c.trace.frames[-1].t_ms if c.trace.frames else 0) / 1000 for c in cur]

    def ordered(pt: dict) -> bool:
        for a, b in wins:
            lo = pt[a.name] if isinstance(a, Hole) else a
            hi = pt[b.name] if isinstance(b, Hole) else b
            if lo > hi:
                return False
        return True

    def points(cands: dict) -> list[dict]:
        out = []
        for combo in itertools.product(*(cands[n] for n in names)):
            pt = dict(zip(names, combo))
            if ordered(pt):
                out.append(pt)
        return out

    def prod(cands: dict) -> int:
        t = 1
        for n in names:
            t *= len(cands[n])
        return t

    all_cands = hole_candidates(sk, _subset_examples(cur, (1 << G.N_CLIPS) - 1))
    use_universe = prod(all_cands) <= UNIVERSE_MAX if universe_only is None else universe_only
    if use_universe:
        upts = points(all_cands)
        coords = np.array([[pt[n] for n in names] for pt in upts], dtype=np.float64).reshape(len(upts), len(names))
        table = np.array([[cr.score(preps[k], pt) for k in range(G.N_CLIPS)] for pt in upts],
                         dtype=np.float64).reshape(len(upts), G.N_CLIPS)
        is_time = np.array([kinds[n] != "hour" for n in names], dtype=bool)

    out: dict[int, tuple[int, int]] = {}
    for U in _subsets():
        idx = [i for i in range(G.N_CLIPS) if U >> i & 1]
        cands = hole_candidates(sk, _subset_examples(cur, U))
        if prod(cands) > MAX_POINTS:
            for slot, _, _ in _labelings(U):
                out[slot] = (-1, -1)
            continue
        if use_universe:
            L = max(lens[i] for i in idx)
            keep = np.all(np.where(is_time[None, :], coords <= L + 1e-12, True), axis=1) if names else np.ones(len(upts), bool)
            S = table[keep][:, idx]
        else:
            pts = points(cands)
            S = np.array([[cr.score(preps[k], pt) for k in idx] for pt in pts], dtype=np.float64).reshape(len(pts), len(idx))
        S = np.unique(S, axis=0) if S.shape[0] else S
        w = np.full(len(idx), G.WEIGHT)
        for slot, _, pos in _labelings(U):
            out[slot] = count_alternatives(S, np.array(pos), w, levels)
    return out
