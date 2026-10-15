"""The Z3 encoding is the NumPy evaluator, bit for bit, at every hole point and margin level.

For random well-typed sketches (every operator, 1-3 holes, hour holes and context atoms) over random small traces
and random hole points, the encoder's GE / LE formulas, with the holes fixed, must hold exactly when the DSL
evaluator's score is >= m / <= -m.  This is the semantic core of the differential check: it does not involve any
optimisation, so a failure here is an encoder bug, not a solver artefact.

`SYNTH_PROP_SCALE=10` runs ten times as many examples (use it before changing the encoder).
"""
from __future__ import annotations

import os
import random
from fractions import Fraction

import z3
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from dsl_strategies import atoms_for
from exemplar.contracts.dsl_ast import Always, And, Eventually, HoldsFor, Hole, Not, Or, Rule, Then, VarDecl
from exemplar.dsl import compile_rule, parse, to_text, typecheck
from exemplar.dsl.util import normalize
from exemplar.synth import Example
from exemplar.synth.z3enc import Encoder, margin_levels
from synth_support import hole_candidates, instances, small_traces

_SCALE = float(os.environ.get("SYNTH_PROP_SCALE", "1"))
_HC = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]
LEVELS = [Fraction(0)] + margin_levels()


def _truth(enc: Encoder, formula, pt) -> bool:
    if formula is True or formula is False:
        return formula
    pairs = []
    for h, v in enc.hv.items():
        c = enc.hole_value_expr(h, pt[h])
        pairs.append((v, z3.IntVal(c, enc.ctx) if isinstance(c, int) else c))
    r = z3.simplify(z3.substitute(formula, *pairs))
    if z3.is_true(r):
        return True
    if z3.is_false(r):
        return False
    s = z3.Solver(ctx=enc.ctx)                                    # not folded completely: ask the solver
    s.add(*enc.bind_holes(pt))
    s.add(formula)
    return s.check() == z3.sat


def _domain_ok(enc: Encoder, pt) -> bool:
    return all(_truth(enc, d, pt) for d in enc.domain)


def check_encoding(sketch: Rule, examples: list[Example], pts: list[dict]) -> None:
    cr = compile_rule(sketch)
    for lv in LEVELS:
        enc = Encoder(sketch, examples, lv)
        for pt in pts:
            if not _domain_ok(enc, pt):
                continue
            for k in range(len(examples)):
                score = cr.score(enc.preps[k], pt)
                ge, le = enc.formulas(k)
                assert _truth(enc, ge, pt) == (score >= float(lv) - 1e-9), (to_text(sketch), pt, float(lv), score, "GE")
                assert _truth(enc, le, pt) == (score <= -float(lv) + 1e-9), (to_text(sketch), pt, float(lv), score, "LE")


@settings(max_examples=int(150 * _SCALE), deadline=None, suppress_health_check=_HC)
@given(instances(max_frames=8, max_holes=3, n_examples=(1, 2)), st.randoms(use_true_random=False))
def test_encoding_equals_evaluator_on_random_sketches(inst, rnd: random.Random):
    sketch, examples = inst
    cands = hole_candidates(sketch, examples)
    check_encoding(sketch, examples, [{h: rnd.choice(v) for h, v in cands.items()} for _ in range(4)])


# ---- focused: every temporal operator on top of small bodies, constant or hole bounds drawn from the trace's gaps
@st.composite
def focused_instances(draw):
    tr = draw(small_traces(max_frames=8, clip_id="f0"))
    tr2 = draw(small_traces(max_frames=8, clip_id="f1"))
    decls = [("x", "Person"), ("y", "Carryable")]
    atom = atoms_for(decls)
    gaps = sorted({(b.t_ms - a.t_ms) / 1000 for a in tr.frames for b in tr.frames if b.t_ms >= a.t_ms} | {0.0, 1000.0})
    bound = st.one_of(st.sampled_from(gaps), st.sampled_from(["a", "b", "d"]).map(lambda n: Hole(name=n)))

    def ordered(p):
        a, b = p
        return (b, a) if not isinstance(a, Hole) and not isinstance(b, Hole) and a > b else (a, b)

    win = st.tuples(bound, bound).map(ordered)
    leaf = st.one_of(atom, st.lists(atom, min_size=2, max_size=2).map(lambda xs: And(args=tuple(xs))),
                     atom.map(lambda a: Not(arg=a)))
    body = st.one_of(
        st.tuples(bound, leaf).map(lambda t: HoldsFor(d=t[0], arg=t[1])),
        st.tuples(win, leaf).map(lambda t: Always(a=t[0][0], b=t[0][1], arg=t[1])),
        st.tuples(win, leaf).map(lambda t: Eventually(a=t[0][0], b=t[0][1], arg=t[1])),
        st.tuples(win, leaf, leaf).map(lambda t: Then(a=t[0][0], b=t[0][1], left=t[1], right=t[2])),
        st.tuples(win, bound, leaf).map(lambda t: Not(arg=Always(a=t[0][0], b=t[0][1],
                                                              arg=HoldsFor(d=t[1], arg=t[2])))),
        st.tuples(win, win, leaf, leaf).map(lambda t: Or(args=(Eventually(a=t[0][0], b=t[0][1], arg=t[2]),
                                                            Always(a=t[1][0], b=t[1][1], arg=t[3])))))
    b = normalize(draw(body))
    rule = Rule(vars=tuple(VarDecl(name=n, type=t) for n, t in decls), body=b)
    if typecheck(rule):                       # drop variables the body does not use
        text = to_text(b)
        rule = Rule(vars=tuple(v for v in rule.vars if f"{v.name}," in text or f"{v.name})" in text), body=b)
    return rule, [Example(tr, True, 1.0, "f0"), Example(tr2, False, 1.0, "f1")]


@settings(max_examples=int(150 * _SCALE), deadline=None, suppress_health_check=_HC)
@given(focused_instances(), st.randoms(use_true_random=False))
def test_encoding_equals_evaluator_on_focused_operators(inst, rnd: random.Random):
    sketch, examples = inst
    assume(not typecheck(sketch))
    cands = hole_candidates(sketch, examples)
    check_encoding(sketch, examples, [{h: rnd.choice(v) for h, v in cands.items()} for _ in range(5)])


def test_known_boundary_exact_gap_matches_integer_ms_semantics():
    """Frames at 100 ms and 300 ms: a hole placed exactly on the 0.2 s gap is inside the window (docs/DSL.md)."""
    from exemplar.contracts.trace import Entity, Fact, Frame, Trace
    tr = Trace(clip_id="b", source="fixture", duration_ms=400,
               entities=(Entity(id="p1", type="person"), Entity(id="k1", type="package")),
               frames=(Frame(t_ms=100, facts=(Fact(pred="picks_up", args=("p1", "k1"), conf="high"),)),
                       Frame(t_ms=300, facts=(Fact(pred="leaves", args=("p1", "porch"), conf="high"),))))
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch)")
    ex = [Example(tr, True, 1.0, "b")]
    enc = Encoder(sk, ex, Fraction(1, 10))
    cr = compile_rule(sk)
    for pt, expected in (({"a": 0.2, "b": 0.2}, True), ({"a": 0.0, "b": 0.1}, False), ({"a": 0.21, "b": 0.4}, False)):
        assert (cr.score(enc.preps[0], pt) > 0) == expected
        assert _truth(enc, enc.formulas(0)[0], pt) == expected
