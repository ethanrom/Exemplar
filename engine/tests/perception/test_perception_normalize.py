from __future__ import annotations

from exemplar.contracts.trace import PerceptionMeta, TraceContext
from exemplar.perception.normalize import build_trace, norm_id, normalize

T = [0, 1000, 2000]
META = PerceptionMeta(mode="fast", model_alias="fast", n_frames=3)


def payload(**over):
    base = {"entities": [{"id": "p1", "type": "person", "attrs": ["Hoodie"]}, {"id": "k1", "type": "package", "attrs": []}],
            "frames": [{"i": 0, "facts": [{"pred": "present", "args": ["p1"], "conf": "high"}]},
                       {"i": 1, "facts": [{"pred": "picks_up", "args": ["p1", "k1"], "conf": "med"}]},
                       {"i": 2, "facts": []}],
            "summary": " takes a box "}
    base.update(over)
    return base


def build(obj):
    n = normalize(obj, T)
    return n, build_trace(n, clip_id="c", source="upload", duration_ms=3000, context=TraceContext(), meta=META)


def test_clean_payload_roundtrips():
    n, (tr, errs) = build(payload())
    assert errs == [] and tr is not None
    assert [f.t_ms for f in tr.frames] == T
    assert tr.entities[0].attrs == ("hoodie",)                     # lower-cased
    assert tr.summary == "takes a box"
    assert not n.dropped


def test_zone_names_lowercased_and_ids_sanitised():
    obj = payload(entities=[{"id": "P1", "type": "Person", "attrs": ["Delivery Uniform"]}, {"id": " K-1 ", "type": "PACKAGE", "attrs": []}],
                  frames=[{"i": 0, "facts": [{"pred": "in_zone", "args": ["P1", "Steps"], "conf": "HIGH"},
                                             {"pred": "carrying", "args": ["p1", "k_1"], "conf": "Medium"}]}])
    n, (tr, errs) = build(obj)
    assert errs == [], errs
    assert [e.id for e in tr.entities] == ["p1", "k_1"] and tr.entities[0].attrs == ("delivery_uniform",)
    assert [(f.pred, f.args, f.conf) for f in tr.frames[0].facts] == [
        ("in_zone", ("p1", "steps"), "high"), ("carrying", ("p1", "k_1"), "med")]
    assert norm_id("9lives") == "e_9lives" and norm_id("") is None and norm_id(5) is None


def test_facts_with_unknown_entity_ids_are_dropped_and_counted():
    obj = payload()
    obj["frames"][0]["facts"] += [{"pred": "present", "args": ["p9"], "conf": "high"},
                                  {"pred": "near", "args": ["p1", "zz"], "conf": "low"}]
    n, (tr, errs) = build(obj)
    assert errs == [] and n.dropped["fact_unknown_entity"] == 2
    assert [f.args for f in tr.frames[0].facts] == [("p1",)]


def test_missing_frames_become_empty_and_bad_indices_are_dropped():
    obj = payload(frames=[{"i": 1, "facts": [{"pred": "present", "args": ["p1"], "conf": "low"}]},
                          {"i": 7, "facts": []}, {"i": -1, "facts": []}, {"i": "x", "facts": []}])
    n, (tr, errs) = build(obj)
    assert errs == [] and n.dropped["frame_bad_index"] == 3
    assert [len(f.facts) for f in tr.frames] == [0, 1, 0]
    assert [e.id for e in tr.entities] == ["p1"]                  # k1 never mentioned -> dropped
    assert n.dropped["entity_unreferenced"] == 1


def test_duplicate_facts_keep_max_confidence():
    obj = payload(frames=[{"i": 0, "facts": [{"pred": "present", "args": ["p1"], "conf": "low"},
                                             {"pred": "present", "args": ["p1"], "conf": "high"}]}])
    n, (tr, errs) = build(obj)
    assert errs == [] and n.dropped["fact_duplicate"] == 1
    assert [(f.args, f.conf) for f in tr.frames[0].facts] == [(("p1",), "high")]


def test_duplicate_entities_dropped():
    obj = payload(entities=payload()["entities"] + [{"id": "P1", "type": "vehicle", "attrs": []}])
    n, (tr, errs) = build(obj)
    assert errs == [] and n.dropped["entity_duplicate"] == 1 and tr.entity("p1").type == "person"


def test_near_is_made_symmetric_and_self_near_dropped():
    obj = payload(frames=[{"i": 0, "facts": [{"pred": "near", "args": ["k1", "p1"], "conf": "med"},
                                             {"pred": "near", "args": ["p1", "p1"], "conf": "med"}]}])
    n, (tr, errs) = build(obj)
    assert errs == [] and n.dropped["fact_self_near"] == 1
    assert {f.args for f in tr.frames[0].facts} == {("k1", "p1"), ("p1", "k1")}
    assert tr.signal("near", ("p1", "k1"))[0] == tr.signal("near", ("k1", "p1"))[0] == 0.8


def test_ontology_violations_become_errors_not_exceptions():
    cases = [
        ({"pred": "rings_doorbell", "args": ["p1"], "conf": "high"}, "unknown predicate"),
        ({"pred": "in_zone", "args": ["p1", "garage"], "conf": "high"}, "not a valid Zone"),
        ({"pred": "picks_up", "args": ["k1", "p1"], "conf": "high"}, "not a valid Person"),
        ({"pred": "near", "args": ["p1"], "conf": "high"}, "takes 2 args"),
        ({"pred": "present", "args": ["p1"], "conf": "certain"}, "conf must be"),
    ]
    for fact, msg in cases:
        obj = payload()
        obj["frames"][0]["facts"].append(fact)
        n, (tr, errs) = build(obj)
        assert tr is None and any(msg in e for e in errs), (fact, errs)


def test_garbage_input_is_an_error():
    for bad in [None, "text", [], {"entities": 3, "frames": []}, {}]:
        n = normalize(bad, T)
        assert n.errors
