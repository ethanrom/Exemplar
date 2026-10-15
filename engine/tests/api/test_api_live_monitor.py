"""Live capture (/live/*), monitor stream / cost / firings, eval results."""
from __future__ import annotations

import json
import threading
import time

import pytest

from exemplar.api import ApiConfig
from exemplar.api.cost import usd
from exemplar.perception.sampling import probe

from . import helpers as H
from .conftest import validate_component


def post_frame(env, session, t_ms, jpeg=None, device=H.DEVICE_ID, **kw):
    data = {"session_id": session, "t_ms": str(t_ms)}
    if device:
        data["device_id"] = device
    return env.client.post("/live/frames", data=data, files={"image": ("f.jpg", jpeg or H.make_jpeg((t_ms % 255, 40, 90)), "image/jpeg")}, **kw)


def send_session(env, session, n=10, step=500):
    for i in range(n):
        assert post_frame(env, session, i * step).status_code == 202


# ------------------------------------------------------------------------------------------ live frames
def test_frames_are_stored_per_session(env):
    send_session(env, "s1", n=4)
    d = env.state.data_dir / "live" / "s1"
    assert sorted(p.name for p in d.glob("*.jpg")) == ["000000000.jpg", "000000500.jpg", "000001000.jpg", "000001500.jpg"]


@pytest.mark.parametrize("kw,status", [
    (dict(session="../evil", t_ms=0), 400), (dict(session="bad session", t_ms=0), 400), (dict(session="s", t_ms=-1), 400),
    (dict(session="s", t_ms=0, jpeg=b"GIF89a-not-a-jpeg"), 400)])
def test_frame_validation(env, kw, status):
    r = post_frame(env, kw["session"], kw["t_ms"], kw.get("jpeg"))
    assert r.status_code == status


def test_frame_missing_fields_and_size_limit(make_env):
    env = make_env(config=ApiConfig(poll_enabled=False, max_frame_bytes=2000))
    assert env.client.post("/live/frames", data={"session_id": "s"}, files={"image": ("f.jpg", H.make_jpeg(), "image/jpeg")}).status_code == 400
    r = post_frame(env, "s", 0, jpeg=H.make_jpeg(size=(900, 900)))
    assert r.status_code == 413 and r.json()["code"] == "FRAME_TOO_LARGE"


def test_finish_builds_a_ring_live_clip_and_traces_it(env):
    send_session(env, "s1", n=10)
    r = env.client.post("/live/sessions/s1/finish")
    assert r.status_code == 202 and r.json() == {"event_id": "live_s1"}
    ev = env.wait_trace("live_s1")
    assert ev["source"] == "ring_live" and ev["kind"] == "live" and ev["device_id"] == H.DEVICE_ID
    assert ev["clip_status"] == "ready" and ev["has_snapshot"] is True and ev["summary"]
    clip = env.state.store.clips.get("live_s1")
    assert abs(probe(clip.path).duration_s - 5.0) < 0.35 and clip.duration_ms == 5000
    assert clip.source_ref == "live:s1"
    call = env.perceive.calls_for("live_s1")[0]
    assert call["source"] == "ring_live" and call["context"].event_kind == "live" and call["context"].device_id == H.DEVICE_ID
    assert call["context"].local_hour is not None and call["context"].sub_type is None
    snap = env.client.get("/events/live_s1/snapshot")
    assert snap.status_code == 200 and snap.content[:2] == b"\xff\xd8"
    assert env.client.get("/events/live_s1/clip").headers["content-type"] == "video/mp4"


def test_finish_is_idempotent_and_closes_the_session(env):
    send_session(env, "s1", n=6)
    assert env.client.post("/live/sessions/s1/finish").json()["event_id"] == "live_s1"
    env.wait_trace("live_s1")
    assert env.client.post("/live/sessions/s1/finish").json()["event_id"] == "live_s1"
    assert len(env.perceive.calls_for("live_s1")) == 1 and env.state.store.events.count("ring_live") == 1
    late = post_frame(env, "s1", 99_000)
    assert late.status_code == 409 and late.json()["code"] == "SESSION_FINISHED"


def test_finish_unknown_or_empty_session_is_404(env):
    assert env.client.post("/live/sessions/nope/finish").status_code == 404
    assert env.client.post("/live/sessions/bad%20id/finish").status_code == 400


def test_live_facts_are_published_before_the_monitor_runs(renv):
    renv.client.patch(f"/rules/{renv.theft['id']}", json={"status": "deployed"})
    renv.perceive.script["live_s2"] = "theft_a"
    send_session(renv, "s2", n=8)
    renv.client.post("/live/sessions/s2/finish")
    H.wait_until(lambda: renv.client.get("/monitor/firings").json(), what="firing for the live capture")
    events = [e for e in renv.state.bus.recent() if e.get("event_id") == "live_s2"]
    types = [e["type"] for e in events]
    facts = [e for e in events if e["type"] == "live_facts"]
    assert types[:3] == ["event_ingested", "clip_ready", "trace_ready"]
    assert facts and types.index("live_facts") < types.index("rule_fired")
    assert facts[0]["message"] == "summary at session finish"
    assert {"t_ms", "pred", "args", "conf"} <= set(facts[0]["facts"][0])
    assert any(f["pred"] == "picks_up" for e in facts for f in e["facts"])
    for e in events:
        validate_component("MonitorEvent", e)
    firing = renv.client.get("/monitor/firings").json()[0]
    assert firing["event_id"] == "live_s2" and firing["fired"] is True


# ------------------------------------------------------------------------------------------ SSE
def read_stream(env, path, headers=None, *, until, timeout=10.0):
    """Collect raw SSE lines from a live server until `until(lines)` is true."""
    lines: list[str] = []
    done = threading.Event()

    def run():
        with env.client.stream("GET", path, headers=headers or {}) as r:
            lines.append(f"HTTP {r.status_code} {r.headers.get('content-type')}")
            for line in r.iter_lines():
                lines.append(line)
                if line == "" and until(lines):          # only judge at a frame boundary (blank line)
                    break
        done.set()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return lines, done, t


def test_monitor_stream_pushes_events_with_ids_and_replays_after_last_event_id(make_env):
    env = make_env(serve=True)
    lines, done, _ = read_stream(env, "/monitor/stream", until=lambda ls: sum(1 for l in ls if l.startswith("data:")) >= 3)
    H.wait_until(lambda: env.state.bus.subscribers == 1, what="stream subscriber")
    env.state.bus.emit("event_ingested", event_id="e1", message="one")
    env.state.bus.emit("auth_expiring", message="soon")
    env.state.bus.publish({"type": "rule_fired", "event_id": "e1", "rule_id": "ru_x"})
    assert done.wait(10)
    assert lines[0] == "HTTP 200 text/event-stream; charset=utf-8"
    frames = H_parse(lines)
    assert [f["event"] for f in frames] == ["event_ingested", "auth_expiring", "rule_fired"]
    assert [int(f["id"]) for f in frames] == sorted(int(f["id"]) for f in frames)
    for f in frames:
        validate_component("MonitorEvent", json.loads(f["data"]))
    first_id = int(frames[0]["id"])
    lines2, done2, _ = read_stream(env, "/monitor/stream", headers={"Last-Event-ID": str(first_id)},
                                   until=lambda ls: sum(1 for l in ls if l.startswith("data:")) >= 2)
    assert done2.wait(10)
    assert [f["event"] for f in H_parse(lines2)] == ["auth_expiring", "rule_fired"]       # replayed from the buffer


def test_streams_send_ping_events(make_env):
    env = make_env(serve=True, config=ApiConfig(poll_enabled=False, sse_ping_s=0.2))
    lines, done, _ = read_stream(env, "/monitor/stream", until=lambda ls: "event: ping" in ls)
    assert done.wait(10), lines
    assert "data: {}" in lines


def test_monitor_stream_carries_the_ingest_pipeline(make_env):
    env = make_env(serve=True)
    env.connect()
    lines, done, _ = read_stream(env, "/monitor/stream", until=lambda ls: "event: trace_ready" in ls)
    H.wait_until(lambda: env.state.bus.subscribers == 1)
    env.ring.add_event("ava1.ring.history.event.S1", H.T0, 6_000)
    env.sync()
    assert done.wait(20), lines
    assert [f["event"] for f in H_parse(lines)] == ["event_ingested", "clip_ready", "trace_ready"]


def H_parse(lines):
    return H.parse_sse([l for l in lines if not l.startswith("HTTP ")])


# ------------------------------------------------------------------------------------------ cost / firings / eval
def test_price_table_reproduces_the_measured_costs():
    assert usd("perception_fast", 6400, 1400) == pytest.approx(0.0014, abs=0.0001)
    assert usd("perception_strong", 6200, 1600) == pytest.approx(0.028, abs=0.001)


def test_cost_is_zero_on_an_empty_engine(env):
    c = env.client.get("/monitor/cost").json()
    assert c == {"events": 0, "stage0_dropped": 0, "stage1_scored": 0, "stage2_escalated": 0, "tokens_in": 0,
                 "tokens_out": 0, "usd_estimate": 0, "per_event_usd": 0.0}


def test_cost_without_a_monitor_is_derived_from_firings_and_ledger(env):
    env.seed_fixture_events("theft_a", "delivery_a", "birds_feeder")
    env.cid = env.new_concept()
    env.state.store.rules.insert(rule_id="ru_a", concept_id=env.cid, run_id=None, sketch_text="s", dsl_text="d",
                                 ast_json=json.dumps({}), english="e", holes={}, margin=0.1, mdl=1.0, violated_clip_ids=[])
    for i, (ev, stage) in enumerate([("fx_theft_a", 1), ("fx_delivery_a", 0), ("fx_birds_feeder", 2)]):
        env.state.store.firings.upsert({"id": f"fi_{i}", "rule_id": "ru_a", "event_id": ev, "stage": stage,
                                        "score": 0.1, "tau": 0.0, "fired": False, "witness": None, "actions": [],
                                        "created_at_ms": 1000 + i})
    env.state.store.cost.add("perception_fast", clip_id="theft_a", tokens_in=6400, tokens_out=1400)
    env.state.store.cost.add("perception_strong", clip_id="birds_feeder", tokens_in=6200, tokens_out=1600)
    env.state.store.cost.add("sketch", run_id="r1", tokens_in=500_000, tokens_out=50_000)   # teach cost: not per-event
    c = env.client.get("/monitor/cost").json()
    assert (c["events"], c["stage0_dropped"], c["stage1_scored"], c["stage2_escalated"]) == (3, 1, 1, 1)
    assert (c["tokens_in"], c["tokens_out"]) == (12600, 3000)
    assert c["usd_estimate"] == pytest.approx(0.0014 + 0.028, abs=0.0015) and c["per_event_usd"] == pytest.approx(c["usd_estimate"] / 3, abs=1e-5)


def test_firings_newest_first_with_limit(env):
    env.seed_fixture_events("theft_a", "delivery_a", "birds_feeder")
    env.cid = env.new_concept()
    env.state.store.rules.insert(rule_id="ru_a", concept_id=env.cid, run_id=None, sketch_text="s", dsl_text="d",
                                 ast_json=json.dumps({}), english="e", holes={}, margin=0.1, mdl=1.0, violated_clip_ids=[])
    for i, ev in enumerate(["fx_theft_a", "fx_delivery_a", "fx_birds_feeder"]):
        env.state.store.firings.upsert({"id": f"fi_{i}", "rule_id": "ru_a", "event_id": ev, "stage": 1, "score": 0.2,
                                        "tau": 0.0, "fired": i == 0, "witness": {"rule_id": "ru_a", "clip_id": "theft_a", "score": 0.2,
                                        "bindings": {}, "spans": []} if i == 0 else None,
                                        "actions": [{"action": "ui", "status": "ok", "detail": None}] if i == 0 else [],
                                        "created_at_ms": 1000 + i})
    allf = env.client.get("/monitor/firings").json()
    assert [f["id"] for f in allf] == ["fi_2", "fi_1", "fi_0"]
    assert allf[2]["witness"]["rule_id"] == "ru_a" and allf[2]["actions"][0]["action"] == "ui"
    assert [f["id"] for f in env.client.get("/monitor/firings?limit=2").json()] == ["fi_2", "fi_1"]
    assert env.client.get("/monitor/firings?limit=0").status_code == 400


def test_eval_results_empty_then_served_from_the_data_dir(env):
    empty = env.client.get("/eval/results").json()
    assert empty["rows"] == [] and empty["generated_at"]
    path = env.state.data_dir / "eval"
    path.mkdir()
    doc = {"generated_at": "2026-10-20T12:00:00Z", "alpha": 0.1, "rows": [
        {"concept": "vehicle_dwell", "method": "exemplar", "k": 3, "q": 3, "seed": 0, "f1": 0.8, "precision": 0.9,
         "recall": 0.7, "false_alarm_rate": 0.08}]}
    (path / "results.json").write_text(json.dumps(doc), encoding="utf-8")
    assert env.client.get("/eval/results").json() == doc
    (path / "results.json").write_text("{not json", encoding="utf-8")
    assert env.client.get("/eval/results").json()["rows"] == []
