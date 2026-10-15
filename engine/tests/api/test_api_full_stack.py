"""Integrator test: the whole pipeline through the API with every REAL stream (C, D, E, H) wired by default.

Only Ring and perception are fakes (fixture traces), and the LLM is replaced by stream D's deterministic
TemplateProposer, so this runs offline and free: teach -> candidates -> active question -> random
calibration labels -> backtest with the conformal badge -> deploy -> webhook event -> firing with witness.
"""
from __future__ import annotations

import functools

import pytest

from exemplar.api import Services

from . import helpers as H

synth = pytest.importorskip("exemplar.synth")
agent = pytest.importorskip("exemplar.agent")
pytest.importorskip("exemplar.monitor")
from exemplar.agent.templates import TemplateProposer  # noqa: E402


@pytest.fixture
def full_env(make_env):
    env = make_env()
    env.state.services = Services(
        perceive=env.perceive,
        run_cegis=functools.partial(agent.run_cegis, model=TemplateProposer(), k=4, max_rounds=2),
        ring_factory=lambda auth: env.ring)        # everything else: the real default imports
    env.seed_fixture_events(*H.ALL_FIXTURES)
    env.cid = env.new_concept(alpha=0.2)
    return env


def test_teach_question_calibrate_deploy_fire(full_env):
    env, cid = full_env, full_env.cid
    for clip, v in H.EXAMPLES.items():                               # theft_a, theft_b pos; delivery_a neg
        assert env.label(cid, clip, v).status_code == 200
    run = H.run_teach(env, cid, timeout=180.0)
    assert run["status"] == "done", run

    rules = env.client.get(f"/concepts/{cid}/rules").json()
    assert rules, "real synthesis produced no candidates"
    best = rules[0]
    print("\nLEARNED:", best["english"], "|", best["dsl_text"], "| margin", best["margin"], "| mdl", round(best["mdl"], 1))
    assert best["english"] and best["dsl_text"] and best["margin"] > 0
    assert "?" not in best["dsl_text"]                               # closed rule after slack placement

    q = env.client.get(f"/concepts/{cid}/question")                  # real committee + query selection
    assert q.status_code in (200, 204)
    if q.status_code == 200:
        assert 0.0 <= q.json()["p"] <= 1.0 and q.json()["clip_id"] not in H.EXAMPLES

    drawn = [d["clip_id"] for d in env.client.post(f"/concepts/{cid}/random-sample?n=50&seed=5").json()]
    for c in drawn:                                                  # remaining fixtures are all non-theft
        assert env.label(cid, c, "neg", "random").status_code == 200
    bt = env.client.get(f"/rules/{best['id']}/backtest").json()
    print("CALIBRATION:", bt["calibration"])
    cal = bt["calibration"]
    assert cal["n_random_neg"] == len(drawn) and cal["tau"] >= 0.0
    assert cal["guarantee"] is (len(drawn) >= 4)                     # ceil(1/0.2) - 1 = 4 random negatives
    matched = {r["clip_id"] for r in bt["rows"] if r["matched"]}
    assert {"theft_a", "theft_b"} <= matched and "delivery_a" not in matched

    assert env.client.patch(f"/rules/{best['id']}", json={"status": "deployed", "actions": ["ui"]}).status_code == 200
    env.perceive.script["evt-fs1"] = "theft_b"
    env.perceive.script["evt-fs2"] = "delivery_b"
    H.post_webhook(env, "fs1", sub="human")
    H.post_webhook(env, "fs2", sub="human")
    H.wait_until(lambda: len(env.client.get("/monitor/firings").json()) == 2, timeout=60.0, what="2 firings")
    by_event = {f["event_id"]: f for f in env.client.get("/monitor/firings").json()}
    fired, dropped = by_event["evt-fs1"], by_event["evt-fs2"]
    print("WITNESS:", fired["witness"]["english"], [(s["op"], s["t_start_ms"], s["t_end_ms"], round(s["rho"], 2)) for s in fired["witness"]["spans"]][:4])
    assert fired["fired"] and fired["witness"]["rule_id"] == best["id"] and fired["witness"]["spans"]
    assert fired["witness"]["bindings"] and fired["witness"]["margin"] > 0
    assert not dropped["fired"]
