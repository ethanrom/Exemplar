"""Ingest pipeline: history poll / webhook -> event -> clip -> snapshot -> fast perception -> trace -> ledger."""
from __future__ import annotations

import json
import time

import httpx
import pytest
import respx

from exemplar.api import ApiConfig
from exemplar.perception import PerceptionBackendError
from exemplar.ring import (AuthManager, MediaNotFoundError, RetryPolicy, RingClient, TimeRangeNotAuthorizedError)

from . import helpers as H

EV1, EV2 = "ava1.ring.history.event.ONE", "ava1.ring.history.event.TWO"


def _add_two(env):
    env.ring.add_event(EV1, H.T0, 31_700)
    env.ring.add_event(EV2, H.T0 + 120_000, 21_500)


def test_sync_ingests_playground_events_end_to_end(env):
    env.connect()
    _add_two(env)
    assert env.sync() == 2
    for eid in (EV1, EV2):
        ev = env.wait_trace(eid)
        assert ev["source"] == "ring" and ev["kind"] == "on_demand" and ev["sub_type"] == "on_demand"
        assert ev["device_id"] == H.DEVICE_ID and ev["clip_status"] == "ready" and ev["has_snapshot"] is True
        assert ev["summary"] and ev["trace"]["status"] == "ok" and ev["trace_text"]
    assert env.sync() == 0                                      # nothing new on the next poll
    assert len(env.perceive.calls) == 2


def test_live_feed_message_names_the_camera_not_its_id(env):
    """The Live feed shows `event_ingested.message` verbatim: the device name, never (a tail of) the Ring device id."""
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.sync()
    env.wait_trace(EV1)
    msgs = [e["message"] for e in env.state.bus.recent() if e["type"] == "event_ingested" and e["event_id"] == EV1]
    assert msgs == ["On-demand clip on Playground Device"]
    assert H.DEVICE_ID[-8:] not in msgs[0]
    H.post_webhook(env, "wh1", sub="human")                     # a webhook before any device listing was cached: no name, no id
    unnamed = [e["message"] for e in env.state.bus.recent() if e["type"] == "event_ingested" and e["event_id"] == "evt-wh1"]
    assert unnamed and all(H.DEVICE_ID[-8:] not in m for m in unnamed)


def test_media_files_are_stored_under_the_data_dir(env):
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.sync()
    env.wait_trace(EV1)
    clip = env.state.store.clips.get(EV1)
    assert clip.status == "ready" and clip.sha256 and clip.duration_ms == 6_000
    from pathlib import Path
    assert Path(clip.path).read_bytes() == env.ring.video and Path(clip.path).parent == env.state.data_dir / "clips"
    assert Path(clip.snapshot_path).read_bytes() == env.ring.jpeg
    assert (env.state.data_dir / "snapshots").is_dir() and (env.state.data_dir / "live").is_dir()
    assert (env.state.data_dir / "uploads").is_dir()


def test_trace_context_is_filled_at_ingest(env):
    """Playground events: sub_type on_demand, event_kind, local time in the device's zone (CA -> Pacific)."""
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.sync()
    env.wait_trace(EV1)
    ctx = env.perceive.calls_for(EV1)[0]["context"]
    assert ctx.sub_type == "on_demand" and ctx.event_kind == "on_demand"
    assert ctx.device_id == H.DEVICE_ID and ctx.started_at_ms == H.T0
    assert (ctx.local_hour, ctx.weekday) == (0, 3)              # 07:08 UTC = 00:08 PDT, Thursday
    call = env.perceive.calls_for(EV1)[0]
    assert call["source"] == "ring" and call["mode"] == "fast"
    stored = env.state.store.traces.get(EV1, "fast")
    assert stored.context.sub_type == "on_demand"


def test_winter_event_uses_standard_time(env):
    env.connect()
    jan = 1768000000000                      # 2026-01-09T23:06:40Z -> 15:06 PST (UTC-8), a Friday
    env.ring.add_event(EV1, jan, 6_000)
    env.sync()
    env.wait_trace(EV1)
    ctx = env.perceive.calls_for(EV1)[0]["context"]
    assert (ctx.local_hour, ctx.weekday) == (15, 4)


def test_cost_ledger_written_once_and_skipped_when_cached(env):
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.ring.add_event(EV2, H.T0 + 60_000, 6_000)
    env.perceive.cached_ids.add(EV2)
    env.sync()
    env.wait_trace(EV1)
    env.wait_trace(EV2)
    totals = env.state.store.cost.totals()
    assert totals["perception_fast"] == {"calls": 1, "tokens_in": 6400, "tokens_out": 1400}
    cost = env.client.get("/monitor/cost").json()
    assert cost["tokens_in"] == 6400 and cost["tokens_out"] == 1400 and cost["usd_estimate"] > 0


def test_perception_failed_trace_is_stored_and_visible(env):
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.perceive.script[EV1] = "FAILED"
    env.sync()
    ev = env.wait_trace(EV1, "perception_failed")
    assert ev["summary"] is None and ev["trace"]["status"] == "perception_failed"
    assert ev["trace"]["error"] and ev["trace_text"] is None
    assert env.state.store.traces.primary_row(EV1).status == "perception_failed"


def test_backend_outage_leaves_clip_untraced_and_the_next_sync_retries(env):
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.perceive.script[EV1] = PerceptionBackendError("Bedrock unavailable")
    env.sync()
    H.wait_until(lambda: env.state.store.clips.get(EV1).error, what="clip.error after backend failure")
    ev = env.client.get(f"/events/{EV1}").json()
    assert ev["trace_status"] == "none" and ev["clip_status"] == "ready"
    assert "perception unavailable" in env.state.store.clips.get(EV1).error
    del env.perceive.script[EV1]                                # backend is back
    env.sync()
    env.wait_trace(EV1)
    assert env.state.store.clips.get(EV1).error is None


def test_bedrock_not_configured_is_shown_instead_of_reading_forever(env):
    """No Bedrock setup: the event reads perception_failed with a plain-language reason (Library card and detail),
    not "Reading clip..." forever; once the setup is fixed the next sync reads the clip."""
    from exemplar.perception import PerceptionNotConfigured
    from exemplar.store import PERCEPTION_UNCONFIGURED
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.perceive.script[EV1] = PerceptionNotConfigured("CLAUDE_AWS_FAST_MODEL is not configured (.env)")
    env.sync()
    ev = env.wait_trace(EV1, "perception_failed")
    assert ev["clip_status"] == "ready" and ev["summary"] == PERCEPTION_UNCONFIGURED
    assert ev["trace"]["status"] == "perception_failed" and ev["trace"]["error"] == PERCEPTION_UNCONFIGURED
    assert ev["trace_text"] is None and "CLAUDE_AWS_*" in PERCEPTION_UNCONFIGURED
    row = next(i for i in env.client.get("/events").json()["items"] if i["id"] == EV1)
    assert (row["trace_status"], row["summary"]) == ("perception_failed", PERCEPTION_UNCONFIGURED)
    assert env.state.store.clips.get(EV1).error == PERCEPTION_UNCONFIGURED
    assert [c.id for c in env.state.store.clips.awaiting_perception()] == [EV1]
    del env.perceive.script[EV1]                                # Bedrock is set up
    env.sync()
    ev = env.wait_trace(EV1)
    assert ev["summary"] and ev["summary"] != PERCEPTION_UNCONFIGURED and ev["trace"]["status"] == "ok"
    assert env.state.store.clips.get(EV1).error is None


def test_unreadable_media_marks_clip_failed(env):
    from exemplar.perception import SamplingError
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.perceive.script[EV1] = SamplingError("ffmpeg could not decode")
    env.sync()
    H.wait_until(lambda: env.state.store.clips.get(EV1).status == "failed", what="clip failed")
    assert "unreadable" in env.state.store.clips.get(EV1).error


def test_download_forbidden_and_missing_media_are_recorded(env):
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.ring.add_event(EV2, H.T0 + 60_000, 6_000)
    env.ring.video_errors[EV1] = TimeRangeNotAuthorizedError("before consent", status=403, code="TIME_RANGE_NOT_AUTHORIZED")
    env.ring.video_errors[EV2] = MediaNotFoundError("nothing recorded", status=416, code="MEDIA_NOT_FOUND")
    env.sync()
    H.wait_until(lambda: env.state.store.clips.get(EV1).status == "failed", what="EV1 failed")
    H.wait_until(lambda: env.state.store.clips.get(EV2).status == "not_found", what="EV2 not_found")
    assert "TIME_RANGE_NOT_AUTHORIZED" in env.state.store.clips.get(EV1).error
    assert env.client.get(f"/events/{EV1}").json()["trace_status"] == "none"
    assert env.perceive.calls == []
    types = [e["type"] for e in env.state.bus.recent()]
    assert types.count("error") == 2


def test_snapshot_failure_falls_back_to_a_frame_of_the_clip(env):
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.ring.snapshot_errors[EV1] = MediaNotFoundError("no snapshot", status=416)
    env.sync()
    ev = env.wait_trace(EV1)
    assert ev["has_snapshot"] is True
    r = env.client.get(f"/events/{EV1}/snapshot")
    assert r.status_code == 200 and r.content[:2] == b"\xff\xd8" and r.content != env.ring.jpeg


def test_at_most_two_perception_calls_run_concurrently(env):
    env.connect()
    env.perceive.delay_s = 0.25
    for i in range(5):
        env.ring.add_event(f"ava1.ring.history.event.N{i}", H.T0 + i * 60_000, 6_000)
    assert env.sync() == 5
    for i in range(5):
        env.wait_trace(f"ava1.ring.history.event.N{i}")
    assert env.perceive.max_active == 2


def test_monitor_stream_events_cover_the_pipeline_in_order(env):
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.sync()
    env.wait_trace(EV1)
    seq = [e["type"] for e in env.state.bus.recent() if e.get("event_id") == EV1]
    assert seq == ["event_ingested", "clip_ready", "trace_ready"]
    assert all(e["at_ms"] > 0 for e in env.state.bus.recent())


def test_first_sync_is_capped_and_newest_first(make_env):
    env = make_env(config=ApiConfig(poll_enabled=False, clip_grace_s=0.0, initial_sync_limit=3))
    env.connect()
    for i in range(6):
        env.ring.add_event(f"ava1.ring.history.event.C{i}", H.T0 + i * 60_000, 6_000)
    assert env.sync() == 3
    ids = {e["id"] for e in env.client.get("/events").json()["items"]}
    assert ids == {f"ava1.ring.history.event.C{i}" for i in (3, 4, 5)}


def test_events_are_deduped_across_polls_and_late_arrivals_are_found(env):
    env.connect()
    env.ring.add_event(EV2, H.T0 + 120_000, 6_000)
    assert env.sync() == 1
    env.ring.add_event(EV1, H.T0 + 60_000, 6_000)                # surfaces late (Playground lists events 27-44 s later)
    assert env.sync() == 1
    assert env.sync() == 0


# ------------------------------------------------------------------------------------------ webhooks
def _post_webhook(env, *, request_id, etype="motion_detected", sub=None, ts=H.T0, device=H.DEVICE_ID, eid=None):
    data = {"id": eid or f"evt-{request_id}", "type": etype,
            "attributes": {"source": device, "source_type": "devices", "timestamp": ts}}
    if sub:
        data["subType"] = sub
    body = {"meta": {"version": "1.1", "time": "2026-10-15T07:08:25Z", "request_id": request_id, "account_id": "acct"},
            "data": data}
    return env.client.post("/ring/webhook-events", content=json.dumps(body), headers={"Content-Type": "application/json"})


def test_webhook_event_runs_the_same_pipeline_with_ring_context(env):
    r = _post_webhook(env, request_id="rq1", sub="human")
    assert r.status_code == 202
    ev = env.wait_trace("evt-rq1")
    assert ev["kind"] == "motion" and ev["sub_type"] == "human" and ev["clip_status"] == "ready"
    ctx = env.perceive.calls_for("evt-rq1")[0]["context"]
    assert (ctx.sub_type, ctx.event_kind, ctx.device_id, ctx.started_at_ms) == ("human", "motion", H.DEVICE_ID, H.T0)
    assert (ctx.local_hour, ctx.weekday) == (0, 3)
    assert _post_webhook(env, request_id="rq1", sub="human").status_code == 409
    assert len(env.perceive.calls) == 1


def test_webhook_clip_is_requested_with_an_assumed_length(env):
    _post_webhook(env, request_id="rq2", etype="button_press")
    ev = env.wait_trace("evt-rq2")
    assert ev["kind"] == "ding" and ev["sub_type"] == "ding"
    clip = env.state.store.clips.get("evt-rq2")
    assert clip.duration_ms == 10_000                            # webhook_assumed_clip_s


def test_poll_hit_next_to_a_webhook_event_is_the_same_physical_event(env):
    env.connect()
    _post_webhook(env, request_id="rq3", sub="vehicle", ts=H.T0 + 1_500)
    env.wait_trace("evt-rq3")
    env.ring.add_event("ava1.ring.history.event.SAME", H.T0, 6_000)
    assert env.sync() == 0
    assert env.state.store.events.count("ring") == 1


# ------------------------------------------------------------------------------------------ background tasks
def test_poller_ingests_without_an_explicit_sync(make_env):
    env = make_env(start_background=True, config=ApiConfig(poll_enabled=True, poll_interval_s=0.1, clip_grace_s=0.0))
    env.connect()
    env.ring.add_event(EV1, H.T0, 6_000)
    env.wait_trace(EV1)


def test_poller_idles_while_disconnected(make_env):
    env = make_env(start_background=True, config=ApiConfig(poll_enabled=True, poll_interval_s=0.05, clip_grace_s=0.0))
    env.ring.add_event(EV1, H.T0, 6_000)
    time.sleep(0.4)
    assert env.state.store.events.count() == 0 and not [c for c in env.ring.calls if c[0] == "history"]


def test_auth_expiring_is_announced_once_five_minutes_before(make_env):
    env = make_env(start_background=True, config=ApiConfig(poll_enabled=False, auth_check_interval_s=0.05))
    env.connect(minutes=30)
    time.sleep(0.3)
    assert not [e for e in env.state.bus.recent() if e["type"] == "auth_expiring"]
    env.connect(minutes=4)
    H.wait_until(lambda: [e for e in env.state.bus.recent() if e["type"] == "auth_expiring"], what="auth_expiring")
    time.sleep(0.3)
    assert len([e for e in env.state.bus.recent() if e["type"] == "auth_expiring"]) == 1


# ------------------------------------------------------------------------------------------ real client + HTTP mock
def test_clip_download_retries_416_and_425_through_stream_a(make_env, video_bytes, jpeg_bytes):
    """The real RingClient against mocked Ring HTTP: 416 -> 425 -> 303 -> 200 for the video."""
    async def no_sleep(_: float) -> None:
        return None

    holder = {}

    def factory(auth: AuthManager) -> RingClient:
        holder["client"] = RingClient(auth, retry=RetryPolicy(base_delay_s=0.0), sleep=no_sleep, wall_clock=lambda: 9e9)
        return holder["client"]

    env = make_env(ring_factory=factory)
    page = json.loads(open(H.FIXTURE_TRACES.parent.parent / "ring" / "fixtures" / "history_page_real.json", encoding="utf-8").read())
    first = page["data"][0]
    eid, dev = first["id"], first["relationships"]["source"]["data"]["id"]
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.amazonvision.com/v1/users/me").respond(
            200, json={"data": {"id": "u", "attributes": {"first_name": "Play", "last_name": "Ground"}}})
        mock.get("https://api.amazonvision.com/v1/devices").respond(200, json={"data": [
            {"type": "devices", "id": dev, "attributes": {"name": "Playground Device"}}]})
        mock.get(url__regex=r".*/v1/devices/.*/location").respond(200, json={"data": {"attributes": {"country": "US", "state": "CA"}}})
        mock.get(url__regex=r".*/v1/history/devices/.*/events.*").respond(200, json={"data": [first]})
        video_post = mock.post(url__regex=r".*/media/video/download").mock(side_effect=[
            httpx.Response(416, json={"errors": [{"status": "416", "code": "MEDIA_NOT_FOUND", "detail": "not yet"}]}),
            httpx.Response(425, json={"errors": [{"status": "425", "code": "RECORDING_NOT_READY", "detail": "wait"}]}),
            httpx.Response(303, headers={"location": "https://download.example.test/v.mp4"})])
        mock.post(url__regex=r".*/media/image/download").respond(303, headers={"location": "https://download.example.test/s.jpg"})
        mock.get("https://download.example.test/v.mp4").respond(200, content=video_bytes, headers={
            "content-type": "video/mp4", "x-media-duration": "31700"})
        mock.get("https://download.example.test/s.jpg").respond(200, content=jpeg_bytes, headers={"content-type": "image/jpeg"})
        env.connect()
        assert env.sync() == 1
        ev = env.wait_trace(eid)
        assert ev["clip_status"] == "ready" and ev["sub_type"] == "on_demand" and ev["has_snapshot"] is True
        assert video_post.call_count == 3
        assert all("authorization" not in c.request.headers for c in mock.calls if c.request.url.host == "download.example.test")
