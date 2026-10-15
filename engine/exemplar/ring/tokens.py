"""Ring token providers.

* `PlaygroundToken` - the Developer Playground's read-only JWT (30 min, `ava.v1:read`). We never verify
  the signature (we don't have the key); we only decode `iat`/`exp` to drive the countdown and to know
  the media consent boundary (`issued_at_ms` of the FIRST token - see docs/FRICTION_LOG.md).
* `OAuthApp` - the real app mode: authorization_code (+PKCE) and refresh_token grants against
  https://oauth.ring.com/oauth/token, refresh-token ROTATION (every refresh returns a new refresh
  token, the old one stops working), and the app-integrations account-link calls.
* `AuthManager` - what FastAPI holds: the "current" provider, swappable at runtime (`PUT /ring/auth`),
  persisted through a `TokenStore` (the API backs it with the `ring_auth` table).

Tokens are secrets: nothing in this module logs or repr()s them.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import urlencode

import httpx

from .errors import RingAuthError, RingError, error_from_response

API_BASE = "https://api.amazonvision.com"
OAUTH_TOKEN_URL = "https://oauth.ring.com/oauth/token"
OAUTH_AUTHORIZE_URL = "https://account.ring.com/account/integrations/partner-link/authorize"
DEFAULT_SCOPE = "ava.v1:read"


# --------------------------------------------------------------------------------------- JWT helpers
def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode a JWT payload WITHOUT verifying it. Raises ValueError if it isn't a JWT."""
    parts = token.strip().split(".")
    if len(parts) != 3 or not all(parts[:2]):
        raise ValueError("not a JWT (expected three dot-separated segments)")
    seg = parts[1]
    try:
        raw = base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))
        claims = json.loads(raw)
    except (ValueError, TypeError) as e:
        raise ValueError("JWT payload is not valid base64url JSON") from e
    if not isinstance(claims, dict):
        raise ValueError("JWT payload is not an object")
    return claims


def _claim_ms(claims: dict[str, Any], key: str) -> int | None:
    v = claims.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v * 1000)


# --------------------------------------------------------------------------------------- status
@dataclass(frozen=True)
class AuthStatus:
    """Mirror of api.yaml `RingAuthStatus` (never contains the token)."""

    mode: str | None            # "playground" | "oauth" | None
    connected: bool
    expires_at_ms: int | None = None
    issued_at_ms: int | None = None
    user_name: str | None = None

    def to_api(self) -> dict[str, Any]:
        return {"mode": self.mode, "connected": self.connected, "expires_at_ms": self.expires_at_ms,
                "issued_at_ms": self.issued_at_ms, "user_name": self.user_name}


@runtime_checkable
class TokenProvider(Protocol):
    async def get_token(self) -> str: ...
    async def on_unauthorized(self) -> bool:
        """Called after a 401. Return True if a new token is available and the call may be retried."""
        ...
    def status(self) -> AuthStatus: ...


# --------------------------------------------------------------------------------------- store
@dataclass(frozen=True)
class StoredAuth:
    """One row of `ring_auth` (schema.sql): the single current credential set."""

    mode: str                       # "playground" | "oauth"
    access_token: str | None = None
    refresh_token: str | None = None
    issued_at_ms: int | None = None
    expires_at_ms: int | None = None
    updated_at_ms: int = 0

    def __repr__(self) -> str:  # never leak tokens through repr/logging
        return (f"StoredAuth(mode={self.mode!r}, access_token={'<set>' if self.access_token else None}, "
                f"refresh_token={'<set>' if self.refresh_token else None}, issued_at_ms={self.issued_at_ms}, "
                f"expires_at_ms={self.expires_at_ms})")


class TokenStore(Protocol):
    """Persistence for the current credentials. Synchronous on purpose (tiny SQLite upsert)."""

    def load(self) -> StoredAuth | None: ...
    def save(self, auth: StoredAuth) -> None: ...
    def clear(self) -> None: ...


class InMemoryTokenStore:
    def __init__(self, initial: StoredAuth | None = None) -> None:
        self._auth = initial

    def load(self) -> StoredAuth | None:
        return self._auth

    def save(self, auth: StoredAuth) -> None:
        self._auth = auth

    def clear(self) -> None:
        self._auth = None


# --------------------------------------------------------------------------------------- Playground
class PlaygroundToken:
    """A pasted Developer Playground token. Valid 30 minutes; there is no refresh."""

    mode = "playground"

    def __init__(self, token: str | None = None, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._token: str | None = None
        self._claims: dict[str, Any] = {}
        if token:
            self.set(token)

    @classmethod
    def from_settings(cls, settings: Any = None, **kw: Any) -> "PlaygroundToken":
        if settings is None:
            from exemplar.settings import get_settings
            settings = get_settings()
        return cls(getattr(settings, "ring_token", None), **kw)

    def set(self, token: str) -> None:
        """Replace the token (the UI's re-paste). Raises ValueError if it isn't a JWT."""
        token = token.strip()
        claims = decode_jwt_claims(token)
        self._token, self._claims = token, claims

    @property
    def has_token(self) -> bool:
        return self._token is not None

    @property
    def issued_at_ms(self) -> int | None:
        return _claim_ms(self._claims, "iat")

    @property
    def expires_at_ms(self) -> int | None:
        return _claim_ms(self._claims, "exp")

    @property
    def is_expired(self) -> bool:
        """True when there is no token or `exp` has passed. Unknown `exp` counts as not expired."""
        return self.is_expiring(0.0)

    def is_expiring(self, within_s: float) -> bool:
        """True when there is no token or it expires within `within_s` seconds."""
        if self._token is None:
            return True
        exp = self.expires_at_ms
        return exp is not None and self._clock() * 1000 >= exp - within_s * 1000

    def seconds_left(self) -> float | None:
        exp = self.expires_at_ms
        return None if exp is None else exp / 1000 - self._clock()

    async def get_token(self) -> str:
        """Return the token even if it has expired (the API will answer 401 and the UI re-prompts)."""
        if self._token is None:
            raise RingAuthError("No Ring Playground token configured", code="NO_TOKEN")
        return self._token

    async def on_unauthorized(self) -> bool:
        return False  # nothing to refresh: the user must paste a new token

    def status(self) -> AuthStatus:
        return AuthStatus(mode=self.mode, connected=self.has_token and not self.is_expired,
                          expires_at_ms=self.expires_at_ms, issued_at_ms=self.issued_at_ms)

    def to_stored(self) -> StoredAuth:
        return StoredAuth(mode="playground", access_token=self._token, issued_at_ms=self.issued_at_ms,
                          expires_at_ms=self.expires_at_ms, updated_at_ms=int(self._clock() * 1000))

    def __repr__(self) -> str:
        return f"PlaygroundToken(set={self.has_token}, expires_at_ms={self.expires_at_ms})"


# --------------------------------------------------------------------------------------- OAuth
@dataclass(frozen=True)
class OAuthTokens:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    scope: str | None = None
    token_type: str = "Bearer"
    issued_at_ms: int = 0
    expires_at_ms: int = 0


@dataclass(frozen=True)
class AuthorizeRequest:
    url: str
    state: str
    code_verifier: str = field(repr=False)


def generate_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge) for S256 PKCE."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def compute_nonce(time_param: str, account_id: str, hmac_key: str) -> str:
    """One-way account-linking nonce: Base64URL(HMAC-SHA256(K_hmac, '<time>:<account_id>')), no padding."""
    mac = hmac.new(hmac_key.encode("utf-8"), f"{time_param}:{account_id}".encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode("ascii")


def nonce_matches(received: str, time_param: str, account_id: str, hmac_key: str) -> bool:
    return hmac.compare_digest(compute_nonce(time_param, account_id, hmac_key), received)


class OAuthApp:
    """Ring app credentials: code exchange, rotating refresh, account-link completion."""

    mode = "oauth"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        store: TokenStore | None = None,
        http: httpx.AsyncClient | None = None,
        token_url: str = OAUTH_TOKEN_URL,
        authorize_url: str = OAUTH_AUTHORIZE_URL,
        api_base: str = API_BASE,
        refresh_margin_s: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("OAuthApp needs client_id and client_secret")
        self.client_id = client_id
        self._client_secret = client_secret
        self.store: TokenStore = store if store is not None else InMemoryTokenStore()
        self._http = http
        self._own_http = http is None
        self.token_url, self.authorize_url, self.api_base = token_url, authorize_url, api_base.rstrip("/")
        self.refresh_margin_s = refresh_margin_s
        self._clock = clock
        self._tokens: OAuthTokens | None = None
        self._loaded = False
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, settings: Any = None, **kw: Any) -> "OAuthApp | None":
        if settings is None:
            from exemplar.settings import get_settings
            settings = get_settings()
        cid, sec = getattr(settings, "ring_client_id", None), getattr(settings, "ring_client_secret", None)
        return cls(cid, sec, **kw) if cid and sec else None

    # ---- http plumbing
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ---- authorize URL (partner-initiated flow)
    def build_authorize_url(self, redirect_uri: str, *, state: str | None = None, scope: str = DEFAULT_SCOPE,
                            code_verifier: str | None = None) -> AuthorizeRequest:
        """URL to send the user to. Keep `state` and `code_verifier` in the session for the callback."""
        if code_verifier is None:
            code_verifier, challenge = generate_pkce()
        else:
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        state = state or secrets.token_urlsafe(16)
        q = urlencode({
            "client_id": self.client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": scope, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        })
        return AuthorizeRequest(url=f"{self.authorize_url}?{q}", state=state, code_verifier=code_verifier)

    # ---- token endpoint
    async def _token_request(self, form: dict[str, str]) -> OAuthTokens:
        form = {**form, "client_id": self.client_id, "client_secret": self._client_secret}
        try:
            r = await self._client().post(self.token_url, data=form,
                                          headers={"Accept": "application/json"})
        except httpx.TransportError as e:
            raise RingAuthError(f"OAuth token endpoint unreachable: {type(e).__name__}") from e
        if r.status_code != 200:
            err = error_from_response(r.status_code, r.text, r.headers, step="oauth")
            # keep the OAuth error code (invalid_grant, ...) but always surface it as an auth failure
            raise RingAuthError(err.message, status=r.status_code, code=err.code, title=err.title,
                                detail=err.detail, request_id=err.request_id, step="oauth")
        try:
            body = r.json()
            access = body["access_token"]
        except (ValueError, KeyError, TypeError) as e:
            raise RingAuthError("OAuth token response was malformed", status=r.status_code, step="oauth") from e
        now_ms = int(self._clock() * 1000)
        expires_in = float(body.get("expires_in") or 0)
        return OAuthTokens(access_token=access, refresh_token=body.get("refresh_token"),
                           scope=body.get("scope"), token_type=body.get("token_type") or "Bearer",
                           issued_at_ms=now_ms, expires_at_ms=now_ms + int(expires_in * 1000))

    def _remember(self, tokens: OAuthTokens, previous_refresh: str | None = None) -> OAuthTokens:
        # Rotation: the response carries a NEW refresh token. If a server ever omits it, keep the old one.
        if tokens.refresh_token is None and previous_refresh:
            tokens = replace(tokens, refresh_token=previous_refresh)
        self._tokens, self._loaded = tokens, True
        self.store.save(StoredAuth(mode="oauth", access_token=tokens.access_token,
                                   refresh_token=tokens.refresh_token, issued_at_ms=tokens.issued_at_ms,
                                   expires_at_ms=tokens.expires_at_ms, updated_at_ms=int(self._clock() * 1000)))
        return tokens

    async def exchange_code(self, code: str, *, code_verifier: str | None = None,
                            redirect_uri: str | None = None) -> OAuthTokens:
        """authorization_code grant (+PKCE). Codes expire after ~60 s: exchange immediately."""
        form = {"grant_type": "authorization_code", "code": code}
        if code_verifier:
            form["code_verifier"] = code_verifier
        if redirect_uri:
            form["redirect_uri"] = redirect_uri
        async with self._lock:
            return self._remember(await self._token_request(form))

    def _load(self) -> OAuthTokens | None:
        if not self._loaded:
            self._loaded = True
            s = self.store.load()
            if s and s.mode == "oauth" and s.access_token:
                self._tokens = OAuthTokens(access_token=s.access_token, refresh_token=s.refresh_token,
                                           issued_at_ms=s.issued_at_ms or 0, expires_at_ms=s.expires_at_ms or 0)
        return self._tokens

    async def refresh(self, *, force: bool = True, stale_access_token: str | None = None) -> OAuthTokens:
        """refresh_token grant. Serialised: a rotated-out refresh token must never be replayed.

        `stale_access_token` (used after a 401): skip the grant if someone else already replaced it."""
        async with self._lock:
            cur = self._load()
            if cur is None or not cur.refresh_token:
                raise RingAuthError("No Ring refresh token available - link the account again",
                                    code="NO_REFRESH_TOKEN")
            if stale_access_token is not None and cur.access_token != stale_access_token:
                return cur
            if not force and not self._needs_refresh(cur):
                return cur  # another task refreshed while we waited for the lock
            new = await self._token_request({"grant_type": "refresh_token", "refresh_token": cur.refresh_token})
            return self._remember(new, previous_refresh=cur.refresh_token)

    def _needs_refresh(self, t: OAuthTokens) -> bool:
        return bool(t.expires_at_ms) and self._clock() * 1000 >= t.expires_at_ms - self.refresh_margin_s * 1000

    async def get_token(self) -> str:
        cur = self._load()
        if cur is None:
            raise RingAuthError("Ring account is not linked", code="NO_TOKEN")
        if self._needs_refresh(cur) and cur.refresh_token:
            cur = await self.refresh(force=False)
        return cur.access_token

    async def on_unauthorized(self) -> bool:
        cur = self._load()
        if cur is None or not cur.refresh_token:
            return False
        await self.refresh(force=True, stale_access_token=cur.access_token)
        return True

    def status(self) -> AuthStatus:
        cur = self._load()
        if cur is None:
            return AuthStatus(mode=self.mode, connected=False)
        expired = bool(cur.expires_at_ms) and self._clock() * 1000 >= cur.expires_at_ms
        # connected as long as we can still get a token (refreshable) or the access token is live
        return AuthStatus(mode=self.mode, connected=(not expired) or bool(cur.refresh_token),
                          expires_at_ms=cur.expires_at_ms or None, issued_at_ms=cur.issued_at_ms or None)

    # ---- account linking (app-integrations)
    async def _integrations(self, method: str, body: dict[str, Any], access_token: str | None) -> dict[str, Any]:
        token = access_token or await self.get_token()
        try:
            r = await self._client().request(method, f"{self.api_base}/v1/accounts/me/app-integrations",
                                             json=body, headers={"Authorization": f"Bearer {token}"})
        except httpx.TransportError as e:
            raise RingError(f"app-integrations unreachable: {type(e).__name__}") from e
        if r.status_code >= 300:
            raise error_from_response(r.status_code, r.text, r.headers, step="request")
        try:
            return r.json()
        except ValueError:
            return {}

    async def confirm_account_link(self, account_identifier: str, nonce: str, *,
                                   access_token: str | None = None) -> dict[str, Any]:
        """One-way linking step 1: POST {account_identifier, nonce} -> {"status": "awaiting"}.
        `access_token` is the token of the user whose nonce matched (defaults to our current one)."""
        return await self._integrations("POST", {"account_identifier": account_identifier, "nonce": nonce},
                                        access_token)

    async def complete_account_link(self, account_identifier: str | None = None, *,
                                    access_token: str | None = None) -> dict[str, Any]:
        """Step 2 (mandatory): PATCH {"status": "completed"} (partner-initiated flow: pass account_identifier)."""
        body: dict[str, Any] = {"status": "completed"}
        if account_identifier:
            body["account_identifier"] = account_identifier
        return await self._integrations("PATCH", body, access_token)

    def __repr__(self) -> str:
        return f"OAuthApp(client_id={self.client_id!r}, linked={self._load() is not None})"


# --------------------------------------------------------------------------------------- manager
class AuthManager:
    """The 'current' credential. Implements `TokenProvider`; swap providers at runtime.

    Startup order (`from_settings`): persisted credentials in the store > Playground token from
    settings (`RING_PLAYGROUND_TOKEN` / `token` file) > OAuth app creds without a link (not connected).
    """

    def __init__(self, store: TokenStore | None = None, *, oauth: OAuthApp | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.store: TokenStore = store if store is not None else InMemoryTokenStore()
        self.oauth = oauth
        self._clock = clock
        self._provider: TokenProvider | None = None
        self.user_name: str | None = None
        # earliest iat seen this process: Playground media before it is TIME_RANGE_NOT_AUTHORIZED
        self.first_issued_at_ms: int | None = None

    @classmethod
    def from_settings(cls, settings: Any = None, store: TokenStore | None = None, **kw: Any) -> "AuthManager":
        if settings is None:
            from exemplar.settings import get_settings
            settings = get_settings()
        oauth = OAuthApp.from_settings(settings, store=store)
        mgr = cls(store, oauth=oauth, **kw)
        if oauth is not None:
            oauth.store = mgr.store
        mgr._bootstrap(getattr(settings, "ring_token", None))
        return mgr

    def _bootstrap(self, env_token: str | None) -> None:
        saved = self.store.load()
        if saved and saved.mode == "oauth" and self.oauth is not None:
            self._provider = self.oauth
            return
        if saved and saved.mode == "playground" and saved.access_token:
            try:
                self._provider = PlaygroundToken(saved.access_token, clock=self._clock)
                self._note_issued()
                # a newer token in the environment wins over a stale persisted one
                if env_token and self._provider.is_expired:  # type: ignore[union-attr]
                    self.set_playground_token(env_token, persist=False)
                return
            except ValueError:
                pass
        if env_token:
            try:
                self.set_playground_token(env_token, persist=False)
            except ValueError:
                pass

    def _note_issued(self) -> None:
        iat = getattr(self._provider, "issued_at_ms", None)
        if iat is not None and (self.first_issued_at_ms is None or iat < self.first_issued_at_ms):
            self.first_issued_at_ms = iat

    # ---- mutations
    def set_playground_token(self, token: str, *, persist: bool = True) -> AuthStatus:
        """`PUT /ring/auth`. Raises ValueError for something that isn't a JWT."""
        p = PlaygroundToken(token, clock=self._clock)
        self._provider = p
        self._note_issued()
        self.user_name = None
        if persist:
            self.store.save(p.to_stored())
        return self.status()

    def use_oauth(self) -> AuthStatus:
        if self.oauth is None:
            raise RingAuthError("RING_CLIENT_ID / RING_CLIENT_SECRET are not configured", code="NO_OAUTH_APP")
        self._provider = self.oauth
        return self.status()

    def disconnect(self) -> None:
        self._provider = None
        self.user_name = None
        self.store.clear()

    # ---- TokenProvider
    async def get_token(self) -> str:
        if self._provider is None:
            raise RingAuthError("Ring is not connected - paste a Playground token", code="NO_TOKEN")
        return await self._provider.get_token()

    async def on_unauthorized(self) -> bool:
        return False if self._provider is None else await self._provider.on_unauthorized()

    def status(self) -> AuthStatus:
        if self._provider is None:
            return AuthStatus(mode=None, connected=False)
        st = self._provider.status()
        return replace(st, user_name=self.user_name)

    @property
    def mode(self) -> str | None:
        return self.status().mode

    def __repr__(self) -> str:
        return f"AuthManager(mode={self.mode!r}, connected={self.status().connected})"
