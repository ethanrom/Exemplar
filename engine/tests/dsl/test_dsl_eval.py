"""Evaluators on fixtures and hand-built traces: robustness, boolean, windows, context, holes."""
from __future__ import annotations

import numpy as np
import pytest

from dsl_helpers import ALL_FIXTURES, load
from dsl_reference import ref_score
from exemplar.contracts.dsl_ast import Atom, fill_holes
from exemplar.contracts.ontology import CLAMP
from exemplar.contracts.trace import Entity, Fact, Frame, Trace, TraceContext
from exemplar.dsl import (UnboundHoleError, compile_rule, evaluate, evaluate_bool, parse, prepare, rho, robustness,
                          typecheck)

C = CLAMP
approx = lambda x: pytest.approx(x, abs=1e-12)


def mk(frames, entities=(("p1", "person"), ("k1", "package")), duration_ms=None, **ctx) -> Trace:
    """frames: [(t_ms, [(pred, args, conf), ...]), ...]"""
    fr = tuple(Frame(t_ms=t, facts=tuple(Fact(pred=p, args=tuple(a), conf=c) for p, a, c in fs)) for t, fs in frames)
    last = fr[-1].t_ms if fr else 0
    return Trace(clip_id="t", source="fixture", duration_ms=duration_ms if duration_ms is not None else last + 1000,
                 entities=tuple(Entity(id=i, type=t) for i, t in entities), frames=fr,
                 context=TraceContext(**ctx))


def R(text):
    r = parse(text)
    assert typecheck(r) == [], typecheck(r)
    return r


def score_and_bool(rule_text, tr, holes=None):
    r = R(rule_text)
    return robustness(r, tr, holes), evaluate_bool(r, tr, holes)


# ------------------------------------------------------------------ fixtures: the PLAN's example concepts
THEFT = "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)"
DWELL = "exists v: Vehicle: holds_for >= 120 in_zone(v, dock)"
UNATTENDED = "exists k: Package: always[0, 24] in_zone(k, steps)"


def matches(rule_text, name):
    r = R(rule_text)
    tr = load(name)
    s, b = robustness(r, tr), evaluate_bool(r, tr)
    assert b == (s > 0), (name, s, b)
    return s > 0


def test_theft_rule_matches_thefts_not_deliveries():
    got = {n: matches(THEFT, n) for n in ALL_FIXTURES}
    assert {n for n, m in got.items() if m} == {"theft_a", "theft_b"}
    assert robustness(R(THEFT), load("theft_a")) == approx(0.45)         # picks_up high
    assert robustness(R(THEFT), load("theft_b")) == approx(0.30)         # picks_up med is the weakest link


def test_theft_rule_variants_with_holes():
    sketch = R("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)")
    assert robustness(sketch.model_copy(), load("theft_a"), {"b": 4.0}) == approx(0.45)    # leaves at +4 s exactly
    assert robustness(sketch, load("theft_a"), {"b": 3.5}) < 0                              # just short of +4 s
    assert robustness(sketch, load("delivery_a"), {"b": 20.0}) < 0                          # leaves but never picks up


def test_dwell_rule_matches_vehicle_dwell_only():
    got = {n for n in ALL_FIXTURES if matches(DWELL, n)}
    assert got == {"vehicle_dwell_dock"}
    # the dock run is sampled at 6..126 s (high) then 156 s (med): continuous for 150 s, not for 151 s.
    tr = load("vehicle_dwell_dock")
    for d, ok in [(120, True), (126, True), (150, True), (150.5, False), (151, False)]:
        r = R(f"exists v: Vehicle: holds_for >= {d} in_zone(v, dock)")
        assert (robustness(r, tr) > 0) == ok == evaluate_bool(r, tr), d
    assert robustness(R("exists v: Vehicle: holds_for >= 120 in_zone(v, dock)"), tr) == approx(0.45)   # 6..126 s, all high
    assert robustness(R("exists v: Vehicle: holds_for >= 150 in_zone(v, dock)"), tr) == approx(0.30)   # must include 156 s (med)


def test_unattended_package_rule():
    got = {n for n in ALL_FIXTURES if matches(UNATTENDED, n)}
    assert got == {"unattended_package"}
    # window and duration variants: windows are truncated at the clip end, so long windows still match
    for text in ["exists k: Package: holds_for >= 20 in_zone(k, steps)",
                 "exists k: Package: always[0, 1000] in_zone(k, steps)"]:
        assert {n for n in ALL_FIXTURES if matches(text, n)} == {"unattended_package"}


def test_spec_unattended_shape_with_a_person_binding():
    """`always[0,d] in_zone(k, steps) and not eventually[0,d] present(p)`: the package sits on the steps for a
    stretch during which the bound person is never seen. It needs a person entity, so it matches theft_b
    (package alone on the steps, person arrives later), not the person-less unattended_package clip."""
    rule = "exists k: Package, p: Person: always[0, 3] in_zone(k, steps) and not eventually[0, 3] present(p)"
    assert {n for n in ALL_FIXTURES if matches(rule, n)} == {"theft_b"}


def test_visitor_rules():
    rings = "exists p: Person: eventually[0, 5] rings_bell(p)"
    assert {n for n in ALL_FIXTURES if matches(rings, n)} == {"visitor_rings", "delivery_b"}
    # a 'quiet stretch' reading of `not eventually`: it holds from any start time with no ring in the window
    quiet = "exists p: Person: in_zone(p, door) and not eventually[0, 30] rings_bell(p)"
    assert matches(quiet, "visitor_no_ring") and matches(quiet, "visitor_rings")      # t >= 7 s is after the ring


# ------------------------------------------------------------------ hand-computed robustness values
@pytest.fixture
def bell():
    """frames at 0,1,2,3 s; rings_bell(p1): -, high, -, low."""
    return mk([(0, [("present", ("p1",), "low")]), (1000, [("rings_bell", ("p1",), "high")]),
               (2000, []), (3000, [("rings_bell", ("p1",), "low")])], entities=(("p1", "person"),))


B = {"p": "p1"}
RB = Atom(pred="rings_bell", args=("p",))


def series(text, tr, binding=B):
    return rho(parse(f"exists p: Person, k: Package: {text}").body, tr, binding).tolist()


def test_atom_and_boolean_connectives(bell):
    n, hi, lo = -0.45, 0.45, 0.1
    assert series("rings_bell(p)", bell) == pytest.approx([n, hi, n, lo])
    assert series("not rings_bell(p)", bell) == pytest.approx([-n, -hi, -n, -lo])
    # present(p1) is asserted (low) at frame 0 and implied by the rings_bell facts at frames 1 (high) and 3 (low)
    assert series("present(p)", bell) == pytest.approx([lo, hi, n, lo])
    assert series("rings_bell(p) and present(p)", bell) == pytest.approx([n, hi, n, lo])
    assert series("rings_bell(p) or present(p)", bell) == pytest.approx([lo, hi, n, lo])
    assert series("rings_bell(p) and not present(p)", bell) == pytest.approx([n, -hi, n, -lo])


def test_eventually_and_always_windows(bell):
    n, hi, lo = -0.45, 0.45, 0.1
    assert series("eventually[0, 1] rings_bell(p)", bell) == pytest.approx([hi, hi, lo, lo])
    assert series("always[0, 1] rings_bell(p)", bell) == pytest.approx([n, n, n, lo])
    assert series("eventually[1, 1] rings_bell(p)", bell) == pytest.approx([hi, n, lo, -C])
    assert series("always[1, 2] rings_bell(p)", bell) == pytest.approx([n, n, lo, -C])
    assert series("eventually[0.5, 0.9] rings_bell(p)", bell) == pytest.approx([-C] * 4)        # no frame in window
    assert series("always[0.5, 0.9] rings_bell(p)", bell) == pytest.approx([-C] * 4)            # non-vacuous
    assert series("eventually[0, 100] rings_bell(p)", bell) == pytest.approx([hi, hi, lo, lo])


def test_then_and_holds_for(bell):
    n, hi, lo = -0.45, 0.45, 0.1
    # present(p1): [lo, hi, n, lo] (see above).  inner[i] = min(present[i], max rings_bell over [i+1, i+2]);
    # the result at t is the max of inner over t1 >= t.
    pres = [lo, hi, n, lo]
    inner = [min(pres[0], max(hi, n)), min(pres[1], max(n, lo)), min(pres[2], lo), min(pres[3], -C)]
    assert inner == [lo, lo, n, -C]
    assert series("present(p) then[1, 2] rings_bell(p)", bell) == pytest.approx([lo, lo, n, -C])
    # holds_for >= 1 present(p): windows [t1, t1+1]
    #   t1=0: min(0.1, 0.45)=0.1; t1=1: min(0.45,-0.45)=-0.45; t1=2: min(-0.45, 0.45)=-0.45; t1=3 invalid (-C)
    assert series("holds_for >= 1 present(p)", bell) == pytest.approx([0.1, -0.45, -0.45, -C])
    assert series("holds_for >= 0 present(p)", bell) == pytest.approx([hi, hi, lo, lo])      # = max over t1 >= t
    assert series("holds_for >= 5 present(p)", bell) == pytest.approx([-C] * 4)                # longer than the clip


# ------------------------------------------------------------------ integer-ms window boundaries
def test_window_membership_is_exact_at_the_boundary_in_integer_ms():
    # 0.3 - 0.1 >= 0.2 is False in float seconds; offsets here come from integer ms, so Delta == 0.2 matches.
    tr = mk([(100, [("picks_up", ("p1", "k1"), "high")]), (300, [("leaves", ("p1", "porch"), "high")])])
    for a, b, ok in [(0.2, 0.2, True), (0.2, 1, True), (0, 0.2, True), (0.201, 1, False), (0, 0.199, False),
                     (0.1, 0.3, True)]:
        r = R(f"exists p: Person, k: Package: picks_up(p, k) then[{a}, {b}] leaves(p, porch)")
        assert (robustness(r, tr) > 0) == ok == evaluate_bool(r, tr), (a, b)
    assert (300 - 100) / 1000 >= 0.2 and not (0.3 - 0.1 >= 0.2)       # the pitfall being avoided


def test_non_dyadic_gaps_match_decimal_bounds():
    # frames 0.7 s apart: 1400/1000 == 1.4 and 2100/1000 == 2.1 exactly as the literals 1.4 / 2.1
    tr = mk([(0, [("rings_bell", ("p1",), "high")]), (700, []), (1400, [("rings_bell", ("p1",), "high")]),
             (2100, [])], entities=(("p1", "person"),))
    for text, ok in [("eventually[1.4, 1.4]", True), ("eventually[1.39, 1.399]", False), ("always[2.1, 2.1]", False)]:
        r = R(f"exists p: Person: {text} rings_bell(p)")
        assert (robustness(r, tr) > 0) == ok == evaluate_bool(r, tr), text


def test_holds_for_needs_clip_long_enough():
    tr = mk([(0, [("present", ("p1",), "high")]), (1000, [("present", ("p1",), "high")]),
             (2000, [("present", ("p1",), "high")])], entities=(("p1", "person"),))
    for d, ok in [(0, True), (1, True), (2, True), (2.0001, False), (3, False)]:
        r = R(f"exists p: Person: holds_for >= {d} present(p)")
        assert (robustness(r, tr) > 0) == ok == evaluate_bool(r, tr), d


def test_single_frame_trace():
    tr = mk([(500, [("present", ("p1",), "high")])], entities=(("p1", "person"),))
    assert score_and_bool("exists p: Person: present(p)", tr) == (approx(0.45), True)
    assert score_and_bool("exists p: Person: eventually[0, 0] present(p)", tr) == (approx(0.45), True)
    assert score_and_bool("exists p: Person: eventually[1, 2] present(p)", tr)[0] == -C
    assert score_and_bool("exists p: Person: holds_for >= 0 present(p)", tr) == (approx(0.45), True)
    assert score_and_bool("exists p: Person: holds_for >= 1 present(p)", tr) == (-C, False)


# ------------------------------------------------------------------ empty windows, bindings, failures
def test_empty_windows_follow_the_documented_convention(bell):
    # always over an empty window is -C, not vacuously true; its negation is therefore +C
    s, b = score_and_bool("exists p: Person: always[10, 20] rings_bell(p)", bell)
    assert (s, b) == (-C, False)
    s, b = score_and_bool("exists p: Person: not always[10, 20] rings_bell(p)", bell)
    assert (s, b) == (C, True)
    s, b = score_and_bool("exists p: Person: not eventually[10, 20] rings_bell(p)", bell)
    assert (s, b) == (C, True)


def test_no_bindings_failed_and_empty_traces():
    r = R("exists v: Vehicle: present(v)")
    assert robustness(r, load("theft_a")) == -C and not evaluate_bool(r, load("theft_a"))
    r = R("exists p: Person: present(p)")
    assert robustness(r, load("perception_failed")) == -C and not evaluate_bool(r, load("perception_failed"))
    assert robustness(r, load("empty_scene")) == -C
    zero = Trace(clip_id="z", source="fixture", duration_ms=1000, entities=(Entity(id="p1", type="person"),))
    assert robustness(r, zero) == -C and not evaluate_bool(r, zero)
    assert rho(r.body, zero, B).shape == (0,)


def test_best_binding_wins_and_distinct_entities_are_required():
    tr = mk([(0, [("in_zone", ("p2", "door"), "high")]), (1000, [("in_zone", ("p1", "door"), "low")])],
            entities=(("p1", "person"), ("p2", "person")))
    assert robustness(R("exists p: Person: in_zone(p, door)"), tr) == approx(0.45)           # p2 at 0 s
    # two Person variables must bind two different entities
    two = R("exists p: Person, q: Person: in_zone(p, door) and in_zone(q, door)")
    assert robustness(two, tr) == approx(-0.45)          # p2 high & p1 low never overlap in a frame, min over t...
    same = mk([(0, [("in_zone", ("p1", "door"), "high")])], entities=(("p1", "person"),))
    assert robustness(two, same) == -C                    # a single person cannot fill both variables


# ------------------------------------------------------------------ context atoms
@pytest.mark.parametrize("ctx,hour,ok", [
    ("hour in [6, 22]", 6, True), ("hour in [6, 22]", 22, True), ("hour in [6, 22]", 5, False),
    ("hour in [6, 22]", 23, False), ("hour in [22, 6]", 23, True), ("hour in [22, 6]", 0, True),
    ("hour in [22, 6]", 6, True), ("hour in [22, 6]", 22, True), ("hour in [22, 6]", 12, False),
    ("hour in [9, 9]", 9, True), ("hour in [9, 9]", 10, False), ("hour in [0, 23]", 0, True),
    ("hour in [0, 23]", None, False),                      # missing context -> the atom is false
])
def test_hour_context(ctx, hour, ok):
    tr = mk([(0, [("present", ("p1",), "high")])], entities=(("p1", "person"),), local_hour=hour)
    s, b = score_and_bool(f"exists p: Person: present(p) when {ctx}", tr)
    assert b == ok and (s > 0) == ok
    assert s == (approx(0.45) if ok else -C)


def test_subtype_device_and_conjunction_of_context():
    tr = mk([(0, [("present", ("p1",), "high")])], entities=(("p1", "person"),), sub_type="human", device_id="d1",
            local_hour=10)
    ok = lambda ctx: score_and_bool(f"exists p: Person: present(p) when {ctx}", tr)[1]
    assert ok("subtype = human") and not ok("subtype = vehicle") and ok("device = d1") and not ok("device = d2")
    assert ok("subtype = human and device = d1 and hour in [9, 11]")
    assert not ok("subtype = human and device = d2 and hour in [9, 11]")
    bare = mk([(0, [("present", ("p1",), "high")])], entities=(("p1", "person"),))
    assert not score_and_bool("exists p: Person: present(p) when subtype = human", bare)[1]
    assert not score_and_bool("exists p: Person: present(p) when device = d1", bare)[1]


def test_false_context_caps_score_at_minus_c_not_below_it():
    tr = mk([(0, [("present", ("p1",), "high")])], entities=(("p1", "person"),), local_hour=3)
    assert robustness(R("exists p: Person: not present(p) when hour in [6, 7]"), tr) == -C


# ------------------------------------------------------------------ holes
def test_holes_raise_unless_filled():
    sketch = R("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch) when hour in [?h1, 22]")
    tr = load("theft_a")
    for fn in (robustness, evaluate_bool, evaluate):
        with pytest.raises(UnboundHoleError) as ei:
            fn(sketch, tr)
        assert ei.value.names == ["a", "b", "h1"]
    with pytest.raises(UnboundHoleError):
        robustness(sketch, tr, {"a": 0, "b": 5})                      # h1 missing
    with pytest.raises(UnboundHoleError):
        rho(sketch.body, tr, {"p": "p1", "k": "k1"})
    with pytest.raises(UnboundHoleError):
        compile_rule(sketch).score(tr, {"a": 0})


def test_evaluate_with_holes_equals_fill_holes_first():
    sketch = R("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch) when hour in [?h1, 22]")
    tr = load("theft_a")                                              # local_hour = 14
    for vals in [{"a": 0, "b": 10, "h1": 6}, {"a": 5, "b": 10, "h1": 6.4}, {"a": 0, "b": 10, "h1": 15},
                 {"a": 0, "b": 3.9, "h1": 14.4}, {"a": 0.0, "b": 4.0, "h1": 13.6}]:
        closed = fill_holes(sketch, vals)
        want = robustness(closed, tr)
        assert evaluate(sketch, tr, vals) == want == compile_rule(sketch).score(tr, vals)
        assert evaluate_bool(sketch, tr, vals) == (want > 0)
    assert evaluate(sketch, tr, {"a": 0, "b": 4, "h1": 13.6}) == approx(0.45)         # hole 13.6 rounds to hour 14
    assert evaluate(sketch, tr, {"a": 0, "b": 4, "h1": 14.4}) == approx(0.45)         # 14.4 -> 14
    assert evaluate(sketch, tr, {"a": 0, "b": 4, "h1": 14.6}) == -C                   # 14.6 -> 15 > 14


def test_extra_hole_values_are_ignored_and_input_not_mutated():
    sketch = R("exists p: Person: eventually[0, ?b] present(p)")
    before = sketch.model_dump()
    assert evaluate(sketch, load("theft_a"), {"b": 5, "unused": 1}) > 0
    assert sketch.model_dump() == before


# ------------------------------------------------------------------ consistency on every fixture
BATTERY = [
    THEFT, DWELL, UNATTENDED,
    "exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)",
    "exists p: Person, k: Carryable: (carrying(p, k) or near(p, k)) then[0, 6] leaves(p, porch)",
    "exists p: Person: always[0, 6] (present(p) or facing_camera(p)) when hour in [6, 22]",
    "exists e: Entity: holds_for >= 6 (in_zone(e, yard) or in_zone(e, street))",
    "exists a: Animal: eventually[0, 10] in_zone(a, yard) and not present(a)",
    "exists v: Vehicle, p: Person: near(p, v) then[0, 30] holds_for >= 1 present(v)",
    "exists p: Person: not (present(p) then[0, 3] present(p)) when subtype = human",
]


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_all_evaluators_agree_on_fixtures(name):
    tr = load(name)
    for text in BATTERY:
        r = R(text)
        s = robustness(r, tr)
        assert s == ref_score(r, tr), (name, text)
        assert -C <= s <= C
        assert evaluate_bool(r, tr) == (s > 0), (name, text, s)


def test_prepared_trace_is_reusable_and_robust_to_identity_reuse():
    tr = load("theft_a")
    p = prepare(tr)
    assert prepare(tr) is p and prepare(p) is p
    r = R(THEFT)
    assert robustness(r, p) == robustness(r, tr)
    # the pairwise offsets come from integer ms with one division
    assert p.D[1, 3] == (tr.frames[3].t_ms - tr.frames[1].t_ms) / 1000
    assert np.array_equal(p.t_ms, tr.t_ms)


# ------------------------------------------------------------------ agreement with the Phase 0 spike evaluator
def test_then_agrees_with_the_phase0_spike_evaluator():
    """scripts/spikes/z3_then.py::rho_then is the NumPy evaluator that agreed with Z3 in spike 6."""
    import importlib.util
    import random
    from pathlib import Path

    path = Path(__file__).parents[3] / "scripts" / "spikes" / "z3_then.py"
    if not path.exists():
        pytest.skip("spike script not present")
    spec = importlib.util.spec_from_file_location("z3_then_spike", path)
    spike = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(spike)
    from exemplar.contracts.dsl_ast import Then
    rnd = random.Random(7)
    for _ in range(60):
        n = rnd.randint(1, 20)
        ts = sorted(rnd.sample(range(0, 30000, 100), n))
        frames = [(t, [x for x in [("picks_up", ("p1", "k1"), rnd.choice(["low", "med", "high"])) if rnd.random() < .3 else None,
                                   ("leaves", ("p1", "porch"), rnd.choice(["low", "med", "high"])) if rnd.random() < .3 else None]
                       if x]) for t in ts]
        tr = mk(frames)
        a = rnd.choice([0, 0.5, 1, 2.5, 4]); b = a + rnd.choice([0, 1, 3.3, 8, 40])
        phi = np.array(rho(Atom(pred="picks_up", args=("p", "k")), tr, {"p": "p1", "k": "k1"}))
        psi = np.array(rho(Atom(pred="leaves", args=("p", "porch")), tr, {"p": "p1", "k": "k1"}))
        want = spike.rho_then(phi, psi, tr.t_ms, a, b)
        node = Then(a=float(a), b=float(b), left=Atom(pred="picks_up", args=("p", "k")),
                    right=Atom(pred="leaves", args=("p", "porch")))
        got = rho(node, tr, {"p": "p1", "k": "k1"})
        assert np.array_equal(got, want), (ts, a, b)
