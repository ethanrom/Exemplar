"""solve_sketch against an exhaustive reference, plus the concrete behaviours the plan promises.

The reference (`synth_support.brute_force`) scores every equivalence class of hole values with the DSL evaluator, so
agreement here means: Z3's optimum (violated weight, then margin) is the true optimum, an "unsat"/violated verdict is
never wrong, and the returned rule really has the claimed margin.  This is the project's correctness guarantee for
the encoder (PLAN.md section 2.3 "Differential check").
"""
from __future__ import annotations

import os

import pytest
from hypothesis import HealthCheck, assume, given, settings

from exemplar.contracts.dsl_ast import holes as ast_holes
from exemplar.contracts.trace import Entity, Fact, Frame, Trace
from exemplar.dsl import compile_rule, parse, prepare, robustness, to_text, typecheck
from exemplar.synth import EncoderMismatch, Example, InfeasibleBox, SketchError, hole_box, solve_sketch
from exemplar.synth.z3enc import hole_kinds
from synth_support import brute_force, instances, node_values
from dsl_helpers import load

_SCALE = float(os.environ.get("SYNTH_PROP_SCALE", "1"))
_HC = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]
TOL = 1e-9


def _weight(examples, ids):
    byid = {e.clip_id: e for e in examples}
    return sum(byid[i].weight for i in ids)


@settings(max_examples=int(220 * _SCALE), deadline=None, suppress_health_check=_HC)
@given(instances(max_frames=5, max_holes=3, n_examples=(2, 4)))
def test_solver_agrees_with_exhaustive_search(inst):
    sketch, examples = inst
    bf = brute_force(sketch, examples, max_points=6000)
    assume(bf is not None)
    res = solve_sketch(sketch, examples, timeout_s=30)
    assert res.status in ("sat", "unsat"), (res.status, res.note)
    assert res.diff_check_ok
    if not bf.points:
        assert res.status == "unsat" and res.rule is None
        return

    # 1. the minimal violated weight is the true minimum; "sat" means the sketch beats the never-fires rule
    pos_total = sum(e.weight for e in examples if e.positive)
    total = sum(e.weight for e in examples)
    base = pos_total if any(e.positive for e in examples) else total
    expect_sat = bf.w_star < base - TOL
    assert (res.status == "sat") == expect_sat, (to_text(sketch), res.status, bf.w_star, base)
    if res.status == "unsat":
        assert res.rule is None
        return
    assert abs(_weight(examples, res.violated) - bf.w_star) < TOL, (to_text(sketch), res.violated, bf.w_star)

    # 2. the margin is the true maximum, and the returned rule really achieves it
    assert abs(res.margin - bf.m_star) < TOL, (to_text(sketch), res.margin, bf.m_star)
    assert res.rule is not None and not typecheck(res.rule) and not ast_holes(res.rule)
    assert set(res.holes) == set(ast_holes(sketch))
    cr = compile_rule(sketch)
    for ex in examples:
        s = cr.score(prepare(ex.trace), res.holes)
        if ex.clip_id in res.satisfied:
            assert (s > 0) == ex.positive
            assert (s >= res.margin - 1e-6) if ex.positive else (s <= -res.margin + 1e-6)
        else:
            assert (s > 0) != ex.positive
    assert set(res.satisfied) | set(res.violated) == {e.clip_id for e in examples}
    # 3. holes are admissible: inside [0, clip_len] (hours 0-23)
    L = max(max(e.trace.duration_ms, e.trace.frames[-1].t_ms) for e in examples) / 1000
    for v in res.holes.values():
        assert -TOL <= v <= max(L, 23) + TOL
    # 4. the rule printed from the solution parses back to itself
    assert parse(to_text(res.rule)) == res.rule


@settings(max_examples=int(80 * _SCALE), deadline=None, suppress_health_check=_HC)
@given(instances(max_frames=5, max_holes=3, n_examples=(2, 3)))
def test_hole_box_is_the_exact_bounding_box_of_the_feasible_set(inst):
    sketch, examples = inst
    bf = brute_force(sketch, examples, max_points=5000)
    assume(bf is not None)
    res = solve_sketch(sketch, examples, timeout_s=30)
    assume(res.status == "sat")
    box = hole_box(sketch, examples, satisfied=res.satisfied, margin=res.margin)
    assert set(box) == set(ast_holes(sketch))
    byid = {e.clip_id: i for i, e in enumerate(examples)}
    sat = [byid[c] for c in res.satisfied]
    feasible = [pt for pt, sc in bf.points
                if all((sc[i] >= res.margin - TOL) if examples[i].positive else (sc[i] <= -res.margin + TOL)
                       for i in sat)]
    assert feasible, "the solution itself lies in some equivalence class of the reference"
    nodes = node_values(sketch, examples)

    def closure(h, v):
        """A representative in the open gap between two offsets stands for the whole gap (the box is a closure)."""
        if h in hours or any(abs(v - n) < 1e-12 for n in nodes):
            return v, v
        return max(n for n in nodes if n < v), min(n for n in nodes if n > v)

    hours = {h for h, k in hole_kinds(sketch).items() if k == "hour"}
    for h in box:
        lo = min(closure(h, p[h])[0] for p in feasible)
        hi = max(closure(h, p[h])[1] for p in feasible)
        assert abs(box[h][0] - lo) < 1e-6 and abs(box[h][1] - hi) < 1e-6, (to_text(sketch), h, box[h], (lo, hi))
        assert box[h][0] - TOL <= res.holes[h] <= box[h][1] + TOL


# --------------------------------------------------------------------------- concrete behaviours
def _theft_examples():
    return [Example(load("theft_a"), True, 3, "theft_a"), Example(load("theft_b"), True, 3, "theft_b"),
            Example(load("delivery_a"), False, 3, "delivery_a"), Example(load("delivery_b"), False, 3, "delivery_b"),
            Example(load("unattended_package"), False, 1, "unattended_package"),
            Example(load("visitor_no_ring"), False, 1, "visitor_no_ring")]


def test_theft_sketch_solves_and_generalises_with_slack():
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)")
    res = solve_sketch(sk, _theft_examples())
    assert res.status == "sat" and not res.violated and res.diff_check_ok
    assert res.holes["a"] == 0.0                         # the lower bound takes 0 when feasible
    assert res.holes["b"] > 3.0                          # not the tight observed gap (2-3 s)
    assert res.margin == pytest.approx(0.3)              # theft_b's picks_up is only `med`


def test_single_positive_gap_7s_gives_then_0_to_centre():
    """docs/DSL.md "Hole placement": one positive with a 7 s gap in a 24 s clip gives then[0, 15.5], not then[7, 7]."""
    ent = (Entity(id="p1", type="person"), Entity(id="k1", type="package"))
    fr = []
    for t in range(0, 25):
        facts = []
        if t == 4:
            facts.append(Fact(pred="picks_up", args=("p1", "k1"), conf="high"))
        if t == 11:
            facts.append(Fact(pred="leaves", args=("p1", "porch"), conf="high"))
        fr.append(Frame(t_ms=t * 1000, facts=tuple(facts)))
    tr = Trace(clip_id="one", source="fixture", duration_ms=24_000, entities=ent, frames=tuple(fr))
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch)")
    res = solve_sketch(sk, [Example(tr, True, 3, "one")])
    assert res.status == "sat"
    assert to_text(res.rule) == "exists p: Person, k: Package: picks_up(p, k) then[0, 15.5] leaves(p, porch)"


def test_noisy_label_is_reported_as_violated_not_unsat():
    """A mislabelled clip costs one violation (a counterexample) instead of making the sketch unsat."""
    ex = _theft_examples() + [Example(load("delivery_a"), True, 1, "mislabelled_delivery")]
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)")
    res = solve_sketch(sk, ex)
    assert res.status == "sat"
    # delivery_a is a negative (weight 3) and its twin a positive (weight 1): the cheaper violation is the positive
    assert res.violated == ("mislabelled_delivery",)


def test_sketch_that_matches_no_positive_is_unsat():
    sk = parse("exists v: Vehicle: eventually[?a, ?b] in_zone(v, driveway)")
    res = solve_sketch(sk, _theft_examples())
    assert res.status == "unsat" and res.rule is None


def test_no_holes_sketch_is_just_evaluated():
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k)")
    res = solve_sketch(sk, _theft_examples())
    assert res.status == "sat" and res.holes == {} and res.rule == sk


def test_hour_holes_and_context():
    t = load("theft_a")                                  # local_hour 14
    other = t.model_copy(update={"clip_id": "late", "context": t.context.model_copy(update={"local_hour": 3})})
    sk = parse("exists p: Person, k: Package: eventually[0, 30] picks_up(p, k) when hour in [?h1, ?h2]")
    res = solve_sketch(sk, [Example(t, True, 3, "theft_a"), Example(other, False, 3, "late")])
    assert res.status == "sat" and not res.violated
    h1, h2 = res.holes["h1"], res.holes["h2"]
    assert h1 == int(h1) and h2 == int(h2) and 0 <= h1 <= 23 and 0 <= h2 <= 23
    # the solved interval (which may wrap past midnight) contains 14 and excludes 3: checked by the evaluator
    assert robustness(res.rule, t) > 0 and robustness(res.rule, other) < 0
    # not pinned to the observed hour: the solution is spread over the feasible region
    assert (h1, h2) != (14, 14)


def test_untypeable_sketch_is_rejected():
    sk = parse("exists p: Person: rings_bell(p, p)")
    with pytest.raises(SketchError):
        solve_sketch(sk, [Example(load("theft_a"), True, 1)])


def test_hole_box_infeasible_raises():
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)")
    with pytest.raises(InfeasibleBox):
        hole_box(sk, _theft_examples(), satisfied=("theft_b",), margin=0.45)      # theft_b only reaches 0.3


def test_encoder_mismatch_is_loud(monkeypatch):
    """If the evaluator ever disagreed with the encoding, `solve_sketch` must raise rather than return the rule."""
    import exemplar.synth.solve as S
    real = S._score_all
    monkeypatch.setattr(S, "_score_all", lambda cr, preps, pt: [-s for s in real(cr, preps, pt)])
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)")
    with pytest.raises(EncoderMismatch):
        solve_sketch(sk, _theft_examples())


# --------------------------------------------------------------------------- Z3 timeout -> grid fallback
def _force_timeout(monkeypatch):
    import exemplar.synth.solve as S
    monkeypatch.setattr(S, "_maxsmt", lambda enc, timeout_s: ("unknown", None))


def test_grid_fallback_when_z3_times_out(monkeypatch):
    _force_timeout(monkeypatch)
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)")
    res = solve_sketch(sk, _theft_examples(), timeout_s=5)
    assert res.status == "grid_fallback" and res.rule is not None and not ast_holes(res.rule)
    assert res.diff_check_ok and not res.violated and res.margin == pytest.approx(0.3)
    assert all(v % 0.5 == 0 for v in res.holes.values())                 # on the 0.5 s grid
    cr = compile_rule(sk)
    for ex in _theft_examples():
        assert (cr.score(prepare(ex.trace), res.holes) > 0) == ex.positive


def test_grid_fallback_large_grid_and_hours(monkeypatch):
    _force_timeout(monkeypatch)
    sk = parse("exists p: Person, k: Package: eventually[?a, ?b] picks_up(p, k) and holds_for >= ?d near(p, k) "
               "when hour in [?h1, ?h2]")
    t = load("theft_a")
    other = t.model_copy(update={"clip_id": "late", "context": t.context.model_copy(update={"local_hour": 3})})
    res = solve_sketch(sk, [Example(t, True, 3, "theft_a"), Example(other, False, 3, "late")], timeout_s=5)
    assert res.status in ("grid_fallback", "timeout")
    if res.status == "grid_fallback":
        assert robustness(res.rule, t) > 0 and robustness(res.rule, other) < 0


def test_timeout_when_nothing_matches_a_positive(monkeypatch):
    _force_timeout(monkeypatch)
    sk = parse("exists v: Vehicle: eventually[?a, ?b] in_zone(v, driveway)")
    res = solve_sketch(sk, _theft_examples(), timeout_s=5)
    assert res.status == "timeout" and res.rule is None
