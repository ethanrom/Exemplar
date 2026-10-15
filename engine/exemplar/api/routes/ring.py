"""/ring/*: connection state, OAuth, devices, history sync, webhook ingest."""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from exemplar.ring import RingAuthError, RingError, parse_webhook

from ..errors import ApiError, BadRequest, error_body, ring_error, short_error
from ..state import AppState
from .deps import get_state

log = logging.getLogger("exemplar.api.ring")
router = APIRouter(tags=["ring"])

OAUTH_STATE_TTL_S = 600.0


class TokenBody(BaseModel):
    access_token: str


@router.get("/ring/auth")
def get_auth(st: AppState = Depends(get_state)) -> dict[str, Any]:
    """Current Ring auth state. Never contains the token."""
    return st.auth.status().to_api()


@router.put("/ring/auth")
async def put_auth(body: TokenBody, st: AppState = Depends(get_state)) -> dict[str, Any]:
    """Paste a Developer Playground token: store it, prove it with `GET /v1/users/me`, start syncing."""
    try:
        st.auth.set_playground_token(body.access_token)
    except ValueError as e:
        raise BadRequest(f"that is not a Ring Playground token: {e}", "INVALID_TOKEN") from e
    try:
        await st.ring().verify_connection()
    except RingAuthError as e:
        st.auth.disconnect()
        raise ApiError(400, f"Ring rejected the token ({e.status or 'auth error'}): expired or revoked? "
                            "Paste a fresh one from the Developer Playground.", e.code or "TOKEN_REJECTED") from e
    except RingError as e:          # transport / 5xx: the token may be fine, keep it and let the poller retry
        log.warning("could not verify the Ring token right now: %s", short_error(e))
    st.pipeline.kick_sync()
    return st.auth.status().to_api()


@router.get("/ring/oauth/start", name="oauth_start", status_code=302)
def oauth_start(request: Request, st: AppState = Depends(get_state)) -> RedirectResponse:
    oauth = st.auth.oauth
    if oauth is None:
        raise BadRequest("Ring OAuth is not configured: set RING_CLIENT_ID and RING_CLIENT_SECRET in .env "
                         "(the Playground token flow works without them)", "OAUTH_NOT_CONFIGURED")
    redirect_uri = str(request.url_for("oauth_callback"))
    req = oauth.build_authorize_url(redirect_uri)
    now = time.time()
    st.oauth_pending = {k: v for k, v in st.oauth_pending.items() if now - v[2] < OAUTH_STATE_TTL_S}
    st.oauth_pending[req.state] = (req.code_verifier, redirect_uri, now)
    return RedirectResponse(req.url, status_code=302)


@router.get("/ring/oauth/callback", name="oauth_callback", status_code=302)
async def oauth_callback(code: str, state: str | None = None, st: AppState = Depends(get_state)) -> RedirectResponse:
    oauth = st.auth.oauth
    if oauth is None:
        raise BadRequest("Ring OAuth is not configured: set RING_CLIENT_ID and RING_CLIENT_SECRET in .env",
                         "OAUTH_NOT_CONFIGURED")
    verifier = redirect_uri = None
    if state is not None:
        pending = st.oauth_pending.pop(state, None)
        if pending is None or time.time() - pending[2] > OAUTH_STATE_TTL_S:
            raise BadRequest("unknown or expired OAuth state: start the link again from /ring/oauth/start",
                             "INVALID_STATE")
        verifier, redirect_uri, _ = pending
    try:
        await oauth.exchange_code(code, code_verifier=verifier, redirect_uri=redirect_uri)
    except RingError as e:
        raise ApiError(400, f"Ring did not accept the authorization code: {e.message}", e.code or "OAUTH_FAILED") from e
    st.auth.use_oauth()
    st.pipeline.kick_sync()
    return RedirectResponse(st.config.ui_url, status_code=302)


@router.get("/ring/devices")
async def list_devices(st: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    if not st.auth.status().connected:
        raise ApiError(401, "Ring is not connected: paste a Developer Playground token", "NO_TOKEN")
    try:
        devices = await st.pipeline.devices(refresh=True)
    except RingError as e:
        raise ring_error(e) from e
    return [d.to_api() for d in devices]


@router.post("/ring/sync", status_code=202)
async def sync_history(st: AppState = Depends(get_state)) -> dict[str, int]:
    """Poll the event history now. New events are registered here; clips download and trace in the background."""
    try:
        n = await st.pipeline.sync_history()
    except RingError as e:
        raise ring_error(e) from e
    return {"new_events": n}


@router.post("/ring/webhook-events", status_code=202)
async def ingest_webhook_event(request: Request, st: AppState = Depends(get_state)) -> Any:
    """Called by apps/web after it verified X-Signature on the raw body. Dedupes on `meta.request_id`."""
    raw = await request.body()
    try:
        wh = parse_webhook(raw)
    except ValueError as e:
        raise BadRequest(str(e), "INVALID_WEBHOOK") from e
    if not st.store.webhooks.claim(wh.request_id, wh.event_type):
        return JSONResponse(error_body(f"request_id {wh.request_id} was already processed", "DUPLICATE"), status_code=409)
    row = st.pipeline.register_webhook(wh)
    if row is not None:
        st.pipeline.submit(row.id)
    return {"status": "queued", "event_id": row.id if row else None}
