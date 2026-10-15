"""The Z3 encoding is the NumPy evaluator, bit for bit, at every hole point and margin level.

For random well-typed sketches (every operator, 1-3 holes, hour holes and context atoms) over random small traces
and random hole points, the encoder's GE / LE formulas, with the holes fixed, must hold exactly when the DSL
evaluator's score is >= m / <= -m.  This is the semantic core of the differential check: it does not involve any
optimisation, so a failure here is an encoder bug, not a solver artefact.
"""
from __future__ import annotations

import os
import random

import z3
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from exemplar.contracts.dsl_ast import Hole, holes as ast_holes
from exemplar.dsl import compile_rule, parse, to_text
from exemplar.synth import Example
from exemplar.synth.z3enc import Encoder, margin_levels
from synth_support import hole_candidates, instances

_SCALE = float(os.environ.get("SYNTH_PROP_SCALE", "1"))
_HC = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]
LEVELS = [0.0] + [float(x) for x in margin_levels()]


def _truth(enc: Encoder, formula, pt) -> bool:
    if formula is True or formula is False:
        return formula
    s = z3.Solver(ctx=enc.ctx)
    s.add(*enc.bind_holes(pt))
    s.add(formula)
    return s.check() == z3.sat


def _domain_ok(enc: Encoder, pt) -> bool:
    s = z3.Solver(ctx=enc.ctx)
    s.add(*enc.bind_holes(pt))
    s.add(*enc.domain)
    return s.check() == z3.sat


@settings(max_examples=int(250 * _SCALE), deadline=None, suppress_health_check=_HC)
@given(instances(max_frames=8, max_holes=3, n_examples=(1, 2)), st.randoms(use_true_random=False))
def test_encoding_equals_evaluator_at_every_level(inst, rnd: random.Random):
    sketch, examples = inst
    cands = hole_candidates(sketch, examples)
    cr = compile_rule(sketch)
    for _ in range(4):                                             # four random hole points per instance
        pt = {h: rnd.choice(v) for h, v in cands.items()}
        for lv in LEVELS:
            enc = Encoder(sketch, examples, margin=_frac(lv))
            if not _domain_ok(enc, pt):
                continue
            for k, ex in enumerate(examples):
                score = cr.score(enc.preps[k], pt)
                ge, le = enc.formulas(k)
                exp_ge, exp_le = score >= lv - 1e-9, score <= -lv + 1e-9
                assert _truth(enc, ge, pt) == exp_ge, (to_text(sketch), pt, lv, score, "GE")
                assert _truth(enc, le, pt) == exp_le, (to_text(sketch), pt, lv, score, "LE")


def _frac(x: float):
    from fractions import Fraction
    return Fraction(x).limit_denominator(10**6)


def test_known_boundary_exact_gap_matches_integer_ms_semantics():
    """Frames at 100 ms and 300 ms: a hole placed exactly on the 0.2 s gap is inside the window (docs/DSL.md)."""
    from exemplar.contracts.trace import Entity, Fact, Frame, Trace
    tr = Trace(clip_id="b", source="fixture", duration_ms=400,
               entities=(Entity(id="p1", type="person"), Entity(id="k1", type="package")),
               frames=(Frame(t_ms=100, facts=(Fact(pred="picks_up", args=("p1", "k1"), conf="high"),)),
                       Frame(t_ms=300, facts=(Fact(pred="leaves", args=("p1", "porch"), conf="high"),))))
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch)")
    ex = [Example(tr, True, 1.0, "b")]
    enc = Encoder(sk, ex, _frac(0.1))
    cr = compile_rule(sk)
    for pt, expected in (({"a": 0.2, "b": 0.2}, True), ({"a": 0.2, "b": 0.19}, None), ({"a": 0.0, "b": 0.1}, False),
                         ({"a": 0.21, "b": 0.4}, False)):
        if expected is None:
            continue
        assert (cr.score(enc.preps[0], pt) > 0) == expected
        assert _truth(enc, enc.formulas(0)[0], pt) == expected
