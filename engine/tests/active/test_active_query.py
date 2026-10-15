"""select_query: p(u), closest-to-0.5 pick, diversity among near-ties, labelled clips never returned."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from active_helpers import GridBox, candidate, example, gap_trace, load, present_trace, THEN_SKETCH
from exemplar.active import Committee, Question, build_committee, committee_scores, select_query
from exemplar.dsl import parse

API = Path(__file__).parents[2] / "exemplar" / "contracts" / "api.yaml"


@pytest.fixture(scope="module")
def committee() -> Committee:
    # version space for b: [2, 24] (theft_a gives the lower end; the clip is 24 s of rule horizon)
    exs = [example(load("theft_a"), True), example(load("delivery_a"), False)]
    return build_committee([candidate(THEN_SKETCH, {"b": 3.0})], exs, box_fn=GridBox(), n_samples=400, seed=0)


def true_p(gap: float) -> float:        # P(b >= gap) for b uniform on [2, 24]
    return (24.0 - gap) / 22.0


def test_p_is_the_weighted_fraction_of_members_that_match(committee):
    traces = [gap_trace(f"g{g}", g) for g in (3, 8, 13, 20)]
    S, w = committee_scores(committee, traces)
    p = w @ (S > 0)
    for pj, g in zip(p, (3, 8, 13, 20)):
        assert pj == pytest.approx(true_p(g), abs=0.06)


def test_picks_the_clip_with_p_closest_to_one_half(committee):
    unl = [gap_trace(f"g{g}", g) for g in (3, 8, 13, 20)]
    (q,) = select_query(committee, unl)
    assert q.clip_id == "g13" and abs(q.p - 0.5) < 0.07 and q.committee_size == len(committee)


def test_labelled_clips_are_never_returned(committee):
    unl = [gap_trace(f"g{g}", g) for g in (3, 10, 13, 22)]
    by_id = {t.clip_id: t for t in unl}
    (q,) = select_query(committee, unl, labelled=[by_id["g13"]])
    assert q.clip_id == "g10"                                     # the best remaining: p about 0.64
    (q,) = select_query(committee, unl, exclude={"g13", "g10", "g3"})
    assert q.clip_id == "g22"
    assert select_query(committee, unl, exclude={t.clip_id for t in unl}) == []
    got = select_query(committee, unl, k=10, labelled=[by_id["g13"]])
    assert "g13" not in {x.clip_id for x in got} and len(got) == 3


def test_k_returns_distinct_clips_in_selection_order(committee):
    unl = [gap_trace(f"g{g}", g) for g in (3, 8, 13, 20)]
    qs = select_query(committee, unl, k=3)
    assert len({q.clip_id for q in qs}) == 3 and qs[0].clip_id == "g13"
    assert all(isinstance(q, Question) for q in qs)


def test_duplicates_in_unlabelled_are_collapsed(committee):
    t = gap_trace("g13", 13)
    assert len(select_query(committee, [t, t, t], k=3)) == 1


def test_deterministic(committee):
    unl = [gap_trace(f"g{g}", g) for g in (3, 8, 13, 20)]
    assert select_query(committee, unl, k=3) == select_query(committee, unl, k=3)


def test_empty_inputs(committee):
    assert select_query(Committee(members=()), [gap_trace("g", 3)]) == []
    assert select_query(committee, []) == []
    with pytest.raises(ValueError):
        select_query(committee, [gap_trace("g", 3)], k=0)


def test_unanimous_committee_still_returns_the_closest_clips_with_p_0_or_1(committee):
    qs = select_query(committee, [gap_trace("easy_yes", 1.5), gap_trace("easy_no", 40.0)], k=2)
    assert [(q.clip_id, round(q.p, 9)) for q in qs] == [("easy_no", 0.0), ("easy_yes", 1.0)]      # equal gaps: by id


# ------------------------------------------------------------------------------------------ diversity among near-ties
def two_member_committee() -> Committee:
    a = parse("exists v: Vehicle: present(v)")
    b = parse("exists k: Package: present(k)")
    return Committee(members=((a, 0.5), (b, 0.5)))


def test_near_ties_prefer_the_clip_farthest_from_the_labelled_ones():
    com = two_member_committee()
    labelled = present_trace("done", "vehicle")                  # vector (+, -)
    same_as_labelled = present_trace("u_same", "vehicle")       # p = 0.5, vector (+, -): distance 0
    different = present_trace("u_diff", "package")              # p = 0.5, vector (-, +): far
    for order in ([same_as_labelled, different], [different, same_as_labelled]):
        (q,) = select_query(com, order, labelled=[labelled])
        assert q.clip_id == "u_diff" and q.p == pytest.approx(0.5)
    # without a labelled reference the tie falls to the clip id (deterministic)
    (q,) = select_query(com, [same_as_labelled, different])
    assert q.clip_id == "u_diff"                                # 'u_diff' < 'u_same'


def test_diversity_never_overrides_a_clearly_better_p():
    a = parse("exists v: Vehicle: present(v)")
    b = parse("exists k: Package: present(k)")
    c = parse("exists p: Person: present(p)")
    com = Committee(members=((a, 0.5), (b, 0.3), (c, 0.2)))
    labelled = present_trace("done", "vehicle")
    u_half = present_trace("u_half", "vehicle")                 # p = 0.5, identical to the labelled clip
    u_far = present_trace("u_far", "vehicle", "package")        # p = 0.8, distinct
    (q,) = select_query(com, [u_far, u_half], labelled=[labelled])
    assert q.clip_id == "u_half" and q.p == pytest.approx(0.5)


def test_near_ties_within_five_points_are_resolved_by_diversity():
    rules = [parse(f"exists {v}: {t}: present({v})") for v, t in (("v", "Vehicle"), ("k", "Package"), ("p", "Person"), ("a", "Animal"))]
    com = Committee(members=tuple(zip(rules, (0.50, 0.25, 0.22, 0.03))))
    labelled = present_trace("done", "vehicle")                          # matches member 1 only
    u_exact = present_trace("u_exact", "vehicle")                        # p = 0.50 (gap 0.00), same vector as `done`
    u_diverse = present_trace("u_diverse", "package", "person")          # p = 0.47 (gap 0.03), far from `done`
    (q,) = select_query(com, [u_exact, u_diverse], labelled=[labelled])
    assert q.clip_id == "u_diverse" and q.p == pytest.approx(0.47)
    # a gap of 0.25 is no near-tie: the closer clip wins even though it is not diverse
    u_far = present_trace("u_far", "package")                            # p = 0.25
    (q,) = select_query(com, [u_exact, u_far], labelled=[labelled])
    assert q.clip_id == "u_exact"


def test_batch_picks_are_diverse_from_each_other():
    com = two_member_committee()
    same1, same2 = present_trace("s1", "vehicle"), present_trace("s2", "vehicle")
    other = present_trace("o1", "package")
    qs = select_query(com, [same1, same2, other], k=2)
    assert {q.clip_id for q in qs} == {"o1", "s1"} or {q.clip_id for q in qs} == {"o1", "s2"}   # not s1 + s2


# ------------------------------------------------------------------------------------------ API
def test_question_to_api():
    q = Question(clip_id="c9", p=0.4, committee_size=17)
    d = q.to_api(concept_id="theft")
    assert d == {"concept_id": "theft", "clip_id": "c9", "p": 0.4, "committee_size": 17}
    spec = yaml.safe_load(API.read_text(encoding="utf-8"))
    Draft202012Validator(spec["components"]["schemas"]["Question"]).validate(d)
    ev = {"id": "e1"}
    assert q.to_api(concept_id="theft", event=ev)["event"] == ev
