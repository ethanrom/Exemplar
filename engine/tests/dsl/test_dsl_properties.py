"""Property tests for the evaluators. Strategies live in dsl_strategies.py."""
from __future__ import annotations

import os

import numpy as np
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from dsl_reference import ref_score, ref_series
from dsl_strategies import formula_and_trace, rule_and_trace, rules, traces
from exemplar.contracts.dsl_ast import Always, Atom, Eventually, Not, Rule, Then, fill_holes, holes
from exemplar.contracts.ontology import CLAMP
from exemplar.dsl import (compile_rule, evaluate, evaluate_bool, parse, prepare, rho, robustness, to_english, to_text,
                          truth_series, typecheck, witness)

# DSL_PROP_SCALE=10 runs ten times as many examples (use it before changing the evaluator).
_SCALE = float(os.environ.get("DSL_PROP_SCALE", "1"))
_HC = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]
KEY = settings(max_examples=int(150 * _SCALE), deadline=None, suppress_health_check=_HC)    # the four required properties
SETTINGS = settings(max_examples=int(60 * _SCALE), deadline=None, suppress_health_check=_HC)
C = CLAMP


# ------------------------------------------------------------------ the four required properties
@KEY
@given(rule_and_trace())
def test_sign_of_robustness_agrees_with_boolean(rt):
    rule, tr = rt
    assert not typecheck(rule), typecheck(rule)
    r = robustness(rule, tr)
    if r != 0:
        assert (r > 0) == evaluate_bool(rule, tr), (to_text(rule), r)


@KEY
@given(formula_and_trace())
def test_sign_agrees_pointwise_for_every_subformula(ft):
    phi, tr, binding = ft
    r = rho(phi, tr, binding)
    b = truth_series(phi, tr, binding)
    assert len(r) == len(b) == len(tr.frames)
    for ri, bi in zip(r, b):
        if ri != 0:
            assert (ri > 0) == bi


@KEY
@given(formula_and_trace())
def test_negation_duality(ft):
    phi, tr, binding = ft
    pos = rho(phi, tr, binding)
    assert np.array_equal(rho(Not(arg=phi), tr, binding), -pos)
    assert np.array_equal(rho(Not(arg=Not(arg=phi)), tr, binding), pos)


def _widen(draw_pair):
    a, b, da, db = draw_pair
    return a, b, max(0.0, a - da), b + db


widen = st.tuples(st.sampled_from([0.0, 0.5, 1.0, 2.5, 4.0]), st.sampled_from([0.0, 1.0, 3.0, 6.0, 12.0]),
                  st.sampled_from([0.0, 0.5, 2.0, 5.0]), st.sampled_from([0.0, 1.0, 4.0, 30.0])).map(_widen)


@KEY
@given(formula_and_trace(), widen)
def test_widening_eventually_never_decreases_rho(ft, w):
    phi, tr, binding = ft
    a, b, a2, b2 = w
    assume(a <= b)
    narrow = rho(Eventually(a=a, b=b, arg=phi), tr, binding)
    wide = rho(Eventually(a=a2, b=b2, arg=phi), tr, binding)
    assert (wide >= narrow).all()


@KEY
@given(formula_and_trace(), widen)
def test_widening_always_never_increases_rho(ft, w):
    phi, tr, binding = ft
    a, b, a2, b2 = w
    assume(a <= b)
    narrow = rho(Always(a=a, b=b, arg=phi), tr, binding)
    wide = rho(Always(a=a2, b=b2, arg=phi), tr, binding)
    # Where the narrow window holds no frame, rho is -C by convention (deliberately non-vacuous), and a
    # wider window that does contain frames may legitimately be higher. Monotonicity holds elsewhere.
    prep = prepare(tr)
    _, nonempty = prep.window(a, b)
    assert (wide[nonempty] <= narrow[nonempty]).all()


@SETTINGS
@given(formula_and_trace(), widen)
def test_widening_then_window_never_decreases_rho(ft, w):
    phi, tr, binding = ft
    a, b, a2, b2 = w
    assume(a <= b)
    psi = Atom(pred="present", args=("y",))
    narrow = rho(Then(a=a, b=b, left=phi, right=psi), tr, binding)
    wide = rho(Then(a=a2, b=b2, left=phi, right=psi), tr, binding)
    assert (wide >= narrow).all()


def test_always_widening_exception_is_the_empty_window_convention():
    """Documented non-monotone corner: an empty always-window is -C, a wider non-empty one can be higher."""
    from dsl_helpers import load
    tr = load("unattended_package")                    # frames every 3 s, package on the steps throughout
    phi = Atom(pred="in_zone", args=("k", "steps"))
    narrow = rho(Always(a=1.0, b=2.0, arg=phi), tr, {"k": "k1"})      # no frame 1..2 s ahead -> -C
    wide = rho(Always(a=0.0, b=3.0, arg=phi), tr, {"k": "k1"})
    assert (narrow == -C).all() and (wide > narrow).all()


# ------------------------------------------------------------------ printer / parser / typechecker
@SETTINGS
@given(rules(holes=True))
def test_parse_to_text_roundtrip(rule):
    text = to_text(rule)
    assert parse(text) == rule, text
    assert to_text(parse(text)) == text


@SETTINGS
@given(rules(holes=True))
def test_typecheck_accepts_generated_rules(rule):
    assert typecheck(rule) == []


@SETTINGS
@given(rules(holes=True))
def test_english_is_total_and_deterministic(rule):
    s = to_english(rule)
    assert s == to_english(parse(to_text(rule))) and s.startswith("There is ") and s.endswith(".")


# ------------------------------------------------------------------ evaluator cross-checks
@KEY
@given(formula_and_trace())
def test_vectorised_rho_equals_reference_semantics(ft):
    phi, tr, binding = ft
    got = rho(phi, tr, binding)
    want = np.array(ref_series(phi, tr, binding))
    assert np.array_equal(got, want), (to_text(phi), got, want)


@SETTINGS
@given(rule_and_trace())
def test_robustness_equals_reference_and_is_clamped(rt):
    rule, tr = rt
    r = robustness(rule, tr)
    assert r == ref_score(rule, tr)
    assert -C <= r <= C


@SETTINGS
@given(rule_and_trace(holes=True), st.data())
def test_hole_filling_paths_agree(rt, data):
    rule, tr = rt
    names = holes(rule)
    vals = {n: data.draw(st.sampled_from([0.0, 0.5, 1.0, 3.0, 7.5, 20.0, 11.0, 23.0])) for n in names}
    closed = fill_holes(rule, vals)
    assert holes(closed) == []
    base = robustness(closed, tr)
    assert evaluate(rule, tr, vals) == base
    assert compile_rule(rule).score(tr, vals) == base
    assert compile_rule(closed).score(prepare(tr)) == base
    if base != 0:
        assert evaluate_bool(rule, tr, vals) == (base > 0)


@SETTINGS
@given(traces(), st.data())
def test_signal_index_matches_trace_signal(tr, data):
    prep = prepare(tr)
    from dsl_strategies import _candidate_facts
    cands = _candidate_facts(list(tr.entities)) + [("present", (e.id,)) for e in tr.entities] \
        + [("attr", (e.id, "hoodie")) for e in tr.entities] + [("in_zone", ("k1", "door")), ("near", ("p1", "p1"))]
    for pred, args in cands:
        assert np.array_equal(prep.signal(pred, args), tr.signal(pred, args)), (pred, args)


def node_at(rule: Rule, path: str):
    """Resolve an AST path such as 'body.args[1].left' to the node."""
    node = rule
    for part in path.split("."):
        name, _, idx = part.partition("[")
        node = getattr(node, name)
        if idx:
            node = node[int(idx.rstrip("]"))]
    return node


@SETTINGS
@given(rule_and_trace(context=True))
def test_witness_is_consistent_with_score(rt):
    rule, tr = rt
    w = witness(rule, tr)
    assert w["score"] == robustness(rule, tr)
    assert w["clip_id"] == tr.clip_id
    assert w == witness(rule, tr)                        # deterministic
    prep = prepare(tr)
    times = prep.t_ms.tolist()
    if not w["bindings"]:
        assert w["spans"] == []
        return
    assert set(w["bindings"]) == {v.name for v in rule.vars}
    assert tuple(w["bindings"].values()) in tr.bindings(tuple(v.type for v in rule.vars))
    body = rho(rule.body, tr, w["bindings"])
    for sp in w["spans"]:
        assert sp["t_start_ms"] in times and sp["t_end_ms"] in times and sp["t_start_ms"] <= sp["t_end_ms"]
        node = node_at(rule, sp["path"])
        assert sp["op"] == node.op and sp["text"] == to_text(node)
        series = rho(node, tr, w["bindings"])
        assert sp["rho"] in series.tolist()               # a value this subformula really takes
        if sp["op"] == "atom":                            # atoms are evaluated exactly at their frame
            assert series[times.index(sp["t_start_ms"])] == sp["rho"]
    assert float(body.max()) >= min(w["score"], C) or w["score"] == -C   # score never exceeds the body's best
