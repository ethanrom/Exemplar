from __future__ import annotations

import pytest

from exemplar.contracts.trace import Entity, Fact, Frame, PerceptionMeta, Trace
from exemplar.perception import merge_traces


def mk(frames, entities=None, *, tin=100, tout=10, summary="s"):
    ents = entities if entities is not None else [Entity(id="p1", type="person", attrs=("a",)),
                                                  Entity(id="k1", type="package")]
    fr = tuple(Frame(t_ms=1000 * i, facts=tuple(Fact(pred=p, args=a, conf=c) for p, a, c in facts))
               for i, facts in enumerate(frames))
    return Trace(clip_id="c", source="upload", duration_ms=1000 * len(frames), entities=tuple(ents), frames=fr,
                 summary=summary, perception=PerceptionMeta(mode="strong", model_alias="m", n_frames=len(frames),
                                                           tokens_in=tin, tokens_out=tout, latency_ms=50))


def test_single_trace_is_returned_unchanged():
    t = mk([[("present", ("p1",), "high")]])
    m, stats = merge_traces([t])
    assert m == t and not stats


def test_both_keep_lower_confidence_one_sided_become_low():
    a = mk([[("present", ("p1",), "high"), ("carrying", ("p1", "k1"), "high")], [("present", ("p1",), "med")]])
    b = mk([[("present", ("p1",), "low"), ("near", ("p1", "k1"), "high")], [("present", ("p1",), "high")]])
    m, stats = merge_traces([a, b])
    got = {(i, f.pred, f.args): f.conf for i, fr in enumerate(m.frames) for f in fr.facts}
    assert got == {(0, "present", ("p1",)): "low",              # min(high, low)
                   (0, "carrying", ("p1", "k1")): "low",         # only in a, was high
                   (0, "near", ("p1", "k1")): "low",             # only in b, was high
                   (1, "present", ("p1",)): "med"}               # min(med, high)
    assert stats["facts_both"] == 2 and stats["facts_partial"] == 2


def test_both_med_and_high_stay_when_equal():
    f = [[("present", ("p1",), "high")]]
    m, _ = merge_traces([mk(f), mk(f)])
    assert m.frames[0].facts[0].conf == "high"


def test_entities_are_unioned_by_id_and_attrs_unioned():
    a = mk([[("present", ("p1",), "high")]], [Entity(id="p1", type="person", attrs=("hoodie",))])
    b = mk([[("present", ("p1",), "high"), ("present", ("p2",), "med")]],
           [Entity(id="p1", type="person", attrs=("hoodie", "backpack")), Entity(id="p2", type="person")])
    m, _ = merge_traces([a, b])
    assert [(e.id, e.attrs) for e in m.entities] == [("p1", ("hoodie", "backpack")), ("p2", ())]
    assert m.frames[0].facts[1].conf == "low"                   # p2 seen by one sample only


def test_type_conflict_keeps_first_and_drops_the_other_samples_facts():
    a = mk([[("present", ("x1",), "high")]], [Entity(id="x1", type="person")])
    b = mk([[("present", ("x1",), "high")]], [Entity(id="x1", type="vehicle")])
    m, stats = merge_traces([a, b])
    assert m.entity("x1").type == "person" and stats["facts_type_conflict"] == 1
    assert m.frames[0].facts[0].conf == "low"                   # only the first sample's assertion survives


def test_meta_is_summed_and_first_summary_wins():
    a, b = mk([[("present", ("p1",), "high")]], tin=100, tout=10, summary="one"), \
        mk([[("present", ("p1",), "high")]], tin=300, tout=30, summary="two")
    m, _ = merge_traces([a, b])
    assert (m.perception.samples, m.perception.tokens_in, m.perception.tokens_out) == (2, 400, 40)
    assert m.summary == "one" and m.status == "ok"


def test_mismatched_frames_rejected():
    with pytest.raises(ValueError):
        merge_traces([mk([[]]), mk([[], []])])
    with pytest.raises(ValueError):
        merge_traces([])


def test_three_samples_use_all_for_agreement():
    f = [[("present", ("p1",), "high")]]
    low = [[("present", ("p1",), "low")]]
    m, stats = merge_traces([mk(f), mk(f), mk(low)])
    assert m.frames[0].facts[0].conf == "low" and stats["facts_both"] == 1
    m, stats = merge_traces([mk(f), mk(f), mk([[]])])
    assert m.frames[0].facts[0].conf == "low" and stats["facts_partial"] == 1
