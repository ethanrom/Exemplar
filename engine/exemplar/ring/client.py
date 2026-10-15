"""Async Ring (Amazon Vision) API client. Server-side only: the API blocks browser CORS.

Retry policy:
* 429 -> wait `Retry-After`, 500/503 and transport errors (`RemoteProtocolError: Server disconnected`
  was seen while polling) -> exponential backoff.
* Media downloads additionally retry 416 MEDIA_NOT_FOUND / 425 RECORDING_NOT_READY for ~2 min.
* Never retried: 406 (IP block), any 403 (incl. TIME_RANGE_NOT_AUTHORIZED), 400, 404, 422.
* One 401 triggers a token refresh when the provider can (OAuth), then a single re-send.
Clock and sleep are injectable so tests run instantly.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Sequence
from urllib.parse import parse_qsl, urlsplit

import httpx

from .errors import (
    MEDIA_RETRYABLE,
    RETRYABLE,
    FeatureDisabledError,
    RateLimitedError,
    RingAuthError,
    RingError,
    RingTransportError,
    error_from_response,
)
from .tokens import API_BASE, AuthManager, AuthStatus, PlaygroundToken, TokenProvider

log = logging.getLogger("exemplar.ring")

MOTION_SUBTYPES = ("human", "vehicle", "other_motion")
MAX_VIDEO_MS = 900_000
MAX_LATEST_RANGE_MS = 24 * 3600 * 1000


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff configuration. Delays: base * 2**n, capped at `max_delay_s`; 429 uses Retry-After."""

    api_max_attempts: int = 5
    api_budget_s: float = 90.0
    media_max_attempts: int = 30
    media_budget_s: float = 120.0          # "~2 min" for 416/425 while the recording materialises
    base_delay_s: float = 2.0
    max_delay_s: float = 30.0
    max_retry_after_s: float = 120.0       # a Retry-After beyond this is surfaced instead of slept


# ------------------------------------------------------------------------------------------- models
@dataclass(frozen=True)
class RingUser:
    id: str
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = field(default=None, repr=False)

    @property
    def display_name(self) -> str | None:
        n = " ".join(p for p in (self.first_name, self.last_name) if p)
        return n or None


@dataclass(frozen=True)
class RingDevice:
    id: str
    name: str
    image_url: str | None = None
    online: bool | None = None
    codecs: tuple[str, ...] = ()
    snapshot: bool = False
    chime: bool = False
    status: dict[str, Any] | None = field(default=None, repr=False)
    capabilities: dict[str, Any] | None = field(default=None, repr=False)
    configurations: dict[str, Any] | None = field(default=None, repr=False)
    location_id: str | None = None

    def to_api(self) -> dict[str, Any]:
        """api.yaml `Device`."""
        return {"id": self.id, "name": self.name, "online": self.online, "image_url": self.image_url,
                "codecs": list(self.codecs), "snapshot": self.snapshot, "chime": self.chime}


@dataclass(frozen=True)
class RingEvent:
    """A history event. `sub_type` is NOT in the API; it is only set by `history_tagged`."""

    id: str
    event_type: str                 # motion | on_demand | ding
    start_ms: int
    end_ms: int | None
    device_id: str | None = None
    is_third_party_reviewed: bool = False
    sub_type: str | None = None     # human | vehicle | other_motion (motion events only)

    @property
    def duration_ms(self) -> int | None:
        return None if self.end_ms is None else max(0, self.end_ms - self.start_ms)

    @classmethod
    def from_json(cls, item: dict[str, Any], device_id: str | None = None) -> "RingEvent":
        a = item.get("attributes") or {}
        src = (((item.get("relationships") or {}).get("source") or {}).get("data") or {}).get("id")
        return cls(id=item["id"], event_type=a.get("event_type") or "unknown", start_ms=int(a["start"]),
                   end_ms=int(a["end"]) if a.get("end") is not None else None, device_id=src or device_id,
                   is_third_party_reviewed=bool(a.get("is_third_party_reviewed")))


@dataclass(frozen=True)
class MediaResult:
    data: bytes = field(repr=False)
    content_type: str | None
    status: int                          # 200, or 206 for partial video
    media_timestamp_ms: int | None       # x-media-timestamp: actual start
    media_duration_ms: int | None        # x-media-duration (video)
    media_origin: str | None             # x-media-origin: recording | snapshot (image)
    request_id: str | None = None

    @property
    def partial(self) -> bool:
        return self.status == 206

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.data)
        return p


def _int_or_none(v: str | None) -> int | None:
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def _attrs(doc: dict[str, Any]) -> dict[str, Any]:
    data = doc.get("data")
    return (data.get("attributes") if isinstance(data, dict) else None) or {}


# ------------------------------------------------------------------------------------------- client
class RingClient:
    def __init__(
        self,
        token: TokenProvider | str | None = None,
        *,
        base: str = API_BASE,
        http: httpx.AsyncClient | None = None,
        retry: RetryPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        wall_clock: Callable[[], float] = time.time,
        chime_enabled: bool = False,
        timeout_s: float = 30.0,
        media_timeout_s: float = 180.0,
    ) -> None:
        if token is None:
            token = AuthManager.from_settings()
        elif isinstance(token, str):
            token = PlaygroundToken(token)
        self.token: TokenProvider = token
        self.base = base.rstrip("/")
        self.retry = retry or RetryPolicy()
        self._clock, self._sleep, self._wall = clock, sleep, wall_clock
        self.chime_enabled = chime_enabled
        self._http = http
        self._own_http = http is None
        self._timeout_s, self._media_timeout_s = timeout_s, media_timeout_s

    # ---- lifecycle
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            # NO default Authorization header: pre-signed media URLs must be fetched without it.
            self._http = httpx.AsyncClient(timeout=self._timeout_s, follow_redirects=False)
        return self._http

    async def aclose(self) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> "RingClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---- retry engine
    def _delay(self, err: RingError, attempt: int) -> float:
        p = self.retry
        if isinstance(err, RateLimitedError) and err.retry_after is not None:
            return err.retry_after
        return min(p.max_delay_s, p.base_delay_s * (2 ** attempt))

    async def _retrying(self, attempt_fn: Callable[[], Awaitable[Any]], *, media: bool = False,
                        retry: bool = True) -> Any:
        """Run `attempt_fn` until it succeeds or the policy is exhausted; re-raises the last typed error."""
        p = self.retry
        max_attempts = p.media_max_attempts if media else p.api_max_attempts
        budget = p.media_budget_s if media else p.api_budget_s
        retryable = RETRYABLE + (MEDIA_RETRYABLE if media else ())
        t0 = self._clock()
        refreshed = False
        attempt = 0
        while True:
            try:
                return await attempt_fn()
            except RingAuthError as e:
                if e.status == 401 and not refreshed and await self.token.on_unauthorized():
                    refreshed = True
                    continue
                raise
            except retryable as e:
                if not retry:
                    raise
                attempt += 1
                delay = self._delay(e, attempt - 1)
                over = (isinstance(e, RateLimitedError) and e.retry_after is not None
                        and e.retry_after > p.max_retry_after_s)
                if attempt >= max_attempts or over or (self._clock() - t0) + delay > budget:
                    raise
                log.info("ring retry %d after %.1fs (%s %s)", attempt, delay, type(e).__name__, e.code or e.status)
                await self._sleep(delay)

    async def _send(self, method: str, url: str, *, auth: bool, step: str | None = None,
                    timeout: float | None = None, **kw: Any) -> httpx.Response:
        headers = dict(kw.pop("headers", None) or {})
        if auth:
            headers["Authorization"] = f"Bearer {await self.token.get_token()}"
        if timeout is not None:
            kw["timeout"] = timeout
        try:
            return await self._client().request(method, url, headers=headers, **kw)
        except httpx.TransportError as e:
            raise RingTransportError(f"{type(e).__name__}: {e}", cause=e, step=step) from e

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.base}{path}"

    # ---- JSON helpers
    async def _get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async def attempt() -> dict[str, Any]:
            r = await self._send("GET", self._url(path_or_url), auth=True, params=params, step="request")
            if r.status_code != 200:
                raise error_from_response(r.status_code, r.text, r.headers, step="request")
            try:
                return r.json()
            except ValueError as e:
                raise RingError("Ring returned a non-JSON body", status=r.status_code, step="request") from e

        return await self._retrying(attempt)

    # ---- users / devices
    async def verify_connection(self) -> AuthStatus:
        """GET /v1/users/me to prove the token works; records the user's name on an AuthManager.
        Raises RingAuthError for a bad/expired token. Use after `PUT /ring/auth`."""
        me = await self.users_me()
        if isinstance(self.token, AuthManager):
            self.token.user_name = me.display_name
        return self.token.status()

    async def users_me(self) -> RingUser:
        d = (await self._get_json("/v1/users/me")).get("data") or {}
        a = d.get("attributes") or {}
        return RingUser(id=d.get("id", ""), first_name=a.get("first_name"), last_name=a.get("last_name"),
                        email=a.get("email"))

    async def list_devices(self, include: str | None = "status,capabilities,configurations") -> list[RingDevice]:
        doc = await self._get_json("/v1/devices", {"include": include} if include else None)
        included: dict[tuple[str, str], dict[str, Any]] = {}
        for inc in doc.get("included") or []:
            if isinstance(inc, dict) and "id" in inc:
                included[(inc.get("type", ""), inc["id"])] = inc.get("attributes") or {}
        out: list[RingDevice] = []
        for d in doc.get("data") or []:
            rel = d.get("relationships") or {}

            def related(name: str, rtype: str) -> dict[str, Any] | None:
                ref = ((rel.get(name) or {}).get("data") or {})
                rid = ref.get("id")
                return included.get((ref.get("type", rtype), rid)) if rid else None

            status = related("status", "device-status")
            caps = related("capabilities", "device-capabilities")
            conf = related("configurations", "device-configurations")
            a = d.get("attributes") or {}
            video = (caps or {}).get("video") or {}
            audio = (caps or {}).get("audio") or {}
            enh = ((caps or {}).get("image_enhancements") or {}).get("configurations") or []
            loc = ((rel.get("location") or {}).get("data") or {}).get("id")
            out.append(RingDevice(
                id=d["id"], name=a.get("name") or a.get("description") or "Ring device",
                image_url=a.get("image_url"), online=(status or {}).get("online") if status else None,
                codecs=tuple(video.get("codecs") or ()), snapshot=bool(video) or "snapshot" in enh,
                chime="chime.play" in (audio.get("supported_actions") or ()),
                status=status, capabilities=caps, configurations=conf, location_id=loc))
        return out

    async def device_status(self, device_id: str) -> dict[str, Any]:
        return _attrs(await self._get_json(f"/v1/devices/{device_id}/status"))

    async def device_capabilities(self, device_id: str) -> dict[str, Any]:
        return _attrs(await self._get_json(f"/v1/devices/{device_id}/capabilities"))

    async def device_configurations(self, device_id: str) -> dict[str, Any]:
        return _attrs(await self._get_json(f"/v1/devices/{device_id}/configurations"))

    async def device_location(self, device_id: str) -> dict[str, Any]:
        return _attrs(await self._get_json(f"/v1/devices/{device_id}/location"))

    # ---- history
    async def history(self, device_id: str, event_types: str | Sequence[str] | None = None, *,
                      since_ms: int | None = None, max_pages: int | None = 50) -> AsyncIterator[RingEvent]:
        """Events newest-first, following `links.next` (relative URL carrying `page[key]`).

        Stops on an empty `data` page even when `links.next` is present (the API keeps emitting a
        cursor forever), when a page adds nothing new, at `max_pages`, or - with `since_ms` - once a
        page contains only events that started before it.
        """
        types = ",".join(event_types) if event_types and not isinstance(event_types, str) else event_types
        url: str = f"/v1/history/devices/{device_id}/events"
        params: dict[str, Any] | None = {"event_types": types} if types else None
        seen: set[str] = set()
        pages = 0
        while url:
            doc = await self._get_json(url, params)
            pages += 1
            items = doc.get("data") or []
            if not items:
                return
            fresh = 0
            all_old = True
            for item in items:
                ev = RingEvent.from_json(item, device_id)
                if ev.id in seen:
                    continue
                seen.add(ev.id)
                fresh += 1
                if since_ms is not None and ev.start_ms < since_ms:
                    continue
                all_old = False
                yield ev
            if fresh == 0 or (since_ms is not None and all_old):
                return
            nxt = (doc.get("links") or {}).get("next")
            if not nxt or (max_pages is not None and pages >= max_pages):
                return
            url = nxt
            # links.next normally repeats the filters; re-add them if a server only sends the cursor
            if types and "event_types" not in dict(parse_qsl(urlsplit(nxt).query, keep_blank_values=True)):
                params = {"event_types": types}
            else:
                params = None

    async def history_list(self, device_id: str, event_types: str | Sequence[str] | None = None,
                           **kw: Any) -> list[RingEvent]:
        return [e async for e in self.history(device_id, event_types, **kw)]

    async def history_tagged(self, device_id: str, *, since_ms: int | None = None,
                             subtypes: Sequence[str] = MOTION_SUBTYPES) -> list[RingEvent]:
        """All events with `sub_type` filled in for motion events (workaround): one unfiltered
        query plus one `motion.<sub>` query per subtype. The Playground ignores the filter, so only
        events whose own `event_type` is `motion` are tagged - `on_demand` stays untagged."""
        import dataclasses
        events = {e.id: e async for e in self.history(device_id, since_ms=since_ms)}
        for sub in subtypes:
            async for e in self.history(device_id, f"motion.{sub}", since_ms=since_ms):
                cur = events.get(e.id)
                if cur is not None and cur.event_type == "motion" and cur.sub_type is None:
                    events[e.id] = dataclasses.replace(cur, sub_type=sub)
        return sorted(events.values(), key=lambda e: e.start_ms, reverse=True)

    # ---- media
    async def _media(self, kind: str, device_id: str, body: dict[str, Any]) -> MediaResult:
        """POST .../media/{kind}/download -> 303 -> GET Location (no Authorization). Errors can come
        from either step; the whole two-step is retried together (a pre-signed URL is single-use-ish)."""
        post_url = self._url(f"/v1/devices/{device_id}/media/{kind}/download")

        async def attempt() -> MediaResult:
            r = await self._send("POST", post_url, auth=True, json=body, step="request")
            if r.status_code != 303:
                if r.status_code < 400:
                    raise RingError(f"Unexpected media response (expected 303)", status=r.status_code, step="request")
                raise error_from_response(r.status_code, r.text, r.headers, step="request")
            loc = r.headers.get("location")
            if not loc:
                raise RingError("303 without a Location header", status=303, step="request")
            target = str(httpx.URL(post_url).join(loc))
            if not target.startswith(("https://", "http://")):
                raise RingError("Refusing non-http(s) media Location", status=303, step="request")
            g = await self._send("GET", target, auth=False, step="download",  # NO bearer token here
                                 timeout=self._media_timeout_s)  # Playground renders on demand: 25-50 s seen
            if g.status_code not in (200, 206):
                raise error_from_response(g.status_code, g.text, g.headers, step="download")
            h = g.headers
            return MediaResult(
                data=g.content, content_type=h.get("content-type"), status=g.status_code,
                media_timestamp_ms=_int_or_none(h.get("x-media-timestamp")),
                media_duration_ms=_int_or_none(h.get("x-media-duration")),
                media_origin=h.get("x-media-origin"),
                request_id=h.get("x-request-id") or r.headers.get("x-request-id"))

        return await self._retrying(attempt, media=True)

    async def download_video(self, device_id: str, start_ms: int, duration_ms: int, *,
                             codec: str | None = None, frame_rate: int | None = None,
                             width: int | None = None, height: int | None = None,
                             audio: bool = False) -> MediaResult:
        if not 1 <= duration_ms <= MAX_VIDEO_MS:
            raise ValueError(f"duration_ms must be 1..{MAX_VIDEO_MS}")
        body: dict[str, Any] = {"timestamp": int(start_ms), "duration": int(duration_ms)}
        vopts: dict[str, Any] = {}
        if codec:
            vopts["codec"] = codec
        if frame_rate:
            vopts["frame_rate"] = frame_rate
        if width and height:
            vopts["resolution"] = {"width": width, "height": height}
        if vopts:
            body["video_options"] = vopts
        if audio:
            body["audio_options"] = {"audio_enabled": True}
        return await self._media("video", device_id, body)

    async def download_snapshot(self, device_id: str, at_ms: int | None = None, *,
                                latest_in_range: tuple[int, int | None] | None = None,
                                image_format: str | None = None, width: int | None = None,
                                height: int | None = None) -> MediaResult:
        """`at_ms` -> {"type":"at_timestamp"} (+-10 s tolerance, see x-media-timestamp);
        `latest_in_range=(start_ms, end_ms|None)` -> {"type":"latest_in_range"} (window <= 24 h)."""
        if (at_ms is None) == (latest_in_range is None):
            raise ValueError("pass exactly one of at_ms or latest_in_range")
        if at_ms is not None:
            body: dict[str, Any] = {"type": "at_timestamp", "timestamp": int(at_ms)}  # epoch ms (ISO -> opaque 403)
        else:
            start, end = latest_in_range  # type: ignore[misc]
            body = {"type": "latest_in_range", "start_timestamp": int(start)}
            if end is not None:
                if end - start > MAX_LATEST_RANGE_MS:
                    raise ValueError("latest_in_range window cannot exceed 24 hours")
                body["end_timestamp"] = int(end)
        iopts: dict[str, Any] = {}
        if image_format:
            iopts["format"] = image_format
        if width and height:
            iopts["resolution"] = {"width": width, "height": height}
        if iopts:
            body["image_options"] = iopts
        return await self._media("image", device_id, body)

    async def wait_until_ready(self, event: RingEvent, grace_s: float = 5.0) -> None:
        """Wait until clip end + 5 s before downloading (a no-op for Playground history,
        which only lists an event after it has ended)."""
        if event.end_ms is None:
            return
        remaining = (event.end_ms / 1000 + grace_s) - self._wall()
        if remaining > 0:
            await self._sleep(remaining)

    async def download_event_video(self, event: RingEvent, device_id: str | None = None, *,
                                   grace_s: float = 5.0, **opts: Any) -> MediaResult:
        await self.wait_until_ready(event, grace_s)
        dur = event.duration_ms or 10_000
        return await self.download_video(device_id or event.device_id or "", event.start_ms,
                                         max(1, min(dur, MAX_VIDEO_MS)), **opts)

    async def download_event_snapshot(self, event: RingEvent, device_id: str | None = None, *,
                                      grace_s: float = 5.0, **opts: Any) -> MediaResult:
        await self.wait_until_ready(event, grace_s)
        return await self.download_snapshot(device_id or event.device_id or "", at_ms=event.start_ms, **opts)

    # ---- chime (early access; 400 in the Playground)
    async def chime_play(self, device_id: str, audio_ref: str) -> dict[str, Any]:
        if not self.chime_enabled:
            raise FeatureDisabledError("Chime playback is disabled (construct RingClient(chime_enabled=True))")
        body = {"data": {"type": "audio", "attributes": {"audio_ref": audio_ref}}}

        async def attempt() -> dict[str, Any]:
            r = await self._send("POST", self._url(f"/v1/devices/{device_id}/media/audio/playback"),
                                 auth=True, json=body, step="request")
            if r.status_code != 200:
                raise error_from_response(r.status_code, r.text, r.headers, step="request")
            return r.json()

        # playing a sound twice is user-visible: only the 401-refresh path may re-send
        return await self._retrying(attempt, retry=False)
