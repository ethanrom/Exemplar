"""Rules: get/patch, backtest (calibration from `random` labels only), deploy -> monitor -> firings."""
from __future__ import annotations

import json
import time

import pytest

from exemplar.contracts.dsl_ast import Rule
from exemplar.dsl import parse, robustness, to_english

from . import helpers as H
from .conftest import validate_component

ALL = H.ALL_FIXTURES
EXAMPLES = H.EXAMPLES
_teach_and_calibrate = H.teach_and_calibrate


post_webhook = H.post_webhook


# ------------------------------------------------------------------------------------------ get / patch
def test_get_rule_and_404(renv):
    r = renv.client.get(f"/rules/{renv.theft['id']}")
    assert r.status_code == 200 and r.json()["dsl_text"] == renv.theft["dsl_text"]
    assert renv.client.get("/rules/ru_nope").status_code == 404
    assert renv.client.patch("/rules/ru_nope", json={"status": "selected"}).status_code == 404
    assert renv.client.get("/rules/ru_nope/backtest").status_code == 404


def test_patch_status_and_actions(renv):
    rid = renv.theft["id"]
    r = renv.client.patch(f"/rules/{rid}", json={"status": "selected"})
    assert r.status_code == 200 and r.json()["status"] == "selected"
    r = renv.client.patch(f"/rules/{rid}", json={"actions": ["ui", "slack", "ui"]})
    assert sorted(r.json()["actions"]) == ["slack", "ui"]
    assert renv.client.patch(f"/rules/{rid}", json={"actions": []}).json()["actions"] == ["ui"]
    assert renv.client.patch(f"/rules/{rid}", json={}).json()["status"] == "selected"
    assert renv.client.patch(f"/rules/{rid}", json={"status": "archived"}).status_code == 400
    assert renv.client.patch(f"/rules/{rid}", json={"actions": ["sms"]}).status_code == 400
    retired = renv.client.patch(f"/rules/{rid}", json={"status": "retired"}).json()
    assert retired["status"] == "retired"
    assert rid not in [r["id"] for r in renv.client.get(f"/concepts/{renv.cid}/rules").json()]


# ------------------------------------------------------------------------------------------ backtest
def test_backtest_scores_every_traced_clip(renv):
    r = renv.client.get(f"/rules/{renv.theft['id']}/backtest")
    assert r.status_code == 200
    bt = r.json()
    assert bt["rule_id"] == renv.theft["id"]
    traces = {c: H.load_trace(c) for c in ALL}
    assert {row["clip_id"] for row in bt["rows"]} == set(ALL)          # perception_failed has no usable trace
    rule = parse(H.THEFT_DSL)
    for row in bt["rows"]:
        assert row["score"] == pytest.approx(float(robustness(rule, traces[row["clip_id"]])))
        assert row["matched"] == (row["score"] > bt["calibration"]["tau"])
        assert row["event"]["clip_id"] == row["clip_id"]
    scores = [row["score"] for row in bt["rows"]]
    assert scores == sorted(scores, reverse=True)


def test_backtest_witnesses_for_matches_only(renv):
    bt = renv.client.get(f"/rules/{renv.theft['id']}/backtest").json()
    matched = [r for r in bt["rows"] if r["matched"]]
    assert {r["clip_id"] for r in matched} >= {"theft_a", "theft_b"}
    for r in bt["rows"]:
        if not r["matched"]:
            assert r["witness"] is None
            continue
        w = r["witness"]
        assert w["rule_id"] == renv.theft["id"] and w["clip_id"] == r["clip_id"]
        assert w["bindings"].keys() == {"p", "k"} and w["spans"]
        assert w["tau"] == bt["calibration"]["tau"] and w["margin"] == pytest.approx(r["score"] - w["tau"])
        assert w["english"] == to_english(parse(H.THEFT_DSL))


def test_backtest_counts_follow_labels(renv):
    bt = renv.client.get(f"/rules/{renv.theft['id']}/backtest").json()
    by_clip = {r["clip_id"]: r for r in bt["rows"]}
    assert by_clip["theft_a"]["label"]["value"] == "pos" and by_clip["theft_a"]["matched"]
    c = bt["counts"]
    labelled = [r for r in bt["rows"] if r["label"]]
    assert c["tp"] + c["fp"] + c["fn"] + c["tn"] == len(labelled) == 10
    assert c["tp"] == sum(1 for r in labelled if r["label"]["value"] == "pos" and r["matched"])
    assert c["fp"] == sum(1 for r in labelled if r["label"]["value"] == "neg" and r["matched"])
    assert c["tp"] >= 2 and c["fn"] == 0 and c["unlabelled_matches"] == 0


def test_calibration_uses_only_random_labels(renv):
    """The guarantee depends on it: example / active labels must never reach `calibrate`."""
    renv.label(renv.cid, "visitor_rings", None, "random")                    # drop one random label ...
    renv.label(renv.cid, "visitor_rings", "pos", "active")                   # ... and re-add it as an active label
    bt = renv.client.get(f"/rules/{renv.theft['id']}/backtest").json()
    call = renv.calibrate.calls[-1]
    assert len(call["labels"]) == 6 and all(l.provenance == "random" for l in call["labels"])
    assert {l.clip_id for l in call["labels"]} == {"delivery_b", "unattended_package", "visitor_no_ring", "empty_scene",
                                                    "vehicle_passby", "birds_feeder"}
    assert not {"theft_a", "theft_b", "delivery_a", "visitor_rings"} & {l.clip_id for l in call["labels"]}
    assert call["alpha"] == 0.2 and bt["calibration"]["n_random_neg"] == 6


def test_calibration_is_conformal_and_stored(renv):
    bt = renv.client.get(f"/rules/{renv.theft['id']}/backtest").json()
    cal = bt["calibration"]
    rule = parse(H.THEFT_DSL)
    neg = sorted(float(robustness(rule, H.load_trace(c))) for c in ALL if c not in EXAMPLES)
    assert cal["guarantee"] is True and cal["n_random_neg"] == 7 and cal["k"] == 7 and cal["alpha"] == 0.2
    assert cal["tau"] == pytest.approx(max(0.0, neg[6]))                    # k-th smallest negative score, floored at 0 (E)
    row = renv.state.store.rules.get(renv.theft["id"])
    assert row.tau == pytest.approx(cal["tau"]) and row.delta == cal["delta"]
    assert json.loads(row.calibration_json) == cal
    assert renv.client.get(f"/rules/{renv.theft['id']}").json()["calibration"] == cal


def test_backtest_without_random_labels_has_no_guarantee(make_env):
    env = make_env()
    env.seed_fixture_events(*ALL)
    env.cid = env.new_concept()
    _teach_and_calibrate(env, random_labels=False)
    bt = env.client.get(f"/rules/{env.theft['id']}/backtest").json()
    cal = bt["calibration"]
    assert cal["guarantee"] is False and cal["tau"] == 0.0 and cal["n_random_neg"] == 0
    assert "random negatives" in cal["message"]
    assert all(r["matched"] == (r["score"] > 0) for r in bt["rows"])


# ------------------------------------------------------------------------------------------ deploy
def test_deploy_registers_a_calibrated_rule_with_the_monitor(renv):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"actions": ["ui", "slack"]})
    r = renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    assert r.status_code == 200 and r.json()["status"] == "deployed"
    assert r.json()["calibration"]["guarantee"] is True                  # calibrated on first deploy
    (mon,) = H.FakeMonitor.instances
    dep = mon.rules[rid]
    assert dep.concept_id == renv.cid and dep.tau == r.json()["calibration"]["tau"] and dep.delta == r.json()["calibration"]["delta"]
    assert set(dep.actions) == {"ui", "slack"} and dep.rule == parse(H.THEFT_DSL) and dep.english == renv.theft["english"]
    concept = [c for c in renv.client.get("/concepts").json() if c["id"] == renv.cid][0]
    assert concept["deployed_rule_id"] == rid


def test_deploying_another_rule_replaces_the_first(renv):
    a, b = renv.rules[0]["id"], renv.rules[1]["id"]
    renv.client.patch(f"/rules/{a}", json={"status": "deployed"})
    renv.client.patch(f"/rules/{b}", json={"status": "deployed"})
    assert renv.client.get(f"/rules/{a}").json()["status"] == "selected"
    assert list(H.FakeMonitor.instances[0].rules) == [b]


def test_retire_undeploys(renv):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    assert renv.client.patch(f"/rules/{rid}", json={"status": "retired"}).json()["status"] == "retired"
    assert H.FakeMonitor.instances[0].rules == {}
    assert [c for c in renv.client.get("/concepts").json() if c["id"] == renv.cid][0]["deployed_rule_id"] is None


def test_changing_actions_of_a_deployed_rule_redeploys_it(renv):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    renv.client.patch(f"/rules/{rid}", json={"actions": ["ui", "webhook_out"]})
    mon = H.FakeMonitor.instances[0]
    assert set(mon.rules[rid].actions) == {"ui", "webhook_out"} and len(mon.deploy_calls) == 2


def test_new_random_labels_refresh_the_deployed_threshold(renv):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    mon = H.FakeMonitor.instances[0]
    before = mon.rules[rid].tau
    renv.label(renv.cid, "visitor_rings", None, "random")
    renv.client.get(f"/rules/{rid}/backtest")                           # recalibrates on 6 negatives
    assert len(mon.deploy_calls) == 2 and renv.state.store.rules.get(rid).tau == mon.rules[rid].tau
    assert before == mon.deploy_calls[0].tau


# ------------------------------------------------------------------------------------------ deployed rule end to end
def test_deploy_then_webhook_event_fires_and_shows_in_firings(renv):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    renv.perceive.script["evt-rqT"] = "theft_a"
    assert post_webhook(renv, "rqT").status_code == 202
    firings = H.wait_until(lambda: renv.client.get("/monitor/firings").json(), what="a firing")
    f = firings[0]
    assert f["rule_id"] == rid and f["event_id"] == "evt-rqT" and f["fired"] is True and f["stage"] == 1
    assert f["score"] > f["tau"] and f["witness"]["bindings"] == {"p": "p1", "k": "k1"} and f["witness"]["spans"]
    assert f["actions"] == [{"action": "ui", "status": "ok", "detail": None}]
    validate_component("Firing", f)
    assert [x["id"] for x in renv.client.get(f"/monitor/firings?rule_id={rid}").json()] == [f["id"]]
    assert renv.client.get("/monitor/firings?rule_id=ru_other").json() == []
    types = [e["type"] for e in renv.state.bus.recent() if e.get("event_id") == "evt-rqT"]
    assert types == ["event_ingested", "clip_ready", "trace_ready", "rule_fired"]
    fired = [e for e in renv.state.bus.recent() if e["type"] == "rule_fired"][0]
    assert fired["rule_id"] == rid and fired["firing"]["id"] == f["id"]
    # the fast trace made at ingest is handed over as already paid for: perceived (and ledgered) exactly once
    (inp,) = H.FakeMonitor.instances[0].inputs
    assert inp.trace is not None and inp.trace_cached is True and inp.event_id == "evt-rqT"
    assert inp.sub_type == "human" and inp.device_id == H.DEVICE_ID and inp.context.event_kind == "motion"
    assert [c["mode"] for c in renv.perceive.calls_for("evt-rqT")] == ["fast"]
    assert renv.client.get("/events/evt-rqT").json()["trace_status"] == "ok"


def test_a_clip_the_rule_does_not_match_is_dropped_and_logged(renv):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    assert post_webhook(renv, "rqN").status_code == 202                  # default fake trace: a package, no person
    f = H.wait_until(lambda: renv.client.get("/monitor/firings").json(), what="a dropped firing")[0]
    assert f["fired"] is False and f["witness"] is None and f["actions"] == [] and f["event_id"] == "evt-rqN"
    assert [e["type"] for e in renv.state.bus.recent() if e["type"] in ("rule_fired", "rule_dropped")] == ["rule_dropped"]


def test_near_threshold_scores_escalate_to_strong_perception(renv):
    rid = renv.theft["id"]
    renv.state.store.rules.set_calibration(rid, tau=0.44, delta=0.1, calibration={
        "alpha": 0.2, "n_random_neg": 7, "guarantee": True, "tau": 0.44, "delta": 0.1})
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    renv.perceive.script["evt-rqS"] = "theft_a"                          # score 0.45: within delta of tau
    post_webhook(renv, "rqS")
    f = H.wait_until(lambda: renv.client.get("/monitor/firings").json(), what="escalated firing")[0]
    assert f["stage"] == 2
    assert [c["mode"] for c in renv.perceive.calls_for("evt-rqS")] == ["fast", "strong"]
    assert renv.perceive.calls_for("evt-rqS", "strong")[0]["n_frames"] == renv.state.config.strong_frames
    ev = renv.client.get("/events/evt-rqS").json()
    assert ev["strong_trace"]["perception"]["mode"] == "strong"
    assert renv.state.store.cost.totals()["perception_strong"]["calls"] == 1
    cost = renv.client.get("/monitor/cost").json()
    assert cost["stage2_escalated"] == 1 and cost["events"] == 1 and cost["tokens_in"] == 12800


def test_uploads_never_reach_deployed_monitors(renv, long_video):
    renv.client.patch(f"/rules/{renv.theft['id']}", json={"status": "deployed"})
    mon = H.FakeMonitor.instances[0]
    with open(long_video, "rb") as fh:
        r = renv.client.post("/uploads", files={"file": ("l.mp4", fh, "video/mp4")},
                             data={"attribution": "x", "window_s": "10", "stride_s": "10"})
    for i in r.json():
        renv.wait_trace(i["id"])
    time.sleep(0.2)
    assert mon.counts["events"] == 0 and renv.client.get("/monitor/firings").json() == []


def test_deployed_rules_are_restored_after_a_restart(renv, make_env):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    second = make_env()                                                  # same database file, fresh process state
    second.perceive.script["evt-rqR"] = "theft_a"
    post_webhook(second, "rqR")
    f = H.wait_until(lambda: second.client.get("/monitor/firings").json(), what="firing after restart")[0]
    assert f["rule_id"] == rid and f["fired"] is True
    assert rid in H.FakeMonitor.instances[-1].rules


def test_one_firing_row_per_rule_and_event(renv):
    rid = renv.theft["id"]
    renv.client.patch(f"/rules/{rid}", json={"status": "deployed"})
    renv.perceive.script["evt-rqD"] = "theft_a"
    post_webhook(renv, "rqD")
    H.wait_until(lambda: renv.client.get("/monitor/firings").json())
    mon = H.FakeMonitor.instances[0]
    ev = renv.state.store.events.get("evt-rqD")
    again = mon.process(renv.state.processor.event_input(ev, renv.state.store.traces.primary("evt-rqD")))
    assert again[0].fired and len(renv.client.get("/monitor/firings").json()) == 1       # upserted, not duplicated


# ------------------------------------------------------------------------------------------ 503 until E is merged
def test_deploy_is_503_without_a_monitor_and_changes_nothing(make_env):
    env = make_env(disable=("monitor_cls",))
    env.seed_fixture_events(*ALL)
    env.cid = env.new_concept(alpha=0.2)
    _teach_and_calibrate(env)
    rid = env.theft["id"]
    r = env.client.patch(f"/rules/{rid}", json={"status": "deployed", "actions": ["slack"]})
    assert r.status_code == 503 and r.json()["error"].endswith("not available yet")
    got = env.client.get(f"/rules/{rid}").json()
    assert got["status"] == "candidate" and got["actions"] == ["ui"]
    assert env.client.patch(f"/rules/{rid}", json={"status": "selected"}).status_code == 200       # no E needed for that
    assert env.client.patch(f"/rules/{rid}", json={"status": "retired"}).status_code == 200


def test_backtest_and_deploy_are_503_without_calibration(make_env):
    env = make_env(disable=("calibrate",))
    env.seed_fixture_events(*ALL)
    env.cid = env.new_concept()
    _teach_and_calibrate(env, random_labels=False)
    rid = env.theft["id"]
    assert env.client.get(f"/rules/{rid}/backtest").status_code == 503
    assert env.client.patch(f"/rules/{rid}", json={"status": "deployed"}).status_code == 503


def test_rule_ast_in_responses_is_a_valid_rule(renv):
    ast = renv.client.get(f"/rules/{renv.theft['id']}").json()["ast"]
    validate_component("Rule", ast)
    assert Rule.model_validate(ast) == parse(H.THEFT_DSL)
