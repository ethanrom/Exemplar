"""Witness extraction: argmax bindings, chosen times per temporal operator, determinism, api.yaml shape."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from dsl_helpers import ALL_FIXTURES, load
from exemplar.contracts.ontology import CLAMP
from exemplar.contracts.trace import Entity, Fact, Frame, Trace
from exemplar.dsl import UnboundHoleError, parse, robustness, typecheck, witness

C = CLAMP
API = Path(__file__).parents[2] / "exemplar" / "contracts" / "api.yaml"

THEFT = "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)"


def W(text, tr, holes=None):
    r = parse(text)
    assert typecheck(r) == [] or holes
    return witness(r, tr, holes)


def spans_by_path(w):
    return {s["path"]: s for s in w["spans"]}


def mk(frames, entities):
    fr = tuple(Frame(t_ms=t, facts=tuple(Fact(pred=p, args=tuple(a), conf=c) for p, a, c in fs)) for t, fs in frames)
    return Trace(clip_id="m", source="fixture", duration_ms=fr[-1].t_ms + 1000,
                 entities=tuple(Entity(id=i, type=t) for i, t in entities), frames=fr)


def test_theft_witness_on_theft_a():
    w = W(THEFT, load("theft_a"))
    assert w["clip_id"] == "theft_a" and w["bindings"] == {"p": "p1", "k": "k1"}
    assert w["score"] == pytest.approx(0.45)
    assert [e["id"] for e in w["entities"]] == ["p1", "k1"] and w["entities"][0]["attrs"] == ["hoodie"]
    sp = spans_by_path(w)
    assert [s["path"] for s in w["spans"]] == [
        "body", "body.args[0]", "body.args[0].left", "body.args[0].right", "body.args[1]"]
    # picks_up at 6 s; carrying chosen at 8 s (first of the best frames in [6, 16] s)
    assert (sp["body.args[0]"]["op"], sp["body.args[0]"]["t_start_ms"], sp["body.args[0]"]["t_end_ms"]) == ("then", 6000, 8000)
    assert (sp["body.args[0].left"]["t_start_ms"], sp["body.args[0].left"]["t_end_ms"]) == (6000, 6000)
    assert (sp["body.args[0].right"]["t_start_ms"], sp["body.args[0].right"]["t_end_ms"]) == (8000, 8000)
    assert sp["body.args[0].left"]["text"] == "picks_up(p, k)" and sp["body.args[0].right"]["text"] == "carrying(p, k)"
    assert sp["body.args[1]"]["op"] == "not" and sp["body.args[1]"]["text"] == "not attr(p, delivery_uniform)"
    assert sp["body.args[1]"]["rho"] == pytest.approx(0.45)
    assert sp["body"]["op"] == "and" and (sp["body"]["t_start_ms"], sp["body"]["t_end_ms"]) == (0, 8000)
    assert w["english"].startswith("There is a person p and a package k such that")
    json.dumps(w)                                                         # plain JSON types only


def test_dwell_witness_reports_the_run():
    w = W("exists v: Vehicle: holds_for >= 120 in_zone(v, dock)", load("vehicle_dwell_dock"))
    assert w["bindings"] == {"v": "v1"} and w["score"] == pytest.approx(0.45)
    top, leaf = w["spans"]
    assert (top["path"], top["op"], top["t_start_ms"], top["t_end_ms"]) == ("body", "holds_for", 6000, 126000)
    assert (leaf["path"], leaf["op"], leaf["t_start_ms"]) == ("body.arg", "atom", 6000)
    # a longer requirement has to include the med-confidence frame at 156 s, which becomes the weakest point
    w = W("exists v: Vehicle: holds_for >= 150 in_zone(v, dock)", load("vehicle_dwell_dock"))
    top, leaf = w["spans"]
    assert (top["t_start_ms"], top["t_end_ms"], leaf["t_start_ms"]) == (6000, 156000, 156000)
    assert top["rho"] == leaf["rho"] == pytest.approx(0.30)


def test_eventually_and_always_spans():
    tr = mk([(0, [("in_zone", ("p1", "door"), "low")]), (1000, [("in_zone", ("p1", "door"), "high")]),
             (2000, [("in_zone", ("p1", "door"), "high")]), (3000, [("in_zone", ("p1", "door"), "med")])],
            [("p1", "person")])
    w = W("exists p: Person: eventually[0, 3] in_zone(p, door)", tr)
    top, leaf = w["spans"]
    # the span is the window searched, [0, 3] s from the start frame; the atom is the earliest best frame
    assert (top["op"], top["t_start_ms"], top["t_end_ms"]) == ("eventually", 0, 3000)
    assert leaf["path"] == "body.arg" and leaf["rho"] == pytest.approx(0.45)
    assert (leaf["t_start_ms"], leaf["t_end_ms"]) == (1000, 1000)
    # the best start time is 1 s (window 1..4 s covers the high, high, med frames); starting at 0 s would
    # include the low frame. The window is clipped to the last frame (3 s); the weakest frame is the med one.
    w = W("exists p: Person: always[0, 3] in_zone(p, door)", tr)
    top, leaf = w["spans"]
    assert (top["op"], top["t_start_ms"], top["t_end_ms"], top["rho"]) == ("always", 1000, 3000, pytest.approx(0.30))
    assert leaf["t_start_ms"] == 3000 and leaf["rho"] == pytest.approx(0.30)
    assert w["score"] == pytest.approx(0.30)


def _steps_clip(times_ms, last_true_ms):
    """A package on the steps (high) in every frame up to ``last_true_ms``, absent in frames after it."""
    frames = [(t, [("in_zone", ("k1", "steps"), "high")] if t <= last_true_ms else []) for t in times_ms]
    return mk(frames, [("k1", "package")])


def test_holds_for_span_is_the_required_window_not_the_last_sampled_frame():
    # frames are 1.0, 5.0, 9.0, 13.9, 14.9 s true, then 20 s absent: the 15 s run from t1 = 1 s ends at 16 s,
    # but the last sampled frame inside the window is 14.9 s. The span must report [1.0, 16.0], not [1.0, 14.9].
    tr = _steps_clip([1000, 5000, 9000, 13900, 14900, 20000], last_true_ms=14900)
    w = W("exists k: Package: holds_for >= 15 in_zone(k, steps)", tr)
    top, leaf = w["spans"]
    assert w["score"] == pytest.approx(0.45)
    assert (top["op"], top["t_start_ms"], top["t_end_ms"]) == ("holds_for", 1000, 16000)
    assert top["t_end_ms"] - top["t_start_ms"] == 15000
    assert (leaf["op"], leaf["t_start_ms"], leaf["t_end_ms"]) == ("atom", 1000, 1000)   # atoms stay frame points
    # a hole is resolved before the span is built
    r = parse("exists k: Package: holds_for >= ?d in_zone(k, steps)")
    w = witness(r, tr, {"d": 15})
    assert (w["spans"][0]["t_start_ms"], w["spans"][0]["t_end_ms"]) == (1000, 16000)


def test_holds_for_span_is_clipped_to_the_clip_end():
    # a 10 s clip cannot hold a 15 s run: the rule does not match and the window is clipped to the last frame
    tr = _steps_clip([1000, 5000, 9000, 10000], last_true_ms=10000)
    w = W("exists k: Package: holds_for >= 15 in_zone(k, steps)", tr)
    top = w["spans"][0]
    assert w["score"] == -C
    assert (top["t_start_ms"], top["t_end_ms"]) == (1000, 10000)


def test_eventually_and_always_spans_are_the_evaluated_window_clipped_to_the_clip():
    tr = _steps_clip([500, 4000, 9000, 12500], last_true_ms=12500)
    w = W("exists k: Package: eventually[2, 6] in_zone(k, steps)", tr)
    top, leaf = w["spans"]
    # best start 0.5 s (earliest): window [2.5, 6.5] s holds the 4 s frame; the span is the window, not the frame
    assert (top["op"], top["t_start_ms"], top["t_end_ms"]) == ("eventually", 2500, 6500)
    assert (leaf["t_start_ms"], leaf["t_end_ms"]) == (4000, 4000)
    # the window runs past the end of the clip, so it is clipped at the last frame (12.5 s)
    w = W("exists k: Package: always[1, 100] in_zone(k, steps)", tr)
    top, leaf = w["spans"]
    assert (top["op"], top["t_start_ms"], top["t_end_ms"]) == ("always", 1500, 12500)
    assert leaf["op"] == "atom" and leaf["t_start_ms"] == leaf["t_end_ms"]
    # an empty window keeps the point span at the evaluation frame (nothing was evaluated)
    w = W("exists k: Package: eventually[50, 60] in_zone(k, steps)", tr)
    top = w["spans"][0]
    assert top["t_start_ms"] == top["t_end_ms"] and w["score"] == -C


def test_or_follows_the_best_branch_and_ties_take_the_first():
    tr = mk([(0, [("rings_bell", ("p1",), "high"), ("facing_camera", ("p1",), "high")])], [("p1", "person")])
    w = W("exists p: Person: facing_camera(p) or rings_bell(p)", tr)
    assert [s["path"] for s in w["spans"]] == ["body", "body.args[0]"]       # tie -> first branch
    tr2 = mk([(0, [("rings_bell", ("p1",), "high"), ("facing_camera", ("p1",), "low")])], [("p1", "person")])
    w = W("exists p: Person: facing_camera(p) or rings_bell(p)", tr2)
    assert [s["path"] for s in w["spans"]] == ["body", "body.args[1]"]


def test_first_binding_and_earliest_time_win_ties():
    tr = mk([(0, []), (1000, [("in_zone", ("p1", "door"), "high"), ("in_zone", ("p2", "door"), "high")]),
             (2000, [("in_zone", ("p1", "door"), "high"), ("in_zone", ("p2", "door"), "high")])],
            [("p1", "person"), ("p2", "person")])
    w = W("exists p: Person: in_zone(p, door)", tr)
    assert w["bindings"] == {"p": "p1"} and w["spans"][0]["t_start_ms"] == 1000
    assert w == W("exists p: Person: in_zone(p, door)", tr)


def test_witness_for_non_matching_clip_shows_closest_attempt():
    w = W(THEFT, load("delivery_a"))
    assert w["bindings"] == {"p": "p1", "k": "k1"} and w["score"] == pytest.approx(-0.45)
    assert w["spans"]                                                      # explanation of the best (still negative) try


def test_witness_with_nothing_to_bind_or_failed_trace():
    for name, text in [("perception_failed", "exists p: Person: present(p)"), ("theft_a", "exists v: Vehicle: present(v)"),
                       ("empty_scene", "exists p: Person: present(p)")]:
        w = W(text, load(name))
        assert (w["score"], w["bindings"], w["entities"], w["spans"]) == (-C, {}, [], [])
        assert w["english"].startswith("There is")


def test_false_context_gives_minus_c_score_but_still_a_witness():
    w = W("exists p: Person, k: Package: picks_up(p, k) when hour in [0, 3]", load("theft_a"))
    assert w["score"] == -C and w["bindings"] == {"p": "p1", "k": "k1"} and w["spans"]


def test_witness_with_holes_and_unfilled_holes():
    r = parse("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)")
    with pytest.raises(UnboundHoleError):
        witness(r, load("theft_a"))
    w = witness(r, load("theft_a"), {"b": 5})
    assert w["spans"][0]["text"] == "picks_up(p, k) then[0, 5] leaves(p, porch)"
    assert (w["spans"][0]["t_start_ms"], w["spans"][0]["t_end_ms"]) == (6000, 10000)
    assert "?b" not in w["english"] and "0 to 5 s" in w["english"]


def test_not_spans_are_point_spans_with_positive_robustness_of_absence():
    w = W("exists p: Person: present(p) and not eventually[0, 30] rings_bell(p)", load("theft_a"))
    sp = spans_by_path(w)
    assert sp["body.args[1]"]["op"] == "not" and sp["body.args[1]"]["rho"] > 0
    assert sp["body.args[1]"]["t_start_ms"] == sp["body.args[1]"]["t_end_ms"]


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_witness_matches_robustness_on_fixtures(name):
    for text in [THEFT, "exists v: Vehicle: holds_for >= 120 in_zone(v, dock)",
                 "exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)"]:
        r = parse(text)
        w = witness(r, load(name))
        assert w["score"] == robustness(r, load(name))


def test_witness_validates_against_api_yaml_schema():
    spec = yaml.safe_load(API.read_text(encoding="utf-8"))
    schema = spec["components"]["schemas"]["Witness"]
    v = Draft202012Validator(schema)
    for name in ["theft_a", "delivery_a", "vehicle_dwell_dock", "unattended_package"]:
        for text in [THEFT, "exists v: Vehicle: holds_for >= 120 in_zone(v, dock)", "exists k: Package: always[0, 24] in_zone(k, steps)"]:
            w = witness(parse(text), load(name))
            v.validate({**w, "rule_id": "r1", "tau": 0.1, "margin": w["score"] - 0.1})
