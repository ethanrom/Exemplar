"""/health, /ring/*: auth, OAuth, devices, sync, webhook ingest."""
from __future__ import annotations

import json

import pytest

from exemplar.ring import RingAuthError, RingTransportError, sign_body

from . import helpers as H


def test_health(env):
    r = env.client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["version"]


def test_unknown_path_is_a_json_error(env):
    r = env.client.get("/nope")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


# ---------------------------------------------------------------------------------------------- auth
def test_auth_starts_disconnected(env):
    body = env.client.get("/ring/auth").json()
    assert body["connected"] is False and body["mode"] is None


def test_put_auth_connects_and_never_returns_the_token(env):
    token = H.fresh_jwt(30)
    r = env.client.put("/ring/auth", json={"access_token": token})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "playground" and body["connected"] is True
    assert body["expires_at_ms"] and body["issued_at_ms"]
    assert token not in r.text and token not in env.client.get("/ring/auth").text
    assert env.ring.token_checked == 1                      # verify_connection ran


def test_put_auth_persists_token_in_ring_auth_table(env):
    env.connect()
    stored = env.state.store.auth.load()
    assert stored is not None and stored.mode == "playground" and stored.access_token


def test_put_auth_rejects_non_jwt(env):
    r = env.client.put("/ring/auth", json={"access_token": "not-a-token"})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_TOKEN"
    assert env.client.get("/ring/auth").json()["connected"] is False


def test_put_auth_missing_field_is_400(env):
    r = env.client.put("/ring/auth", json={})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_PAYLOAD"


def test_put_auth_ring_rejects_token_disconnects(env):
    env.ring.verify_error = RingAuthError("bad token", status=401)
    r = env.client.put("/ring/auth", json={"access_token": H.fresh_jwt()})
    assert r.status_code == 400 and "Ring rejected" in r.json()["error"]
    assert env.client.get("/ring/auth").json()["connected"] is False
    assert env.state.store.auth.load() is None


def test_put_auth_transport_error_keeps_token(env):
    env.ring.verify_error = RingTransportError("Server disconnected")
    r = env.client.put("/ring/auth", json={"access_token": H.fresh_jwt()})
    assert r.status_code == 200 and r.json()["connected"] is True


def test_expired_token_is_not_connected(env):
    r = env.client.put("/ring/auth", json={"access_token": H.make_jwt(1_700_000_000, 1_700_001_800)})
    assert r.status_code == 200 and r.json()["connected"] is False


# ---------------------------------------------------------------------------------------------- oauth
def test_oauth_start_without_credentials_is_a_clear_400(env):
    r = env.client.get("/ring/oauth/start", follow_redirects=False)
    assert r.status_code == 400
    assert r.json()["code"] == "OAUTH_NOT_CONFIGURED" and "RING_CLIENT_ID" in r.json()["error"]


def test_oauth_callback_without_credentials_is_400(env):
    r = env.client.get("/ring/oauth/callback?code=abc", follow_redirects=False)
    assert r.status_code == 400 and r.json()["code"] == "OAUTH_NOT_CONFIGURED"


def test_oauth_callback_requires_code(env):
    assert env.client.get("/ring/oauth/callback", follow_redirects=False).status_code == 400


@pytest.fixture
def oauth_env(make_env, monkeypatch):
    monkeypatch.setenv("RING_CLIENT_ID", "client-id")
    monkeypatch.setenv("RING_CLIENT_SECRET", "client-secret")
    from exemplar import settings
    settings.get_settings.cache_clear()
    return make_env()


def test_oauth_start_redirects_to_ring_with_pkce(oauth_env):
    r = oauth_env.client.get("/ring/oauth/start", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://account.ring.com/") and "code_challenge_method=S256" in loc
    assert "redirect_uri=http%3A%2F%2Ftestserver%2Fring%2Foauth%2Fcallback" in loc
    assert len(oauth_env.state.oauth_pending) == 1


def test_oauth_callback_unknown_state_is_400(oauth_env):
    r = oauth_env.client.get("/ring/oauth/callback?code=abc&state=forged", follow_redirects=False)
    assert r.status_code == 400 and r.json()["code"] == "INVALID_STATE"


def test_oauth_callback_exchanges_code_and_redirects_to_ui(oauth_env):
    oauth_env.client.get("/ring/oauth/start", follow_redirects=False)
    state_param = next(iter(oauth_env.state.oauth_pending))
    seen = {}

    async def fake_exchange(code, *, code_verifier=None, redirect_uri=None):
        seen.update(code=code, verifier=code_verifier, redirect=redirect_uri)

    oauth_env.state.auth.oauth.exchange_code = fake_exchange
    r = oauth_env.client.get(f"/ring/oauth/callback?code=the-code&state={state_param}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == oauth_env.state.config.ui_url
    assert seen["code"] == "the-code" and seen["verifier"] and seen["redirect"].endswith("/ring/oauth/callback")
    assert oauth_env.state.auth.mode == "oauth"
    assert not oauth_env.state.oauth_pending                 # state is single-use


def test_oauth_callback_ring_error_is_400(oauth_env):
    oauth_env.client.get("/ring/oauth/start", follow_redirects=False)
    state_param = next(iter(oauth_env.state.oauth_pending))

    async def boom(*a, **k):
        raise RingAuthError("invalid_grant", status=400, code="invalid_grant")

    oauth_env.state.auth.oauth.exchange_code = boom
    r = oauth_env.client.get(f"/ring/oauth/callback?code=x&state={state_param}", follow_redirects=False)
    assert r.status_code == 400 and r.json()["code"] == "invalid_grant"


# ---------------------------------------------------------------------------------------------- devices / sync
def test_devices_requires_connection(env):
    r = env.client.get("/ring/devices")
    assert r.status_code == 401 and r.json()["code"] == "NO_TOKEN"


def test_devices_lists_playground_device(env):
    env.connect()
    r = env.client.get("/ring/devices")
    assert r.status_code == 200
    assert r.json() == [{"id": H.DEVICE_ID, "name": "Playground Device", "online": True, "image_url": None,
                         "codecs": ["h264"], "snapshot": True, "chime": False}]


def test_sync_without_events_returns_zero(env):
    env.connect()
    assert env.sync() == 0


def test_sync_ring_auth_error_is_401(env):
    env.connect()
    env.ring.history_error = RingAuthError("expired", status=401)
    r = env.client.post("/ring/sync")
    assert r.status_code == 401


# ---------------------------------------------------------------------------------------------- webhook
def _webhook(env, name: str):
    doc = json.loads((H.WEBHOOK_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return env.client.post("/ring/webhook-events", content=doc["body"], headers={"Content-Type": "application/json"})


def test_webhook_motion_creates_event_and_dedupes(env):
    r = _webhook(env, "motion_vehicle")
    assert r.status_code == 202 and r.json()["event_id"] == "evt-req-0002"
    ev = env.state.store.events.get("evt-req-0002")
    assert ev.source == "ring" and ev.kind == "motion" and ev.sub_type == "vehicle"
    assert ev.start_ms == 1792048103109 and ev.device_id == "ava1.ring.device.FIXTUREDEVICE0001"
    dup = _webhook(env, "motion_vehicle")
    assert dup.status_code == 409 and dup.json()["code"] == "DUPLICATE"
    assert env.state.store.events.count("ring") == 1


def test_webhook_button_press_maps_to_ding(env):
    assert _webhook(env, "button_press").status_code == 202
    ev = env.state.store.events.get("evt-req-0003")
    assert ev.kind == "ding" and ev.sub_type == "ding"


def test_webhook_lifecycle_events_are_accepted_without_an_event_row(env):
    r = _webhook(env, "app_integration_added")
    assert r.status_code == 202 and r.json()["event_id"] is None
    assert env.state.store.events.count() == 0


def test_webhook_garbage_is_400(env):
    r = env.client.post("/ring/webhook-events", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["code"] == "INVALID_WEBHOOK"
    r = env.client.post("/ring/webhook-events", json={"meta": {}, "data": {}})
    assert r.status_code == 400


def test_webhook_dedupe_survives_in_the_table(env):
    _webhook(env, "motion_human")
    assert env.state.store.webhooks.claim("req-0001", "motion_detected") is False


def test_signed_body_roundtrip_helper_is_consistent():
    body = b'{"a":1}'
    assert sign_body(body, "k").startswith("sha256=")
