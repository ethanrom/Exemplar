from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from exemplar.ring import (
    AuthManager,
    InMemoryTokenStore,
    OAuthApp,
    PlaygroundToken,
    RingAuthError,
    StoredAuth,
    compute_nonce,
    decode_jwt_claims,
    generate_pkce,
    nonce_matches,
)

from .conftest import make_jwt

NOW = 1_792_050_000.0  # seconds


# ------------------------------------------------------------------------------------------ JWT / Playground
def test_decode_jwt_claims_without_verification():
    tok = make_jwt(iat=1_792_045_683, exp=1_792_047_483, scope="ava.v1:read")
    c = decode_jwt_claims(tok)
    assert c["iat"] == 1_792_045_683 and c["exp"] == 1_792_047_483 and c["scope"] == "ava.v1:read"


@pytest.mark.parametrize("bad", ["", "abc", "a.b", "a..c", "x.@@@.z"])
def test_decode_jwt_claims_rejects_garbage(bad):
    with pytest.raises(ValueError):
        decode_jwt_claims(bad)


def test_playground_token_times_and_expiry():
    now = [NOW]
    p = PlaygroundToken(make_jwt(iat=int(NOW) - 600, exp=int(NOW) + 1200), clock=lambda: now[0])
    assert p.issued_at_ms == (int(NOW) - 600) * 1000
    assert p.expires_at_ms == (int(NOW) + 1200) * 1000
    assert not p.is_expired
    assert p.seconds_left() == pytest.approx(1200)
    assert p.is_expiring(1300) and not p.is_expiring(1100)
    now[0] = NOW + 1200
    assert p.is_expired
    st = p.status()
    assert st.mode == "playground" and st.connected is False
    assert st.to_api()["expires_at_ms"] == p.expires_at_ms


async def test_playground_token_get_token_and_missing():
    tok = make_jwt(iat=1, exp=2)
    p = PlaygroundToken(tok, clock=lambda: 10.0)
    assert p.is_expired
    assert await p.get_token() == tok          # expired tokens are still returned; the API answers 401
    assert await p.on_unauthorized() is False
    empty = PlaygroundToken()
    assert empty.is_expired and not empty.status().connected
    with pytest.raises(RingAuthError) as ei:
        await empty.get_token()
    assert ei.value.code == "NO_TOKEN"


def test_playground_token_repaste_replaces_and_rejects_non_jwt():
    p = PlaygroundToken(make_jwt(iat=1, exp=100), clock=lambda: 50.0)
    p.set("  " + make_jwt(iat=2, exp=9999) + "\n")
    assert p.expires_at_ms == 9_999_000
    with pytest.raises(ValueError):
        p.set("not-a-token")
    assert p.expires_at_ms == 9_999_000        # unchanged by the failed paste


def test_token_repr_never_leaks():
    tok = make_jwt(iat=1, exp=2)
    assert tok not in repr(PlaygroundToken(tok))
    sa = StoredAuth(mode="oauth", access_token="AAA-secret", refresh_token="RRR-secret")
    assert "secret" not in repr(sa)


# ------------------------------------------------------------------------------------------ AuthManager
def test_auth_manager_paste_persist_and_first_iat():
    store = InMemoryTokenStore()
    m = AuthManager(store, clock=lambda: NOW)
    assert m.status().mode is None and not m.status().connected
    st = m.set_playground_token(make_jwt(iat=int(NOW) - 100, exp=int(NOW) + 1700))
    assert st.mode == "playground" and st.connected
    saved = store.load()
    assert saved.mode == "playground" and saved.access_token and saved.expires_at_ms == (int(NOW) + 1700) * 1000
    first = m.first_issued_at_ms
    m.set_playground_token(make_jwt(iat=int(NOW) + 5, exp=int(NOW) + 1800))
    assert m.first_issued_at_ms == first == (int(NOW) - 100) * 1000   # the consent boundary is the FIRST iat
    with pytest.raises(ValueError):
        m.set_playground_token("garbage")
    m.disconnect()
    assert store.load() is None and not m.status().connected


def test_auth_manager_bootstraps_from_store_then_env():
    fresh = make_jwt(iat=int(NOW) - 10, exp=int(NOW) + 1790)
    stale = make_jwt(iat=int(NOW) - 4000, exp=int(NOW) - 2200)
    # persisted token wins while it's valid
    m = AuthManager(InMemoryTokenStore(PlaygroundToken(fresh, clock=lambda: NOW).to_stored()), clock=lambda: NOW)
    m._bootstrap(stale)
    assert m.status().connected
    # a stale persisted token is replaced by a newer env token
    m2 = AuthManager(InMemoryTokenStore(PlaygroundToken(stale, clock=lambda: NOW).to_stored()), clock=lambda: NOW)
    m2._bootstrap(fresh)
    assert m2.status().connected and m2.status().expires_at_ms == (int(NOW) + 1790) * 1000
    # nothing persisted: env token is used
    m3 = AuthManager(clock=lambda: NOW)
    m3._bootstrap(fresh)
    assert m3.status().connected


async def test_auth_manager_get_token_requires_connection():
    m = AuthManager()
    with pytest.raises(RingAuthError):
        await m.get_token()
    tok = make_jwt(iat=1, exp=2)
    m.set_playground_token(tok)
    assert await m.get_token() == tok


# ------------------------------------------------------------------------------------------ OAuth
def _app(**kw):
    return OAuthApp("cid-123", "csecret-456", clock=kw.pop("clock", lambda: NOW), **kw)


def test_pkce_s256_challenge_matches_verifier():
    v, c = generate_pkce()
    assert 43 <= len(v) <= 128
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert "=" not in c and generate_pkce()[0] != v


def test_build_authorize_url_has_every_parameter():
    req = _app().build_authorize_url("https://app.example/cb")
    u = urlsplit(req.url)
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://account.ring.com/account/integrations/partner-link/authorize"
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q["client_id"] == "cid-123" and q["redirect_uri"] == "https://app.example/cb"
    assert q["response_type"] == "code" and q["scope"] == "ava.v1:read"
    assert q["state"] == req.state and q["code_challenge_method"] == "S256"
    expected = base64.urlsafe_b64encode(hashlib.sha256(req.code_verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expected
    assert "csecret" not in req.url


def _tok_json(access, refresh, expires_in=14400):
    return {"access_token": access, "refresh_token": refresh, "scope": "ava.v1:read", "expires_in": expires_in,
            "token_type": "Bearer"}


@respx.mock
async def test_exchange_code_sends_form_with_pkce_and_stores_tokens():
    route = respx.post("https://oauth.ring.com/oauth/token").mock(
        return_value=httpx.Response(200, json=_tok_json("A1", "R1")))
    store = InMemoryTokenStore()
    app = _app(store=store)
    t = await app.exchange_code("the-code", code_verifier="verifier-xyz", redirect_uri="https://app.example/cb")
    req = route.calls.last.request
    assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
    form = parse_qs(req.content.decode())
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["the-code"]
    assert form["client_id"] == ["cid-123"] and form["client_secret"] == ["csecret-456"]
    assert form["code_verifier"] == ["verifier-xyz"] and form["redirect_uri"] == ["https://app.example/cb"]
    assert t.expires_at_ms == int(NOW * 1000) + 14400 * 1000
    s = store.load()
    assert (s.mode, s.access_token, s.refresh_token) == ("oauth", "A1", "R1")
    assert await app.get_token() == "A1"


@respx.mock
async def test_refresh_rotates_and_stores_both_tokens():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        seen.append(form["refresh_token"][0])
        n = len(seen)
        return httpx.Response(200, json=_tok_json(f"A{n+1}", f"R{n+1}"))

    respx.post("https://oauth.ring.com/oauth/token").mock(side_effect=handler)
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1",
                                          issued_at_ms=0, expires_at_ms=int(NOW * 1000) + 10_000_000))
    app = _app(store=store)
    await app.refresh()
    assert store.load().access_token == "A2" and store.load().refresh_token == "R2"
    await app.refresh()
    assert seen == ["R1", "R2"]                     # the rotated token is used, never the old one
    assert store.load().refresh_token == "R3"


@respx.mock
async def test_refresh_keeps_old_refresh_token_if_response_omits_it():
    respx.post("https://oauth.ring.com/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "A2", "expires_in": 100}))
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1", expires_at_ms=1))
    app = _app(store=store)
    await app.refresh()
    assert store.load().refresh_token == "R1" and store.load().access_token == "A2"


@respx.mock
async def test_get_token_refreshes_early_once_even_when_concurrent():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=_tok_json("A2", "R2"))

    respx.post("https://oauth.ring.com/oauth/token").mock(side_effect=handler)
    # expires in 4 minutes < 5 minute margin -> must refresh BEFORE it actually expires
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1",
                                          expires_at_ms=int(NOW * 1000) + 240_000))
    app = _app(store=store)
    toks = await asyncio.gather(*[app.get_token() for _ in range(5)])
    assert toks == ["A2"] * 5 and len(calls) == 1


@respx.mock
async def test_get_token_does_not_refresh_when_fresh():
    route = respx.post("https://oauth.ring.com/oauth/token").mock(return_value=httpx.Response(500))
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1",
                                          expires_at_ms=int(NOW * 1000) + 3_600_000))
    assert await _app(store=store).get_token() == "A1" and route.call_count == 0


@respx.mock
async def test_refresh_failure_is_a_typed_auth_error():
    respx.post("https://oauth.ring.com/oauth/token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "refresh token used"}))
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1", expires_at_ms=1))
    with pytest.raises(RingAuthError) as ei:
        await _app(store=store).refresh()
    assert ei.value.code == "invalid_grant" and ei.value.status == 400
    assert "R1" not in str(ei.value) and "csecret" not in str(ei.value)


async def test_refresh_without_refresh_token():
    with pytest.raises(RingAuthError) as ei:
        await _app().refresh()
    assert ei.value.code == "NO_REFRESH_TOKEN"


@respx.mock
async def test_on_unauthorized_forces_a_refresh_once():
    route = respx.post("https://oauth.ring.com/oauth/token").mock(
        return_value=httpx.Response(200, json=_tok_json("A2", "R2")))
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1",
                                          expires_at_ms=int(NOW * 1000) + 3_600_000))
    app = _app(store=store)
    assert await app.on_unauthorized() is True and route.call_count == 1
    assert await app.get_token() == "A2"


@respx.mock
async def test_concurrent_401s_trigger_a_single_refresh():
    calls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        await asyncio.sleep(0.01)
        return httpx.Response(200, json=_tok_json("A2", "R2"))

    respx.post("https://oauth.ring.com/oauth/token").mock(side_effect=handler)
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1",
                                          expires_at_ms=int(NOW * 1000) + 3_600_000))
    app = _app(store=store)
    assert await asyncio.gather(*[app.on_unauthorized() for _ in range(4)]) == [True] * 4
    assert len(calls) == 1 and await app.get_token() == "A2"      # the rotated-out R1 was used exactly once


async def test_on_unauthorized_without_a_refresh_token_is_false():
    assert await _app().on_unauthorized() is False


@respx.mock
async def test_account_link_post_then_patch():
    post = respx.post("https://api.amazonvision.com/v1/accounts/me/app-integrations").mock(
        return_value=httpx.Response(200, json={"status": "awaiting"}))
    patch = respx.patch("https://api.amazonvision.com/v1/accounts/me/app-integrations").mock(
        return_value=httpx.Response(200, json={"account_identifier": "u***r@example.test", "status": "completed"}))
    store = InMemoryTokenStore(StoredAuth(mode="oauth", access_token="A1", refresh_token="R1",
                                          expires_at_ms=int(NOW * 1000) + 3_600_000))
    app = _app(store=store)
    r1 = await app.confirm_account_link("u***r@example.test", "nonce-1", access_token="MATCHED")
    assert r1["status"] == "awaiting"
    assert post.calls.last.request.headers["authorization"] == "Bearer MATCHED"
    assert json.loads(post.calls.last.request.content) == {"account_identifier": "u***r@example.test", "nonce": "nonce-1"}
    r2 = await app.complete_account_link()
    assert r2["status"] == "completed"
    assert json.loads(patch.calls.last.request.content) == {"status": "completed"}
    assert patch.calls.last.request.headers["authorization"] == "Bearer A1"


@respx.mock
async def test_account_link_error_is_typed():
    respx.post("https://api.amazonvision.com/v1/accounts/me/app-integrations").mock(
        return_value=httpx.Response(400, json={"errors": [{"status": "400", "code": "INVALID_PAYLOAD",
                                                           "detail": "bad nonce"}]}))
    with pytest.raises(Exception) as ei:
        await _app().confirm_account_link("x", "n", access_token="T")
    assert getattr(ei.value, "code", None) == "INVALID_PAYLOAD"


def test_nonce_helpers_roundtrip():
    n = compute_nonce("1771130906289", "ava1.ring.account.X", "hmac-key")
    assert len(n) == 43 and "=" not in n
    assert nonce_matches(n, "1771130906289", "ava1.ring.account.X", "hmac-key")
    assert not nonce_matches(n, "1771130906290", "ava1.ring.account.X", "hmac-key")
    assert not nonce_matches(n, "1771130906289", "ava1.ring.account.Y", "hmac-key")
