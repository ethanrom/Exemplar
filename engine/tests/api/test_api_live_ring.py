"""Opt-in live checks against the real Developer Playground + Bedrock (EXEMPLAR_LIVE=1; needs a fresh token).

    EXEMPLAR_LIVE=1 EXEMPLAR_DOTENV="/path/to/.env" uv run pytest tests/api/test_api_live_ring.py -s

Spend is capped: at most LIVE_EVENTS events are traced (about $0.0014 each on the fast model). The token is read
through `get_settings()` and never printed.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from exemplar import settings
from exemplar.api import ApiConfig, AppState, create_app
from exemplar.ring import decode_jwt_claims

from . import helpers as H
from .conftest import SchemaClient

LIVE_EVENTS = 3


@pytest.mark.live
def test_playground_history_to_trace_with_the_real_services(tmp_path):
    settings.get_settings.cache_clear()
    s = settings.get_settings()
    if not s.ring_token:
        pytest.skip("no Playground token configured (RING_PLAYGROUND_TOKEN / token file)")
    exp = decode_jwt_claims(s.ring_token).get("exp")
    if exp and exp < time.time() + 60:
        pytest.skip("the Playground token has expired: paste a fresh one")
    state = AppState(settings=s, config=ApiConfig(poll_enabled=False, initial_sync_limit=LIVE_EVENTS))
    with TestClient(create_app(state=state, start_background=False)) as raw:
        c = SchemaClient(raw)
        auth = c.put("/ring/auth", json={"access_token": s.ring_token})
        assert auth.status_code == 200 and auth.json()["connected"] and auth.json()["user_name"]
        assert s.ring_token not in auth.text
        devices = c.get("/ring/devices").json()
        assert len(devices) >= 1 and devices[0]["snapshot"] is True
        n = c.post("/ring/sync").json()["new_events"]
        assert n == LIVE_EVENTS, f"expected {LIVE_EVENTS} imported events, got {n}"
        events = c.get("/events?source=ring").json()["items"]
        assert len(events) == LIVE_EVENTS and all(e["kind"] == "on_demand" and e["sub_type"] == "on_demand" for e in events)
        for e in events:
            ev = H.wait_until(lambda: (lambda d: d if d["trace_status"] in ("ok", "perception_failed") or d["clip_status"] in ("failed", "not_found") else None)(
                c.get(f"/events/{e['id']}").json()), timeout=240, interval=2.0, what=f"trace for {e['id'][-8:]}")
            assert ev["clip_status"] == "ready", ev
            assert ev["has_snapshot"] and ev["trace_status"] == "ok" and ev["summary"], ev
            assert ev["trace"]["context"]["sub_type"] == "on_demand"
            print(f"{e['id'][-8:]}: {ev['summary']}")
        cost = c.get("/monitor/cost").json()
        assert cost["tokens_in"] > 0 and cost["usd_estimate"] < 0.5
        print("cost:", cost)
