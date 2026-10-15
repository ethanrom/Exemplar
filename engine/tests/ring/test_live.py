"""Opt-in tests against the real Ring Developer Playground. Run with:

    EXEMPLAR_LIVE=1 EXEMPLAR_DOTENV=... uv run pytest tests/ring/test_live.py -s

Needs a fresh (30 min) Playground token (settings: $RING_PLAYGROUND_TOKEN or the `token` file) and, for
the media tests, at least one simulated event in history. Never prints the token.
"""
from __future__ import annotations

import time

import pytest

from exemplar.ring import AuthManager, RingClient, TimeRangeNotAuthorizedError

pytestmark = pytest.mark.live


@pytest.fixture
async def ring():
    auth = AuthManager.from_settings()
    st = auth.status()
    if not st.connected:
        pytest.skip("no live Playground token (missing or expired)")
    async with RingClient(auth) as c:
        yield c


async def test_users_me_and_devices(ring):
    st = await ring.verify_connection()
    assert st.connected and st.mode == "playground"
    me = await ring.users_me()
    assert me.id.startswith("ava1.ring.account.")
    devices = await ring.list_devices()
    assert devices, "Playground should expose one virtual device"
    d = devices[0]
    assert d.id.startswith("ava1.ring.device.")
    assert d.name and "AVC" in d.codecs and d.snapshot
    assert d.capabilities is not None and d.configurations is not None


async def test_history_paginates_and_media_downloads(ring):
    dev = (await ring.list_devices())[0]
    events = await ring.history_list(dev.id, max_pages=3)
    if not events:
        pytest.skip("no Playground events in history yet - click Simulate")
    ev = next((e for e in events if e.end_ms), events[0])
    assert ev.event_type in {"on_demand", "motion", "ding"} and ev.start_ms > 1_700_000_000_000
    # newest first
    assert [e.start_ms for e in events] == sorted((e.start_ms for e in events), reverse=True)

    clip = await ring.download_event_video(ev, dev.id, grace_s=0)
    assert clip.status in (200, 206) and clip.content_type == "video/mp4"
    assert clip.data[4:8] == b"ftyp" and clip.media_duration_ms
    snap = await ring.download_event_snapshot(ev, dev.id, grace_s=0)
    assert snap.content_type == "image/jpeg" and snap.data[:2] == b"\xff\xd8"
    assert snap.media_origin in {"recording", "snapshot"}


async def test_time_before_consent_is_403(ring):
    dev = (await ring.list_devices())[0]
    with pytest.raises(TimeRangeNotAuthorizedError) as ei:
        await ring.download_snapshot(dev.id, at_ms=1_792_045_683_000 - 3_600_000)
    assert ei.value.status == 403 and ei.value.code == "TIME_RANGE_NOT_AUTHORIZED"
