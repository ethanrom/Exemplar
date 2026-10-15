"""Monitor end to end with fake perceivers and fixture traces: stage 0 / 1 / 2, witnesses, failures, cost."""
from __future__ import annotations

import pytest

from exemplar.contracts.trace import TraceContext
from exemplar.monitor import DeployedRule, Monitor, Prices, stage0_reason
from monitor_helpers import (DWELL, THEFT, UNATTENDED, Perceiver, Sink, deployed, event, load, paid, validator,
                             with_conf)

THEFT_A = load("theft_a")           # theft score +0.45
DELIVERY_A = load("delivery_a")     # theft score -0.45


def make(fast=None, strong=None, *, actions=None, prices=None):
    sink = Sink()
    fast = fast if fast is not None else Perceiver()
    strong = strong if strong is not None else Perceiver()
    mon = Monitor(perceive_fast=fast, perceive_strong=strong, on_firing=sink.on_firing, on_event=sink.on_event,
                  actions=actions, prices=prices, clock=lambda: 1_700_000_000.0)
    return mon, sink, fast, strong


# ------------------------------------------------------------------------------------------ stage 0
@pytest.mark.parametrize("sub_type,rule_text,pruned", [
    ("vehicle", THEFT, True),                         # needs a person
    ("vehicle", DWELL, False),                        # needs only a vehicle
    ("vehicle", UNATTENDED, False),                   # package only
    ("other_motion", DWELL, True),                    # no vehicle either
    ("other_motion", THEFT, True),
    ("other_motion", UNATTENDED, False),
    ("other_motion", "exists a: Animal: present(a)", False),
    ("other_motion", "exists e: Entity: present(e)", False),
    ("other_motion", "exists k: Carryable: present(k)", False),
    ("human", THEFT, False), ("human", DWELL, False), ("package_delivery", THEFT, False), ("motion", THEFT, False),
    ("ding", THEFT, False), ("on_demand", THEFT, False), (None, THEFT, False), (None, DWELL, False),
    ("human", THEFT + " when subtype = human", False),
    ("vehicle", DWELL + " when subtype = human", True),     # context contradicts the known sub_type
    ("on_demand", DWELL + " when subtype = vehicle", True),
    (None, DWELL + " when subtype = vehicle", False),       # unknown sub_type never prunes
])
def test_stage0_pruning_table(sub_type, rule_text, pruned):
    assert (stage0_reason(deployed("r", rule_text).rule, sub_type) is not None) == pruned


def test_stage0_drop_never_calls_perception_and_is_recorded():
    mon, sink, fast, strong = make()
    mon.deploy(deployed("theft", THEFT))
    (rec,) = mon.process(event("e1", sub_type="vehicle"))
    assert (rec.stage, rec.fired, rec.score, rec.witness, rec.actions) == (0, False, None, None, ())
    assert rec.tau == 0.0 and "person" in rec.message
    assert fast.calls == [] and strong.calls == []
    assert sink.types() == ["rule_dropped", "cost_update"] and sink.firings == [rec]
    assert sink.of("rule_dropped")[0]["firing"]["stage"] == 0
    c = mon.cost()
    assert (c["events"], c["stage0_dropped"], c["stage1_scored"], c["stage2_escalated"], c["tokens_in"]) == (1, 1, 0, 0, 0)


def test_stage0_prunes_only_the_impossible_rules_and_the_rest_share_one_fast_trace():
    fast = Perceiver({"e1": THEFT_A})
    mon, sink, fast, _ = make(fast)
    mon.deploy(deployed("theft", THEFT))
    mon.deploy(deployed("dwell", DWELL))
    mon.deploy(deployed("unattended", UNATTENDED))
    recs = mon.process(event("e1", sub_type="vehicle"))            # theft needs a person: stage 0
    assert [(r.rule_id, r.stage, r.fired) for r in recs] == [("theft", 0, False), ("dwell", 1, False), ("unattended", 1, False)]
    assert fast.calls == ["e1"]                                      # one fast trace for both remaining rules
    assert mon.cost()["stage1_scored"] == 2 and mon.cost()["stage0_dropped"] == 1


# ------------------------------------------------------------------------------------------ stage 1
def test_stage1_fire_with_witness_margin_and_ui_action():
    fast = Perceiver({"e1": paid(THEFT_A, 6400, 1500)})
    mon, sink, fast, strong = make(fast)
    mon.deploy(deployed("theft", THEFT, tau=0.1, delta=0.1))
    (rec,) = mon.process(event("e1", sub_type="human"))
    assert rec.fired and rec.stage == 1 and rec.score == pytest.approx(0.45) and rec.tau == 0.1
    w = rec.witness
    assert w["rule_id"] == "theft" and w["tau"] == 0.1 and w["margin"] == pytest.approx(0.35)
    assert w["score"] == pytest.approx(0.45) and w["bindings"] == {"p": "p1", "k": "k1"} and w["clip_id"] == "theft_a"
    then = next(s for s in w["spans"] if s["op"] == "then")
    assert (then["t_start_ms"], then["t_end_ms"]) == (6000, 8000)
    assert [a["action"] for a in rec.actions] == ["ui"] and rec.actions[0]["status"] == "ok"
    assert strong.calls == [] and sink.firings == [rec]
    assert sink.types() == ["rule_fired", "action_result", "cost_update"]
    assert sink.of("rule_fired")[0]["rule_id"] == "theft" and sink.of("rule_fired")[0]["firing"]["fired"] is True
    # api shapes
    validator("Firing").validate(rec.to_api())
    for e in sink.events:
        validator("MonitorEvent").validate(e)
    validator("Witness").validate(w)
    c = mon.cost()
    assert (c["events"], c["stage1_scored"], c["stage2_escalated"], c["tokens_in"], c["tokens_out"]) == (1, 1, 0, 6400, 1500)
    assert c["usd_estimate"] == pytest.approx((6400 * 0.10 + 1500 * 0.50) / 1e6)


def test_stage1_drop_below_tau():
    mon, sink, fast, _ = make(Perceiver({"e1": DELIVERY_A}))
    mon.deploy(deployed("theft", THEFT))
    (rec,) = mon.process(event("e1", sub_type="package_delivery"))
    assert (rec.stage, rec.fired, rec.witness, rec.actions) == (1, False, None, ())
    assert rec.score == pytest.approx(-0.45) and "<=" in rec.message
    assert sink.types() == ["rule_dropped", "cost_update"]
    validator("Firing").validate(rec.to_api())


def test_score_equal_to_tau_does_not_fire():
    mon, *_ = make(Perceiver({"e1": THEFT_A}))
    mon.deploy(deployed("theft", THEFT, tau=0.45, delta=0.0))
    (rec,) = mon.process(event("e1"))
    assert rec.score == pytest.approx(0.45) and not rec.fired


def test_precomputed_trace_skips_fast_perception_and_tokens_depend_on_trace_cached():
    mon, sink, fast, _ = make()
    mon.deploy(deployed("theft", THEFT))
    t = paid(THEFT_A, 1000, 100)
    (rec,) = mon.process(event("e1", trace=t))
    assert rec.fired and fast.calls == []
    assert mon.cost()["tokens_in"] == 1000
    mon.process(event("e2", trace=t, trace_cached=True))
    assert mon.cost()["tokens_in"] == 1000 and mon.cost()["events"] == 2


def test_perception_result_like_objects_are_unwrapped_and_cached_ones_cost_nothing():
    class Result:
        def __init__(self, trace, cached):
            self.trace, self.cached = trace, cached

    fast = Perceiver({"e1": Result(paid(THEFT_A, 500, 50), True), "e2": Result(paid(THEFT_A, 700, 70), False)})
    mon, *_ = make(fast)
    mon.deploy(deployed("theft", THEFT))
    assert mon.process(event("e1"))[0].fired and mon.cost()["tokens_in"] == 0
    assert mon.process(event("e2"))[0].fired and mon.cost()["tokens_in"] == 700


def test_event_context_is_overlaid_on_the_trace_context():
    rule = THEFT + " when hour in [10, 18] and subtype = human and device = dev1"
    bare = THEFT_A.model_copy(update={"context": TraceContext()})        # the trace itself knows nothing
    mon, *_ = make(Perceiver({"e1": bare}))
    mon.deploy(deployed("theft", rule))
    (rec,) = mon.process(event("e1", sub_type="human", context=TraceContext(local_hour=14)))
    assert rec.fired and rec.witness["score"] == pytest.approx(0.45)
    (rec,) = mon.process(event("e1", sub_type="human", context=TraceContext(local_hour=3)))
    assert not rec.fired and rec.score == pytest.approx(-0.5)


def test_deploy_undeploy_and_holes():
    mon, *_ = make(Perceiver({"e1": THEFT_A}))
    mon.deploy(deployed("a", THEFT))
    mon.deploy(deployed("b", THEFT))
    assert [r.rule_id for r in mon.deployed()] == ["a", "b"]
    mon.undeploy("a")
    mon.undeploy("nope")
    assert [r.rule_id for r in mon.process(event("e1"))] == ["b"]
    mon.deploy(deployed("b", UNATTENDED))                              # same id replaces
    assert [r.fired for r in mon.process(event("e1"))] == [False]
    with pytest.raises(ValueError, match="holes"):
        mon.deploy(deployed("h", "exists p: Person, k: Package: picks_up(p, k) then[0, ?b] carrying(p, k)"))
    mon.undeploy("b")
    assert mon.process(event("e1")) == []
    assert mon.cost()["events"] == 3


def test_deploy_derives_english_when_empty():
    mon, *_ = make()
    r = deployed("a", THEFT)
    mon.deploy(DeployedRule(rule_id="a", concept_id="c", rule=r.rule, tau=0.0))
    assert mon.deployed()[0].english.startswith("There is a person p")


# ------------------------------------------------------------------------------------------ stage 2
def test_stage2_escalation_flips_a_drop_into_a_fire():
    weak = with_conf(THEFT_A, "picks_up", "low")                       # fast model unsure: score +0.10
    strong_trace = paid(THEFT_A, 6200, 1600, mode="strong")            # strong model sure: +0.45
    mon, sink, fast, strong = make(Perceiver({"e1": paid(weak, 6400, 1500)}), Perceiver({"e1": strong_trace}))
    mon.deploy(deployed("theft", THEFT, tau=0.12, delta=0.1))          # stage-1 score 0.10 < tau: would drop
    (rec,) = mon.process(event("e1", sub_type="human"))
    assert rec.fired and rec.stage == 2 and rec.score == pytest.approx(0.45)
    assert rec.witness["margin"] == pytest.approx(0.45 - 0.12) and rec.witness["tau"] == 0.12
    assert fast.calls == ["e1"] and strong.calls == ["e1"]
    assert sink.types() == ["escalated", "rule_fired", "action_result", "cost_update"]
    assert "escalating" in sink.of("escalated")[0]["message"]
    assert "stage 1 score +0.10, strong score +0.45" in rec.message
    c = mon.cost()
    assert (c["stage1_scored"], c["stage2_escalated"], c["tokens_in"], c["tokens_out"]) == (1, 1, 6400 + 6200, 1500 + 1600)
    assert c["usd_estimate"] == pytest.approx((6400 * 0.10 + 1500 * 0.50 + 6200 * 2 + 1600 * 10) / 1e6)
    for e in sink.events:
        validator("MonitorEvent").validate(e)


def test_stage2_escalation_flips_a_fire_into_a_drop():
    weak = with_conf(THEFT_A, "picks_up", "low")                       # fast: +0.10 > 0 would fire
    mon, sink, *_ = make(Perceiver({"e1": weak}), Perceiver({"e1": DELIVERY_A}))
    mon.deploy(deployed("theft", THEFT, tau=0.0, delta=0.1))
    (rec,) = mon.process(event("e1"))
    assert not rec.fired and rec.stage == 2 and rec.score == pytest.approx(-0.45) and rec.witness is None
    assert sink.types() == ["escalated", "rule_dropped", "cost_update"]


def test_stage2_runs_strong_perception_once_per_event_for_all_rules_in_the_band():
    weak = with_conf(THEFT_A, "picks_up", "low")
    mon, sink, fast, strong = make(Perceiver({"e1": weak}), Perceiver({"e1": THEFT_A}))
    mon.deploy(deployed("t1", THEFT, tau=0.0))
    mon.deploy(deployed("t2", THEFT, tau=0.2, delta=0.1))             # 0.10 within 0.1 of 0.2
    mon.deploy(deployed("far", THEFT, tau=0.45, delta=0.1))           # |0.10 - 0.45| > delta: stays at stage 1
    recs = {r.rule_id: r for r in mon.process(event("e1"))}
    assert strong.calls == ["e1"]
    assert (recs["t1"].stage, recs["t1"].fired) == (2, True)
    assert (recs["t2"].stage, recs["t2"].fired) == (2, True)
    assert (recs["far"].stage, recs["far"].fired) == (1, False) and recs["far"].score == pytest.approx(0.10)
    assert mon.cost()["stage2_escalated"] == 2 and mon.cost()["stage1_scored"] == 3


def test_band_is_inclusive_and_confident_scores_are_not_escalated():
    mon, _, _, strong = make(Perceiver({"e1": THEFT_A}))
    mon.deploy(deployed("edge", THEFT, tau=0.35, delta=0.1))          # |0.45 - 0.35| = 0.1: inside (inclusive)
    mon.deploy(deployed("out", THEFT, tau=0.0, delta=0.1))
    mon.process(event("e1"))
    assert strong.calls == ["e1"] and mon.cost()["stage2_escalated"] == 1


def test_no_escalation_without_a_band_hit():
    mon, _, _, strong = make(Perceiver({"e1": THEFT_A, "e2": DELIVERY_A}))
    mon.deploy(deployed("theft", THEFT))
    mon.process(event("e1")), mon.process(event("e2"))
    assert strong.calls == []


# ------------------------------------------------------------------------------------------ failures
def test_fast_perception_exception_drops_with_a_message_and_never_raises():
    mon, sink, *_ = make(Perceiver({"e1": RuntimeError("bedrock throttled")}))
    mon.deploy(deployed("a", THEFT))
    mon.deploy(deployed("b", UNATTENDED))
    recs = mon.process(event("e1"))
    assert [(r.stage, r.fired, r.score) for r in recs] == [(1, False, None)] * 2
    assert all("perception failed" in r.message and "bedrock throttled" in r.message for r in recs)
    assert sink.types().count("rule_dropped") == 2 and mon.cost()["stage1_scored"] == 0


def test_perception_failed_trace_drops():
    mon, *_ = make(Perceiver({"e1": load("perception_failed")}))
    mon.deploy(deployed("a", THEFT))
    (rec,) = mon.process(event("e1"))
    assert not rec.fired and rec.stage == 1 and "perception failed" in rec.message
    (rec,) = mon.process(event("e2", trace=load("perception_failed")))
    assert not rec.fired and "perception failed" in rec.message


def test_garbage_from_the_perceiver_is_a_dropped_event_not_a_crash():
    mon, *_ = make(Perceiver({"e1": "not a trace"}))
    mon.deploy(deployed("a", THEFT))
    (rec,) = mon.process(event("e1"))
    assert not rec.fired and "TypeError" in rec.message


def test_strong_perception_failure_keeps_the_stage1_decision_and_says_so():
    weak = with_conf(THEFT_A, "picks_up", "low")                       # +0.10, in the band of tau 0
    mon, sink, *_ = make(Perceiver({"e1": weak}), Perceiver({"e1": RuntimeError("strong model down")}))
    mon.deploy(deployed("theft", THEFT, tau=0.0, delta=0.1))
    (rec,) = mon.process(event("e1"))
    assert rec.fired and rec.stage == 1 and rec.score == pytest.approx(0.10)
    assert "escalation failed" in rec.message and "strong model down" in rec.message
    assert "error" in sink.types() and "escalated" in sink.types()
    # the failed escalation is still counted as an attempt
    assert mon.cost()["stage2_escalated"] == 1


def test_strong_trace_perception_failed_keeps_the_stage1_decision():
    weak = with_conf(THEFT_A, "picks_up", "low")
    mon, *_ = make(Perceiver({"e1": weak}), Perceiver({"e1": load("perception_failed")}))
    mon.deploy(deployed("theft", THEFT, tau=0.0, delta=0.1))
    (rec,) = mon.process(event("e1"))
    assert rec.fired and rec.stage == 1 and "escalation failed" in rec.message


def test_callback_exceptions_are_contained():
    def boom(_):
        raise RuntimeError("sink down")

    mon = Monitor(perceive_fast=Perceiver({"e1": THEFT_A}), perceive_strong=Perceiver(), on_firing=boom, on_event=boom)
    mon.deploy(deployed("theft", THEFT))
    (rec,) = mon.process(event("e1"))
    assert rec.fired


# ------------------------------------------------------------------------------------------ cost meter
def test_cost_totals_over_several_events_and_per_event_usd():
    weak = with_conf(THEFT_A, "picks_up", "low")
    fast = Perceiver({"e1": paid(THEFT_A, 6400, 1500), "e2": paid(weak, 6400, 1500), "e3": paid(DELIVERY_A, 6400, 1500)})
    strong = Perceiver({"e2": paid(THEFT_A, 6200, 1600, mode="strong")})
    mon, sink, *_ = make(fast, strong, prices=Prices())
    mon.deploy(deployed("theft", THEFT))
    for i in (1, 2, 3):
        mon.process(event(f"e{i}"))
    mon.process(event("e4", sub_type="vehicle"))                       # stage 0: no perception, no tokens
    c = mon.cost()
    assert (c["events"], c["stage0_dropped"], c["stage1_scored"], c["stage2_escalated"]) == (4, 1, 3, 1)
    assert (c["tokens_in"], c["tokens_out"]) == (3 * 6400 + 6200, 3 * 1500 + 1600)
    usd = (3 * 6400 * 0.10 + 3 * 1500 * 0.50 + 6200 * 2 + 1600 * 10) / 1e6
    assert c["usd_estimate"] == pytest.approx(usd) and c["per_event_usd"] == pytest.approx(usd / 4)
    validator("CostSummary").validate(c)
    updates = sink.of("cost_update")
    assert len(updates) == 4 and updates[-1]["cost"] == c and updates[0]["cost"]["events"] == 1
    assert [u["event_id"] for u in updates] == ["e1", "e2", "e3", "e4"]


def test_custom_price_table():
    mon, *_ = make(Perceiver({"e1": paid(THEFT_A, 1_000_000, 1_000_000)}), prices=Prices(fast_in=1, fast_out=2, strong_in=0, strong_out=0))
    mon.deploy(deployed("theft", THEFT))
    mon.process(event("e1"))
    assert mon.cost()["usd_estimate"] == pytest.approx(3.0)


def test_cost_with_no_events_is_zero():
    mon, *_ = make()
    c = mon.cost()
    assert c["events"] == 0 and c["usd_estimate"] == 0 and c["per_event_usd"] == 0
    validator("CostSummary").validate(c)


def test_event_without_deployed_rules_still_counts_and_emits_cost_update():
    mon, sink, fast, _ = make()
    assert mon.process(event("e1")) == []
    assert fast.calls == [] and sink.types() == ["cost_update"] and mon.cost()["events"] == 1
