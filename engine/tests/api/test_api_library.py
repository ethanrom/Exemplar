"""Library: /events, /events/{id}, snapshot + clip (Range), /uploads."""
from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from exemplar.api import Services
from exemplar.perception.sampling import probe

from . import helpers as H


@pytest.fixture
def lib(env):
    """Three fixture events + two Ring events, one concept with two labels."""
    env.connect()
    env.seed_fixture_events("theft_a", "delivery_a", "birds_feeder")
    env.ring.add_event("ava1.ring.history.event.R1", H.T0, 6_000)
    env.ring.add_event("ava1.ring.history.event.R2", H.T0 + 60_000, 6_000)
    env.sync()
    env.wait_trace("ava1.ring.history.event.R1")
    env.wait_trace("ava1.ring.history.event.R2")
    env.cid = env.new_concept()
    assert env.label(env.cid, "theft_a", "pos").status_code == 200
    assert env.label(env.cid, "delivery_a", "neg").status_code == 200
    return env


def test_list_events_newest_first_with_summary_fields(lib):
    items = lib.client.get("/events").json()["items"]
    assert [i["start_ms"] for i in items] == sorted((i["start_ms"] for i in items), reverse=True)
    by_id = {i["id"]: i for i in items}
    assert len(items) == 5
    fx = by_id["fx_theft_a"]
    assert fx["source"] == "fixture" and fx["trace_status"] == "ok" and fx["clip_status"] == "not_found"
    assert fx["summary"].startswith("A person in a hoodie") and fx["has_snapshot"] is False and fx["label"] is None
    ring = by_id["ava1.ring.history.event.R1"]
    assert ring["has_snapshot"] is True and ring["duration_ms"] == 6_000 and ring["sub_type"] == "on_demand"


def test_list_events_label_of_a_concept(lib):
    items = {i["id"]: i for i in lib.client.get(f"/events?concept_id={lib.cid}").json()["items"]}
    assert items["fx_theft_a"]["label"] == {"concept_id": lib.cid, "clip_id": "theft_a", "value": "pos",
                                             "provenance": "example", "weight": 3.0}
    assert items["fx_birds_feeder"]["label"] is None


@pytest.mark.parametrize("flt,expected", [("pos", {"fx_theft_a"}), ("neg", {"fx_delivery_a"}),
                                          ("unlabelled", {"fx_birds_feeder", "ava1.ring.history.event.R1",
                                                          "ava1.ring.history.event.R2"})])
def test_list_events_labelled_filter(lib, flt, expected):
    r = lib.client.get(f"/events?concept_id={lib.cid}&labelled={flt}")
    assert {i["id"] for i in r.json()["items"]} == expected


def test_list_events_source_filter(lib):
    assert {i["source"] for i in lib.client.get("/events?source=fixture").json()["items"]} == {"fixture"}
    assert len(lib.client.get("/events?source=ring").json()["items"]) == 2
    assert lib.client.get("/events?source=upload").json() == {"items": [], "next_cursor": None}


def test_list_events_cursor_pagination_visits_each_event_once(lib):
    seen, cursor, pages = [], None, 0
    while True:
        url = "/events?limit=2" + (f"&cursor={cursor}" if cursor else "")
        body = lib.client.get(url).json()
        seen += [i["id"] for i in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and len(seen) == len(set(seen)) == 5


def test_list_events_validation(lib):
    assert lib.client.get("/events?labelled=pos").status_code == 400                       # needs concept_id
    assert lib.client.get("/events?concept_id=nope").status_code == 404
    assert lib.client.get("/events?limit=501").status_code == 400
    assert lib.client.get("/events?source=cctv").status_code == 400
    r = lib.client.get("/events?cursor=garbage")
    assert r.status_code == 400 and r.json()["code"] == "INVALID_CURSOR"


def test_event_detail_has_trace_and_fallback_trace_text(lib):
    d = lib.client.get(f"/events/fx_theft_a?concept_id={lib.cid}").json()
    assert d["trace"]["clip_id"] == "theft_a" and d["strong_trace"] is None
    assert d["label"]["value"] == "pos"
    try:                                            # stream D's renderer is used once it is installed
        from exemplar.synth import render_trace_text
    except ImportError:
        render_trace_text = None
    if render_trace_text is None:
        assert "picks_up(p1,k1)@high" in d["trace_text"] and "entities: p1:person[hoodie] k1:package[box]" in d["trace_text"]
    else:
        from exemplar.contracts.trace import Trace
        assert d["trace_text"] == render_trace_text(Trace.model_validate(d["trace"]))


def test_event_detail_uses_ds_renderer_when_available(env):
    env.seed_fixture_events("theft_a")
    env.state.services = Services(**{**env.services._o, "render_trace_text": lambda tr: f"RENDERED {tr.clip_id}"})
    assert env.client.get("/events/fx_theft_a").json()["trace_text"] == "RENDERED theft_a"
    env.state.services = Services(**{**env.services._o, "render_trace_text": lambda tr: 1 / 0})
    assert "picks_up" in env.client.get("/events/fx_theft_a").json()["trace_text"]      # renderer failure -> fallback


def test_event_detail_strong_trace(lib):
    clip = "ava1.ring.history.event.R1"
    ctx = lib.state.store.traces.get(clip, "fast").context
    strong = H.as_perceived(H.load_trace("theft_a"), clip_id=clip, source="ring", context=ctx, mode="strong")
    lib.state.store.traces.put(clip, strong, mode="strong")
    d = lib.client.get(f"/events/{clip}").json()
    assert d["strong_trace"]["perception"]["mode"] == "strong" and d["trace"]["perception"]["mode"] == "fast"


def test_event_detail_without_trace(env):
    env.connect()
    env.ring.add_event("ava1.ring.history.event.X", H.T0, 6_000)
    env.ring.video_errors["ava1.ring.history.event.X"] = RuntimeError("boom")
    env.sync()
    H.wait_until(lambda: env.state.store.clips.get("ava1.ring.history.event.X").status == "failed")
    d = env.client.get("/events/ava1.ring.history.event.X").json()
    assert d["trace"] is None and d["strong_trace"] is None and d["trace_text"] is None and d["trace_status"] == "none"


def test_event_404(env):
    for url in ("/events/nope", "/events/nope/snapshot", "/events/nope/clip"):
        r = env.client.get(url)
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_snapshot_jpeg(lib):
    r = lib.client.get("/events/ava1.ring.history.event.R1/snapshot")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content == lib.ring.jpeg
    assert lib.client.get("/events/fx_theft_a/snapshot").status_code == 404                  # fixture: no media


def test_clip_mp4_supports_http_range(lib):
    url = "/events/ava1.ring.history.event.R1/clip"
    full = lib.client.get(url)
    assert full.status_code == 200 and full.headers["content-type"] == "video/mp4"
    assert full.headers.get("accept-ranges") == "bytes" and full.content == lib.ring.video
    part = lib.client.get(url, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == lib.ring.video[:100]
    assert part.headers["content-range"] == f"bytes 0-99/{len(lib.ring.video)}"
    tail = lib.client.get(url, headers={"Range": "bytes=-50"})
    assert tail.status_code == 206 and tail.content == lib.ring.video[-50:]
    assert lib.client.get(url, headers={"Range": f"bytes={len(lib.ring.video) + 10}-"}).status_code == 416
    assert lib.client.get("/events/fx_theft_a/clip").status_code == 404


# ------------------------------------------------------------------------------------------ uploads
ATTR = '"Thief stealing our package" by frollard, CC BY 4.0'
URL = "https://www.youtube.com/watch?v=TfTFu8lGrwk"


def _upload(env, path: Path, **form):
    data = {"attribution": ATTR, "source_url": URL, "window_s": "10", "stride_s": "5", **form}
    with open(path, "rb") as fh:
        return env.client.post("/uploads", files={"file": ("long.mp4", fh, "video/mp4")}, data=data)


def test_upload_cuts_windows_and_traces_each(env, long_video):
    r = _upload(env, long_video)
    assert r.status_code == 202
    items = r.json()
    assert len(items) == 5                                              # starts 0,5,10,15,20 for a 30 s source
    assert all(i["source"] == "upload" and i["kind"] == "upload" and i["attribution"] == ATTR for i in items)
    assert [i["duration_ms"] for i in items] == [10_000] * 5
    for i in items:
        ev = env.wait_trace(i["id"])
        assert ev["clip_status"] == "ready" and ev["has_snapshot"] is True and ev["summary"]
    clip = env.state.store.clips.get(items[0]["id"])
    assert abs(probe(clip.path).duration_s - 10.0) < 0.3
    refs = sorted(env.state.store.clips.get(i["id"]).source_ref for i in items)
    assert refs == [f"youtube:TfTFu8lGrwk@{s}.0+10.0" for s in ("0", "10", "15", "20", "5")]
    c = env.perceive.calls_for(items[0]["id"])[0]
    assert c["source"] == "upload" and c["context"].event_kind == "upload" and c["context"].sub_type is None
    assert c["context"].local_hour is None


def test_upload_is_idempotent_and_never_creates_a_monitor(env, long_video):
    first = _upload(env, long_video).json()
    for i in first:
        env.wait_trace(i["id"])
    again = _upload(env, long_video).json()
    assert sorted(i["id"] for i in again) == sorted(i["id"] for i in first)
    time.sleep(0.3)
    assert env.state.store.events.count("upload") == 5
    assert len(env.perceive.calls) == 5                                  # no second round of perception
    assert H.FakeMonitor.instances == []


def test_upload_short_video_is_one_window(env, tmp_path):
    short = H.make_mp4(tmp_path / "short.mp4", seconds=4.0)
    items = _upload(env, short, window_s="20", stride_s="10").json()
    assert len(items) == 1 and items[0]["duration_ms"] == 4_000


def test_upload_validation(env, long_video, tmp_path):
    assert _upload(env, long_video, attribution="  ").status_code == 400
    assert _upload(env, long_video, window_s="0").status_code == 400
    assert _upload(env, long_video, stride_s="-3").status_code == 400
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video" * 100)
    r = _upload(env, bad)
    assert r.status_code == 400 and r.json()["code"] == "UNREADABLE_VIDEO"
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert _upload(env, empty).status_code == 400
    r = env.client.post("/uploads", files={"file": ("x.mp4", io.BytesIO(b"x"), "video/mp4")})     # attribution missing
    assert r.status_code == 400
    assert not list((env.state.data_dir / "uploads").glob("*.part"))                           # temp files cleaned up
