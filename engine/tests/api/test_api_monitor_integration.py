"""The API against the REAL stream E (monitor, calibrate) once it is merged; skipped while the modules are stubs.

Stream D is faked here (its `Example` / `Candidate` are duck-typed by E), so these tests need only E.
"""
from __future__ import annotations

import pytest

from exemplar.api import Services

from . import helpers as H

try:
    from exemplar.calibrate import calibrate as real_calibrate
    from exemplar.monitor import ActionRunner, DeployedRule, EventInput, Monitor
    HAVE_E = True
except ImportError:                     # E not merged in this checkout
    HAVE_E = False

pytestmark = pytest.mark.skipif(not HAVE_E, reason="stream E (exemplar.monitor / exemplar.calibrate) is not merged")


@pytest.fixture
def real_env(make_env):
    env = make_env()
    env.state.services = Services(
        perceive=env.perceive, run_cegis=env.cegis, example_cls=H.Example, candidate_cls=H.Candidate,
        build_committee=env.active.build_committee, select_query=env.active.select_query,
        ring_factory=lambda auth: env.ring)                     # calibrate / Monitor / DeployedRule / EventInput: REAL
    env.seed_fixture_events(*H.ALL_FIXTURES)
    env.seed_fixture_events("perception_failed")
    env.cid = env.new_concept(alpha=0.2)
    return H.teach_and_calibrate(env)


def test_backtest_with_real_calibration(real_env):
    bt = real_env.client.get(f"/rules/{real_env.theft['id']}/backtest").json()      # schema-validated by the client
    cal = bt["calibration"]
    assert cal["guarantee"] is True and cal["n_random_neg"] == 7 and cal["tau"] >= 0.0
    assert cal["delta"] > 0 and cal["alpha"] == 0.2
    assert {r["clip_id"] for r in bt["rows"] if r["matched"]} >= {"theft_a", "theft_b"}


def test_real_monitor_fires_drops_and_prunes(real_env):
    rid = real_env.theft["id"]
    assert real_env.client.patch(f"/rules/{rid}", json={"status": "deployed", "actions": ["ui", "slack", "chime"]}).status_code == 200
    real_env.perceive.script["evt-rqA"] = "theft_a"
    H.post_webhook(real_env, "rqA", sub="human")
    H.post_webhook(real_env, "rqB", sub="human")                       # default trace: a package, nobody picks it up
    H.post_webhook(real_env, "rqC", sub="vehicle")                     # a vehicle alert cannot involve a Person
    H.wait_until(lambda: len(real_env.client.get("/monitor/firings").json()) == 3, what="3 firings")
    by_event = {f["event_id"]: f for f in real_env.client.get("/monitor/firings").json()}
    a, b, c = by_event["evt-rqA"], by_event["evt-rqB"], by_event["evt-rqC"]
    assert a["fired"] and a["stage"] == 1 and a["witness"]["rule_id"] == rid and a["witness"]["margin"] > 0
    assert a["actions"][0]["action"] == "ui" and {x["action"] for x in a["actions"]} == {"ui", "slack", "chime"}   # ui runs first
    assert {x["action"]: x["status"] for x in a["actions"]} == {"ui": "ok", "slack": "skipped", "chime": "skipped"}
    assert not b["fired"] and b["stage"] == 1
    assert not c["fired"] and c["stage"] == 0 and c["score"] is None
    cost = real_env.client.get("/monitor/cost").json()
    assert cost["events"] == 3 and cost["stage0_dropped"] == 1 and cost["stage1_scored"] == 2
    types = {e["type"] for e in real_env.state.bus.recent()}
    assert {"rule_fired", "rule_dropped", "action_result", "cost_update"} <= types
    # ingest already paid for the fast traces: the monitor must not have asked for them again or counted them twice
    assert [c["mode"] for c in real_env.perceive.calls_for("evt-rqA")] == ["fast"]
    assert cost["tokens_in"] == 3 * 6400


def test_default_action_runner_is_built_from_the_config(real_env):
    st = real_env.state
    st.services = Services(perceive=real_env.perceive, ring_factory=lambda auth: real_env.ring)
    st.config.slack_webhook_url = "https://hooks.example.test/T/B/X"
    st.config.webhook_out_url = "https://receiver.example.test/hook"
    st.config.webhook_out_secret = "s3cret"
    runner = st.services.make_action_runner(st)
    assert isinstance(runner, ActionRunner)
    assert (runner.slack_url, runner.webhook_url, runner.webhook_secret) == (
        "https://hooks.example.test/T/B/X", "https://receiver.example.test/hook", "s3cret")
    assert runner.chime is None and runner.chime_enabled is False
    st.config.chime_enabled = True
    st.loop = __import__("asyncio").new_event_loop()
    try:
        runner = st.services.make_action_runner(st)
        assert runner.chime_enabled is True and callable(runner.chime)
    finally:
        st.loop.close()
