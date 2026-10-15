"""build_committee: consistent members, box handling, fallback, weights, determinism (offline, fake synth)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from active_helpers import (EVENTUALLY_SKETCH, THEN_SKETCH, Candidate, GridBox, candidate, example, gap_trace, load)
from exemplar.active import Committee, build_committee
from exemplar.contracts.dsl_ast import HourIn
from exemplar.dsl import parse, robustness, to_text

THEFT_A = load("theft_a")           # positive: picks_up (6 s) then carrying (8 s): gap 2 s
DELIVERY_A = load("delivery_a")     # negative: no picks_up at all


def examples(*extra):
    return [example(THEFT_A, True), example(DELIVERY_A, False), *extra]


def b_values(committee: Committee):
    out = []
    for rule, _ in committee.members:
        then = rule.body.args[0]
        out.append(then.b)
    return np.array(out)


def test_members_are_closed_consistent_with_the_examples_and_weights_sum_to_one():
    cand = candidate(THEN_SKETCH, {"b": 3.0})
    box = GridBox()
    com = build_committee([cand], examples(), box_fn=box, n_samples=200, seed=1)
    assert box.calls == [{"satisfied": ("theft_a", "delivery_a"), "margin": 0.45}]
    assert len(com) == 201                                            # the candidate's own point + 200 samples
    assert sum(w for _, w in com.members) == pytest.approx(1.0)
    for rule, w in com.members:
        assert w > 0 and to_text(rule).count("?") == 0               # closed
        assert robustness(rule, THEFT_A) > 0 and robustness(rule, DELIVERY_A) <= 0
    b = b_values(com)
    assert b.min() >= 2.0 - 1e-9 and b.max() <= 24.0                  # inside the feasible box [2, 24]
    assert 11 < b.mean() < 15                                         # uniform over it
    assert (b == 3.0).sum() >= 1                                      # the candidate itself is a member
    d = com.diagnostics[0]
    assert d["acceptance"] == 1.0 and d["fallback"] is False and d["box"] == {"b": (2.0, 24.0)}


def test_a_negative_example_caps_the_version_space():
    cap = example(gap_trace("neg_gap12", 12.0), False)               # matches iff b >= 12, so b must stay below
    box = GridBox()
    com = build_committee([candidate(THEN_SKETCH, {"b": 3.0})], examples(cap), box_fn=box, n_samples=200, seed=2)
    assert box.calls[0]["satisfied"] == ("theft_a", "delivery_a", "neg_gap12")
    b = b_values(com)
    assert b.min() >= 2.0 - 1e-9 and b.max() < 12.0
    for rule, _ in com.members:
        assert robustness(rule, cap.trace) <= 0


def test_violated_examples_are_not_part_of_the_constraints():
    cap = example(gap_trace("neg_gap12", 12.0), False)
    cand = candidate(THEN_SKETCH, {"b": 3.0}, violated=("neg_gap12",))      # "perception suspect": ignore it
    box = GridBox()
    com = build_committee([cand], examples(cap), box_fn=box, n_samples=100, seed=2)
    assert box.calls[0]["satisfied"] == ("theft_a", "delivery_a")
    assert b_values(com).max() > 12.0
    assert com.diagnostics[0]["n_satisfied"] == 2


def test_box_margin_override_is_passed_to_box_fn():
    box = GridBox()
    build_committee([candidate(THEN_SKETCH, {"b": 3.0}, margin=0.3)], examples(), box_fn=box, n_samples=5)
    build_committee([candidate(THEN_SKETCH, {"b": 3.0}, margin=0.3)], examples(), box_fn=box, n_samples=5, box_margin=0.0)
    assert [c["margin"] for c in box.calls] == [0.3, 0.0]


def test_deterministic_for_a_seed_and_different_across_seeds():
    cand = candidate(THEN_SKETCH, {"b": 3.0})
    a = build_committee([cand], examples(), box_fn=GridBox(), n_samples=50, seed=7)
    b = build_committee([cand], examples(), box_fn=GridBox(), n_samples=50, seed=7)
    c = build_committee([cand], examples(), box_fn=GridBox(), n_samples=50, seed=8)
    assert a.members == b.members
    assert not np.array_equal(b_values(a), b_values(c))


def test_a_candidate_keeps_its_samples_when_another_is_added():
    c1 = candidate(THEN_SKETCH, {"b": 3.0})
    c2 = candidate(EVENTUALLY_SKETCH, {"b": 9.0}, mdl=22.0)
    one = build_committee([c1], examples(), box_fn=GridBox(), n_samples=30, seed=3)
    two = build_committee([c1, c2], examples(), box_fn=GridBox(), n_samples=30, seed=3)
    first = [r for r, _ in two.members if "then" in to_text(r)]
    assert first == [r for r, _ in one.members]


# ------------------------------------------------------------------------------------------ weights
def split_weights(com: Committee):
    then = sum(w for r, w in com.members if "then" in to_text(r))
    ev = sum(w for r, w in com.members if "then" not in to_text(r))
    return then, ev


def test_weights_follow_exp_minus_mdl_per_candidate():
    c1 = candidate(THEN_SKETCH, {"b": 3.0}, mdl=20.0)
    c2 = candidate(EVENTUALLY_SKETCH, {"b": 9.0}, mdl=22.0)
    com = build_committee([c1, c2], examples(), box_fn=GridBox(), n_samples=40, seed=0)
    then, ev = split_weights(com)
    assert then + ev == pytest.approx(1.0)
    assert ev / then == pytest.approx(math.exp(-2.0), rel=1e-9)
    # inside a candidate the weight is spread evenly over its accepted points
    ws = {w for r, w in com.members if "then" in to_text(r)}
    assert len(ws) == 1


def test_temperature_flattens_the_weights():
    c1 = candidate(THEN_SKETCH, {"b": 3.0}, mdl=20.0)
    c2 = candidate(EVENTUALLY_SKETCH, {"b": 9.0}, mdl=30.0)
    sharp = split_weights(build_committee([c1, c2], examples(), box_fn=GridBox(), n_samples=20))
    flat = split_weights(build_committee([c1, c2], examples(), box_fn=GridBox(), n_samples=20, mdl_temperature=10.0))
    assert sharp[1] / sharp[0] == pytest.approx(math.exp(-10), rel=1e-9)
    assert flat[1] / flat[0] == pytest.approx(math.exp(-1), rel=1e-9)


@pytest.mark.parametrize("base", [1e5, 700.0, 0.0, -50.0])
def test_weights_are_numerically_stable_for_any_mdl_scale(base):
    c1 = candidate(THEN_SKETCH, {"b": 3.0}, mdl=base)
    c2 = candidate(EVENTUALLY_SKETCH, {"b": 9.0}, mdl=base + 3.0)
    com = build_committee([c1, c2], examples(), box_fn=GridBox(), n_samples=10)
    ws = [w for _, w in com.members]
    assert all(np.isfinite(ws)) and sum(ws) == pytest.approx(1.0)
    then, ev = split_weights(com)
    assert ev / then == pytest.approx(math.exp(-3.0), rel=1e-9)


def test_non_finite_mdl_is_rejected():
    with pytest.raises(ValueError):
        build_committee([candidate(THEN_SKETCH, {"b": 3.0}, mdl=float("inf"))], examples(), box_fn=GridBox(), n_samples=5)


# ------------------------------------------------------------------------------------------ fallback and edge cases
def test_low_acceptance_falls_back_to_a_box_shrunk_around_the_candidate():
    def wide_box(sketch, exs, *, satisfied, margin, timeout_s=10.0):
        return {"b": (0.0, 1000.0)}                                # feasible region is [2, 1000]... but only <=24 is real

    # make the true region small: a negative that matches for every b >= 30 caps b < 30
    cap = example(gap_trace("neg_gap30", 30.0), False)
    com = build_committee([candidate(THEN_SKETCH, {"b": 3.0})], examples(cap), box_fn=wide_box, n_samples=200, seed=4)
    d = com.diagnostics[0]
    assert d["acceptance"] < 0.05 and d["fallback"] is True and d["fallback_accepted"] > 0
    assert d["n_sampled"] == 400
    b = b_values(com)
    assert len(com) == 1 + d["n_accepted"] and d["n_accepted"] >= d["fallback_accepted"]
    assert b.min() >= 2.0 and b.max() < 30.0                      # every member is still consistent
    for rule, _ in com.members:
        assert robustness(rule, THEFT_A) > 0 and robustness(rule, cap.trace) <= 0


def test_no_fallback_when_acceptance_is_high():
    com = build_committee([candidate(THEN_SKETCH, {"b": 3.0})], examples(), box_fn=GridBox(), n_samples=50)
    assert com.diagnostics[0]["fallback"] is False and "fallback_accepted" not in com.diagnostics[0]


def test_closed_candidate_without_holes_is_a_single_member():
    closed = "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)"
    cand = candidate(closed, {})
    com = build_committee([cand], examples(), box_fn=lambda *a, **k: pytest.fail("no holes, no box"), n_samples=50)
    assert len(com) == 1 and com.members[0][1] == pytest.approx(1.0) and com.members[0][0] == parse(closed)


def test_box_failure_degrades_to_the_candidates_own_point():
    def boom(*a, **k):
        raise TimeoutError("z3 timed out")

    com = build_committee([candidate(THEN_SKETCH, {"b": 3.0})], examples(), box_fn=boom, n_samples=20)
    assert "TimeoutError" in com.diagnostics[0]["box_error"]
    assert len(com) >= 1 and set(b_values(com)) == {3.0}


def test_an_inconsistent_candidate_is_kept_and_flagged():
    cand = candidate(THEN_SKETCH, {"b": 1.0})                      # b = 1 does not match theft_a (gap 2)
    com = build_committee([cand], examples(), box_fn=lambda *a, **k: {"b": (0.0, 1.5)}, n_samples=20)
    assert com.diagnostics[0]["inconsistent_candidate"] is True and len(com) == 1


def test_no_candidates_gives_an_empty_committee():
    com = build_committee([], examples(), box_fn=GridBox())
    assert len(com) == 0 and com.members == ()


def test_bad_arguments():
    with pytest.raises(ValueError):
        build_committee([], [], box_fn=GridBox(), n_samples=0)
    with pytest.raises(ValueError):
        build_committee([], [], box_fn=GridBox(), mdl_temperature=0)


def test_sketch_comes_from_sketch_text_not_from_the_closed_rule():
    cand = candidate(THEN_SKETCH, {"b": 3.0})
    assert "?" not in to_text(cand.rule)                           # candidate.rule is closed
    com = build_committee([cand], examples(), box_fn=GridBox(), n_samples=40, seed=9)
    assert len(set(b_values(com))) > 10


def test_hour_holes_are_sampled_as_integers():
    sketch = "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) when hour in [?h1, ?h2]"
    cand = candidate(sketch, {"h1": 12.0, "h2": 16.0})              # theft_a is at hour 14

    def box(sk, exs, *, satisfied, margin, timeout_s=10.0):
        return {"h1": (9.5, 14.0), "h2": (14.0, 20.5)}

    com = build_committee([cand], examples(), box_fn=box, n_samples=100, seed=5)
    assert len(com) > 50
    h1s, h2s = set(), set()
    for rule, _ in com.members:
        (ctx,) = rule.when
        assert isinstance(ctx, HourIn) and isinstance(ctx.h1, int) and isinstance(ctx.h2, int)
        assert 10 <= ctx.h1 <= 14 and 14 <= ctx.h2 <= 20
        h1s.add(ctx.h1), h2s.add(ctx.h2)
        assert robustness(rule, THEFT_A) > 0
    assert len(h1s) >= 4 and len(h2s) >= 5


def test_default_box_fn_is_exemplar_synth_hole_box(monkeypatch):
    import exemplar.synth
    box = GridBox()
    monkeypatch.setattr(exemplar.synth, "hole_box", box, raising=False)
    build_committee([candidate(THEN_SKETCH, {"b": 3.0})], examples(), n_samples=5)
    assert len(box.calls) == 1


def test_prepared_traces_are_accepted_as_example_traces():
    from exemplar.dsl import prepare
    exs = [example(prepare(THEFT_A), True), example(prepare(DELIVERY_A), False)]
    com = build_committee([candidate(THEN_SKETCH, {"b": 3.0})], exs, box_fn=GridBox(), n_samples=10)
    assert len(com) == 11
