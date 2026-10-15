"""RingClient against mocked HTTP (respx). Shapes come from real Playground responses, redacted, in
tests/ring/fixtures/. No sleeping: the client's clock/sleep are injected (see FakeTime)."""
from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

from exemplar.ring import (
    FeatureDisabledError,
    InvalidPayloadError,
    IPBlockedError,
    MediaNotFoundError,
    NotFoundError,
    PlaygroundToken,
    RateLimitedError,
    RecordingNotReadyError,
    RetryPolicy,
    RingAuthError,
    RingClient,
    RingEvent,
    RingForbiddenError,
    RingTransportError,
    ServerError,
    TimeRangeNotAuthorizedError,
    UnprocessableMediaError,
)
from exemplar.ring.errors import error_from_response

from .conftest import FakeTime, load_fixture, make_jwt

API = "https://api.amazonvision.com"
DEV = "ava1.ring.device.FIXTUREDEVICE0001"
DL = "https://download-ap-northeast-1.prod.phoenix.devices.amazon.dev/v1/download"
PRESIGNED = f"{DL}?X-Amz-Signature=fakesig&req_type=video_download&req_id=abc"
VIDEO_URL = f"{API}/v1/devices/{DEV}/media/video/download"
IMAGE_URL = f"{API}/v1/devices/{DEV}/media/image/download"
HIST_URL = f"{API}/v1/history/devices/{DEV}/events"
TOKEN = make_jwt(iat=1_792_045_683, exp=9_999_999_999)
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32


def make_client(ft: FakeTime, **kw) -> RingClient:
    return RingClient(PlaygroundToken(TOKEN), clock=ft.clock, sleep=ft.sleep, **kw)


def err_body(status: int, code: str, detail: str = "x") -> dict:
    return {"errors": [{"id": "req", "status": str(status), "code": code, "detail": detail}]}


def ok_video(**h) -> httpx.Response:
    headers = {"content-type": "video/mp4", "x-media-timestamp": "1792048059035",
               "x-media-duration": "31733", "x-request-id": "rid-1", **h}
    return httpx.Response(200, content=MP4, headers=headers)


def redirect() -> httpx.Response:
    return httpx.Response(303, headers={"Location": PRESIGNED, "X-Request-ID": "rid-0"})


# ------------------------------------------------------------------------------------------ parsing
@respx.mock
async def test_users_me(fake_time):
    respx.get(f"{API}/v1/users/me").mock(return_value=httpx.Response(200, json=load_fixture("users_me.json")))
    async with make_client(fake_time) as c:
        me = await c.users_me()
    assert me.id == "ava1.ring.account.FIXTUREACCOUNT0001" and me.display_name == "Playground User"
    assert "playground@example.com" not in repr(me)        # email is kept out of repr/logs


@respx.mock
async def test_verify_connection_records_the_user_name_on_the_auth_manager(fake_time):
    from exemplar.ring import AuthManager

    respx.get(f"{API}/v1/users/me").mock(return_value=httpx.Response(200, json=load_fixture("users_me.json")))
    auth = AuthManager()
    auth.set_playground_token(TOKEN)
    async with RingClient(auth, clock=fake_time.clock, sleep=fake_time.sleep) as c:
        st = await c.verify_connection()
    assert st.connected and st.user_name == "Playground User" and auth.status().to_api()["user_name"] == "Playground User"
    auth.set_playground_token(TOKEN)                      # re-paste clears the stale name until verified again
    assert auth.status().user_name is None


@respx.mock
async def test_list_devices_resolves_included_and_maps_to_api_device(fake_time):
    route = respx.get(f"{API}/v1/devices").mock(
        return_value=httpx.Response(200, json=load_fixture("devices_included.json")))
    async with make_client(fake_time) as c:
        devices = await c.list_devices()
    assert route.calls.last.request.url.params["include"] == "status,capabilities,configurations"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"
    (d,) = devices
    assert d.name == "Playground Device" and d.id == DEV
    assert d.codecs == ("AVC",) and d.snapshot is True and d.chime is False
    assert d.capabilities["video"]["max_resolution"] == 1080
    assert d.configurations["motion_detection"]["enabled"] == "on"
    assert d.status is not None and d.online is True
    api = d.to_api()
    assert set(api) == {"id", "name", "online", "image_url", "codecs", "snapshot", "chime"}
    assert api["codecs"] == ["AVC"]


@respx.mock
async def test_list_devices_without_include_has_no_expansions(fake_time):
    doc = load_fixture("devices_included.json")
    doc.pop("included")
    route = respx.get(f"{API}/v1/devices").mock(return_value=httpx.Response(200, json=doc))
    async with make_client(fake_time) as c:
        (d,) = await c.list_devices(include=None)
    assert "include" not in route.calls.last.request.url.params
    assert d.status is None and d.capabilities is None and d.online is None and d.codecs == ()


@respx.mock
async def test_device_subresources_return_attributes(fake_time):
    respx.get(f"{API}/v1/devices/{DEV}/status").mock(
        return_value=httpx.Response(200, json={"data": {"attributes": {"online": True}}, "meta": {}}))
    respx.get(f"{API}/v1/devices/{DEV}/capabilities").mock(
        return_value=httpx.Response(200, json={"data": {"attributes": {"video": {"codecs": ["AVC"]}}}}))
    respx.get(f"{API}/v1/devices/{DEV}/configurations").mock(
        return_value=httpx.Response(200, json={"data": {"attributes": {"audio": {"volume": 11}}}}))
    respx.get(f"{API}/v1/devices/{DEV}/location").mock(
        return_value=httpx.Response(200, json={"data": {"attributes": {"country": "US", "state": "CA"}}}))
    async with make_client(fake_time) as c:
        assert (await c.device_status(DEV)) == {"online": True}
        assert (await c.device_capabilities(DEV))["video"]["codecs"] == ["AVC"]
        assert (await c.device_configurations(DEV))["audio"]["volume"] == 11
        assert (await c.device_location(DEV))["state"] == "CA"


# ------------------------------------------------------------------------------------------ media flow
@respx.mock
async def test_303_redirect_is_followed_without_the_bearer_token(fake_time):
    post = respx.post(VIDEO_URL).mock(return_value=redirect())
    get = respx.get(DL).mock(return_value=ok_video())
    async with make_client(fake_time) as c:
        clip = await c.download_video(DEV, 1_792_048_059_034, 31_742)
    # step 1 authenticated, step 2 (pre-signed URL on another host) must NOT carry the token
    assert post.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(post.calls.last.request.content) == {"timestamp": 1_792_048_059_034, "duration": 31_742}
    get_req = get.calls.last.request
    assert "authorization" not in get_req.headers
    assert str(get_req.url) == PRESIGNED
    assert clip.data == MP4 and clip.status == 200 and not clip.partial
    assert clip.content_type == "video/mp4"
    assert clip.media_timestamp_ms == 1_792_048_059_035 and clip.media_duration_ms == 31_733
    assert clip.request_id == "rid-1"


@respx.mock
async def test_206_partial_content_is_flagged(fake_time):
    respx.post(VIDEO_URL).mock(return_value=redirect())
    respx.get(DL).mock(return_value=httpx.Response(206, content=MP4, headers={
        "content-type": "video/mp4", "x-media-timestamp": "1792048060000", "x-media-duration": "3000"}))
    async with make_client(fake_time) as c:
        clip = await c.download_video(DEV, 1_792_048_059_034, 5000)
    assert clip.partial and clip.media_duration_ms == 3000 and clip.media_timestamp_ms == 1_792_048_060_000


@respx.mock
async def test_video_retries_416_then_425_then_200(fake_time):
    """PLAN section 6: the clip-download retry logic against a mocked 416 -> 425 -> 200 sequence."""
    post = respx.post(VIDEO_URL).mock(return_value=redirect())
    get = respx.get(DL).mock(side_effect=[
        httpx.Response(416, json=err_body(416, "MEDIA_NOT_FOUND", "No media found in time range")),
        httpx.Response(425, json=err_body(425, "RECORDING_NOT_READY")),
        ok_video(),
    ])
    async with make_client(fake_time) as c:
        clip = await c.download_video(DEV, 1_792_048_059_034, 31_742)
    assert clip.data == MP4
    assert get.call_count == 3 and post.call_count == 3          # each attempt redoes the signed-URL request
    assert fake_time.sleeps == [2.0, 4.0]                         # exponential backoff
    # and none of the three GETs leaked the token
    assert all("authorization" not in call.request.headers for call in get.calls)


@respx.mock
async def test_media_errors_can_come_from_step_one_too(fake_time):
    post = respx.post(IMAGE_URL).mock(side_effect=[
        httpx.Response(425, json=err_body(425, "RECORDING_NOT_READY")),
        redirect(),
    ])
    respx.get(DL).mock(return_value=httpx.Response(200, content=b"\xff\xd8\xff", headers={
        "content-type": "image/jpeg", "x-media-origin": "recording", "x-media-timestamp": "1792048059034"}))
    async with make_client(fake_time) as c:
        snap = await c.download_snapshot(DEV, at_ms=1_792_048_059_034)
    assert post.call_count == 2 and fake_time.sleeps == [2.0]
    assert snap.media_origin == "recording" and snap.media_timestamp_ms == 1_792_048_059_034
    assert snap.media_duration_ms is None


@respx.mock
async def test_media_retry_gives_up_after_about_two_minutes(fake_time):
    respx.post(VIDEO_URL).mock(return_value=redirect())
    get = respx.get(DL).mock(return_value=httpx.Response(416, json=err_body(416, "MEDIA_NOT_FOUND")))
    async with make_client(fake_time) as c:
        with pytest.raises(MediaNotFoundError) as ei:
            await c.download_video(DEV, 1_792_048_059_034, 5000)
    assert ei.value.status == 416 and ei.value.code == "MEDIA_NOT_FOUND" and ei.value.step == "download"
    assert 90 <= sum(fake_time.sleeps) <= 120 and max(fake_time.sleeps) <= 30
    assert get.call_count == len(fake_time.sleeps) + 1


@respx.mock
async def test_retry_budget_is_configurable(fake_time):
    respx.post(VIDEO_URL).mock(return_value=redirect())
    get = respx.get(DL).mock(return_value=httpx.Response(425, json=err_body(425, "RECORDING_NOT_READY")))
    async with make_client(fake_time, retry=RetryPolicy(media_budget_s=10, base_delay_s=1)) as c:
        with pytest.raises(RecordingNotReadyError):
            await c.download_video(DEV, 1, 1000)
    assert fake_time.sleeps == [1.0, 2.0, 4.0] and get.call_count == 4


@respx.mock
async def test_416_is_not_retried_for_non_media_calls(fake_time):
    route = respx.get(f"{API}/v1/devices/{DEV}/status").mock(
        return_value=httpx.Response(416, json=err_body(416, "MEDIA_NOT_FOUND")))
    async with make_client(fake_time) as c:
        with pytest.raises(MediaNotFoundError):
            await c.device_status(DEV)
    assert route.call_count == 1 and fake_time.sleeps == []


@respx.mock
async def test_429_honours_retry_after(fake_time):
    route = respx.get(f"{API}/v1/users/me").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"},
                       json={"errors": [{"status": "429", "title": "Rate Limit Exceeded"}]}),
        httpx.Response(200, json=load_fixture("users_me.json")),
    ])
    async with make_client(fake_time) as c:
        await c.users_me()
    assert route.call_count == 2 and fake_time.sleeps == [7.0]


@respx.mock
async def test_429_on_the_media_download_step_also_waits(fake_time):
    respx.post(VIDEO_URL).mock(return_value=redirect())
    get = respx.get(DL).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "3"}, json=err_body(429, "RATE_LIMITED")), ok_video()])
    async with make_client(fake_time) as c:
        await c.download_video(DEV, 1, 1000)
    assert fake_time.sleeps == [3.0] and get.call_count == 2


@respx.mock
async def test_429_with_an_absurd_retry_after_is_surfaced_not_slept(fake_time):
    respx.get(f"{API}/v1/users/me").mock(return_value=httpx.Response(429, headers={"Retry-After": "900"}))
    async with make_client(fake_time) as c:
        with pytest.raises(RateLimitedError) as ei:
            await c.users_me()
    assert ei.value.retry_after == 900.0 and fake_time.sleeps == []


@respx.mock
async def test_429_without_retry_after_falls_back_to_backoff(fake_time):
    respx.get(f"{API}/v1/users/me").mock(side_effect=[httpx.Response(429), httpx.Response(429),
                                                      httpx.Response(200, json=load_fixture("users_me.json"))])
    async with make_client(fake_time) as c:
        await c.users_me()
    assert fake_time.sleeps == [2.0, 4.0]


@respx.mock
async def test_406_ip_block_is_never_retried(fake_time):
    body = {"errors": [{"status": "406", "title": "Not Acceptable"}]}
    p = respx.post(VIDEO_URL).mock(return_value=httpx.Response(406, json=body))
    g = respx.get(f"{API}/v1/devices").mock(return_value=httpx.Response(406, json=body))
    async with make_client(fake_time) as c:
        with pytest.raises(IPBlockedError):
            await c.download_video(DEV, 1, 1000)
        with pytest.raises(IPBlockedError):
            await c.list_devices()
    assert p.call_count == 1 and g.call_count == 1 and fake_time.sleeps == []


@respx.mock
async def test_403_time_range_not_authorized_is_never_retried(fake_time):
    errs = load_fixture("errors.json")
    post = respx.post(IMAGE_URL).mock(return_value=httpx.Response(403, json=errs["403_time_range"]))
    async with make_client(fake_time) as c:
        with pytest.raises(TimeRangeNotAuthorizedError) as ei:
            await c.download_snapshot(DEV, at_ms=1_792_000_000_000)
    assert post.call_count == 1 and fake_time.sleeps == []
    assert ei.value.status == 403 and ei.value.code == "TIME_RANGE_NOT_AUTHORIZED" and ei.value.step == "request"
    assert isinstance(ei.value, RingForbiddenError)


@respx.mock
async def test_other_403_400_404_422_are_not_retried(fake_time):
    cases = [(403, "REQUEST_FORBIDDEN", RingForbiddenError), (400, "INVALID_PAYLOAD", InvalidPayloadError),
             (404, "DEVICE_NOT_FOUND", NotFoundError)]
    async with make_client(fake_time) as c:
        route = respx.post(VIDEO_URL)
        for status, code, exc in cases:
            before = route.call_count
            route.mock(return_value=httpx.Response(status, json=err_body(status, code)))
            with pytest.raises(exc) as ei:
                await c.download_video(DEV, 1, 1000)
            assert ei.value.code == code and route.call_count == before + 1
        route.mock(return_value=redirect())
        g = respx.get(DL).mock(return_value=httpx.Response(422, json=load_fixture("errors.json")["422_greco"]))
        with pytest.raises(UnprocessableMediaError) as ei:
            await c.download_video(DEV, 1, 1000)
        assert ei.value.code == "GRECO_NO_VALID_KEY" and g.call_count == 1 and ei.value.step == "download"
    assert fake_time.sleeps == []


@respx.mock
async def test_5xx_is_retried(fake_time):
    route = respx.get(f"{API}/v1/devices/{DEV}/status").mock(side_effect=[
        httpx.Response(500, json={"errors": [{"status": "500", "title": "Internal Server Error"}]}),
        httpx.Response(503, json=err_body(503, "SERVER_BUSY")),
        httpx.Response(200, json={"data": {"attributes": {"online": True}}}),
    ])
    async with make_client(fake_time) as c:
        assert (await c.device_status(DEV))["online"] is True
    assert route.call_count == 3 and fake_time.sleeps == [2.0, 4.0]


@respx.mock
async def test_persistent_503_raises_server_error(fake_time):
    respx.get(f"{API}/v1/devices/{DEV}/status").mock(return_value=httpx.Response(503, json=err_body(503, "SERVER_BUSY")))
    async with make_client(fake_time, retry=RetryPolicy(api_max_attempts=3)) as c:
        with pytest.raises(ServerError) as ei:
            await c.device_status(DEV)
    assert ei.value.code == "SERVER_BUSY" and len(fake_time.sleeps) == 2


@respx.mock
async def test_transport_errors_are_retried_json_call(fake_time):
    """Seen live: httpx.RemoteProtocolError 'Server disconnected without sending a response'."""
    route = respx.get(f"{API}/v1/users/me").mock(side_effect=[
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
        httpx.ConnectError("boom"),
        httpx.Response(200, json=load_fixture("users_me.json")),
    ])
    async with make_client(fake_time) as c:
        assert (await c.users_me()).id.startswith("ava1.ring.account.")
    assert route.call_count == 3 and fake_time.sleeps == [2.0, 4.0]


@respx.mock
async def test_transport_errors_are_retried_on_the_presigned_download(fake_time):
    respx.post(VIDEO_URL).mock(return_value=redirect())
    respx.get(DL).mock(side_effect=[httpx.ReadTimeout("slow"), ok_video()])
    async with make_client(fake_time) as c:
        assert (await c.download_video(DEV, 1, 1000)).data == MP4
    assert fake_time.sleeps == [2.0]


@respx.mock
async def test_persistent_transport_error_surfaces_typed(fake_time):
    respx.get(f"{API}/v1/users/me").mock(side_effect=httpx.RemoteProtocolError("Server disconnected"))
    async with make_client(fake_time, retry=RetryPolicy(api_max_attempts=3)) as c:
        with pytest.raises(RingTransportError) as ei:
            await c.users_me()
    assert isinstance(ei.value.__cause__, httpx.RemoteProtocolError)
    assert len(fake_time.sleeps) == 2


class _RefreshingProvider:
    def __init__(self) -> None:
        self.token, self.refreshes = "stale", 0

    async def get_token(self) -> str:
        return self.token

    async def on_unauthorized(self) -> bool:
        self.refreshes += 1
        self.token = "fresh"
        return self.refreshes == 1

    def status(self):  # pragma: no cover - protocol filler
        raise NotImplementedError


@respx.mock
async def test_401_triggers_one_refresh_then_retry(fake_time):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["authorization"] == "Bearer fresh":
            return httpx.Response(200, json=load_fixture("users_me.json"))
        return httpx.Response(401)            # the real API sends an empty body

    route = respx.get(f"{API}/v1/users/me").mock(side_effect=handler)
    prov = _RefreshingProvider()
    async with RingClient(prov, clock=fake_time.clock, sleep=fake_time.sleep) as c:
        await c.users_me()
    assert route.call_count == 2 and prov.refreshes == 1


@respx.mock
async def test_401_with_nothing_to_refresh_raises_once(fake_time):
    route = respx.get(f"{API}/v1/users/me").mock(return_value=httpx.Response(401))
    async with make_client(fake_time) as c:                # Playground token: cannot refresh
        with pytest.raises(RingAuthError) as ei:
            await c.users_me()
    assert ei.value.status == 401 and route.call_count == 1


@respx.mock
async def test_401_twice_does_not_loop(fake_time):
    route = respx.get(f"{API}/v1/users/me").mock(return_value=httpx.Response(401))
    prov = _RefreshingProvider()
    async with RingClient(prov, clock=fake_time.clock, sleep=fake_time.sleep) as c:
        with pytest.raises(RingAuthError):
            await c.users_me()
    assert route.call_count == 2


async def test_missing_token_fails_before_any_request(fake_time):
    async with RingClient(PlaygroundToken(), clock=fake_time.clock, sleep=fake_time.sleep) as c:
        with pytest.raises(RingAuthError) as ei:
            await c.users_me()
    assert ei.value.code == "NO_TOKEN"


# ------------------------------------------------------------------------------------------ request bodies
@respx.mock
async def test_video_options_and_validation(fake_time):
    post = respx.post(VIDEO_URL).mock(return_value=redirect())
    respx.get(DL).mock(return_value=ok_video())
    async with make_client(fake_time) as c:
        await c.download_video(DEV, 5, 2000, codec="avc", frame_rate=5, width=640, height=360, audio=True)
        with pytest.raises(ValueError):
            await c.download_video(DEV, 5, 0)
        with pytest.raises(ValueError):
            await c.download_video(DEV, 5, 900_001)
    assert json.loads(post.calls.last.request.content) == {
        "timestamp": 5, "duration": 2000,
        "video_options": {"codec": "avc", "frame_rate": 5, "resolution": {"width": 640, "height": 360}},
        "audio_options": {"audio_enabled": True}}
    assert post.call_count == 1


@respx.mock
async def test_snapshot_bodies(fake_time):
    post = respx.post(IMAGE_URL).mock(return_value=redirect())
    respx.get(DL).mock(return_value=httpx.Response(200, content=b"\xff\xd8", headers={
        "content-type": "image/jpeg", "x-media-origin": "snapshot"}))
    async with make_client(fake_time) as c:
        await c.download_snapshot(DEV, at_ms=1_792_048_059_034)
        assert json.loads(post.calls.last.request.content) == {"type": "at_timestamp", "timestamp": 1_792_048_059_034}
        await c.download_snapshot(DEV, latest_in_range=(1000, 2000), image_format="jpeg", width=640, height=360)
        assert json.loads(post.calls.last.request.content) == {
            "type": "latest_in_range", "start_timestamp": 1000, "end_timestamp": 2000,
            "image_options": {"format": "jpeg", "resolution": {"width": 640, "height": 360}}}
        await c.download_snapshot(DEV, latest_in_range=(1000, None))
        assert json.loads(post.calls.last.request.content) == {"type": "latest_in_range", "start_timestamp": 1000}
        for bad in ({}, {"at_ms": 1, "latest_in_range": (1, 2)}, {"latest_in_range": (0, 25 * 3600 * 1000)}):
            with pytest.raises(ValueError):
                await c.download_snapshot(DEV, **bad)


@respx.mock
async def test_event_helpers_use_event_window_and_wait_for_clip_end(fake_time):
    post = respx.post(VIDEO_URL).mock(return_value=redirect())
    respx.get(DL).mock(return_value=ok_video())
    ev = RingEvent(id="e1", event_type="on_demand", start_ms=1_792_048_059_034, end_ms=1_792_048_090_776, device_id=DEV)
    async with make_client(fake_time, wall_clock=lambda: 1_792_048_090.776 - 2.0) as c:   # 2 s before the clip ends
        await c.download_event_video(ev)
    assert json.loads(post.calls.last.request.content) == {"timestamp": 1_792_048_059_034, "duration": 31_742}
    assert fake_time.sleeps == [pytest.approx(7.0)]                                        # end + 5 s grace
    async with make_client(fake_time, wall_clock=lambda: 1_792_049_000.0) as c:            # long past: no wait
        fake_time.sleeps.clear()
        await c.download_event_video(ev)
    assert fake_time.sleeps == []


# ------------------------------------------------------------------------------------------ history
def _ev(i: int, start: int, etype: str = "on_demand") -> dict:
    return {"type": "history-events", "id": f"ava1.ring.history.event.E{i}",
            "attributes": {"event_type": etype, "is_third_party_reviewed": False, "start": start, "end": start + 30_000},
            "relationships": {"source": {"data": {"type": "devices", "id": DEV}}}}


@respx.mock
async def test_history_parses_the_real_shape(fake_time):
    doc = load_fixture("history_page_real.json")
    route = respx.get(HIST_URL).mock(return_value=httpx.Response(200, json=doc))
    async with make_client(fake_time) as c:
        events = await c.history_list(DEV)
    assert len(events) == 6 and route.call_count == 1                 # no links.next -> one page
    assert all(e.event_type == "on_demand" and e.sub_type is None and e.device_id == DEV for e in events)
    assert events[0].start_ms == 1_792_049_271_835 and events[0].end_ms == 1_792_049_303_577
    assert events[0].duration_ms == 31_742 and events[0].is_third_party_reviewed
    assert "event_types" not in route.calls.last.request.url.params


@respx.mock
async def test_history_follows_page_key_cursors_and_stops_on_empty_data(fake_time):
    pages = {
        None: {"data": [_ev(1, 3000), _ev(2, 2000)],
               "links": {"next": f"/v1/history/devices/{DEV}/events?page[key]=2026-10-15T07:00:00Z&event_types=ding%2Con_demand"}},
        "2026-10-15T07:00:00Z": {"data": [_ev(3, 1000)],
               "links": {"next": f"/v1/history/devices/{DEV}/events?page[key]=2026-10-15T06:00:00Z&event_types=ding%2Con_demand"}},
        # empty page BUT links.next still present: must not loop forever
        "2026-10-15T06:00:00Z": {"data": [],
               "links": {"next": f"/v1/history/devices/{DEV}/events?page[key]=2026-10-15T05:00:00Z&event_types=ding%2Con_demand"}},
    }
    seen_keys = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.params.get("page[key]")
        seen_keys.append(key)
        assert request.url.params["event_types"] == "ding,on_demand"
        return httpx.Response(200, json=pages[key])

    route = respx.get(HIST_URL).mock(side_effect=handler)
    async with make_client(fake_time) as c:
        events = [e async for e in c.history(DEV, ["ding", "on_demand"])]
    assert [e.id.rsplit(".", 1)[1] for e in events] == ["E1", "E2", "E3"]
    assert seen_keys == [None, "2026-10-15T07:00:00Z", "2026-10-15T06:00:00Z"] and route.call_count == 3


@respx.mock
async def test_history_reapplies_filter_when_next_only_has_the_cursor(fake_time):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page[key]") is None:
            return httpx.Response(200, json={"data": [_ev(1, 2000)],
                                             "links": {"next": f"/v1/history/devices/{DEV}/events?page[key]=K1"}})
        assert request.url.params["event_types"] == "motion.human"      # re-added
        return httpx.Response(200, json={"data": []})

    respx.get(HIST_URL).mock(side_effect=handler)
    async with make_client(fake_time) as c:
        assert len(await c.history_list(DEV, "motion.human")) == 1


@respx.mock
async def test_history_stops_when_a_page_repeats(fake_time):
    page = {"data": [_ev(1, 2000)], "links": {"next": f"/v1/history/devices/{DEV}/events?page[key]=same"}}
    route = respx.get(HIST_URL).mock(return_value=httpx.Response(200, json=page))
    async with make_client(fake_time) as c:
        events = await c.history_list(DEV)
    assert len(events) == 1 and route.call_count == 2


@respx.mock
async def test_history_max_pages_and_since_ms(fake_time):
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params.get("page[key]") or 0)
        return httpx.Response(200, json={"data": [_ev(n, 10_000 - n * 1000)],
                                         "links": {"next": f"/v1/history/devices/{DEV}/events?page[key]={n + 1}"}})

    route = respx.get(HIST_URL).mock(side_effect=handler)
    async with make_client(fake_time) as c:
        assert len(await c.history_list(DEV, max_pages=3)) == 3 and route.call_count == 3
        before = route.call_count
        got = await c.history_list(DEV, since_ms=8500)                 # newest-first: stop once events are older
    assert [e.start_ms for e in got] == [10_000, 9000] and route.call_count - before == 3


@respx.mock
async def test_history_tagged_tags_motion_but_never_playground_on_demand(fake_time):
    motion = {"human": _ev(1, 5000, "motion"), "vehicle": _ev(2, 4000, "motion")}
    on_demand = _ev(3, 3000, "on_demand")

    def handler(request: httpx.Request) -> httpx.Response:
        flt = request.url.params.get("event_types")
        if flt is None:
            return httpx.Response(200, json={"data": [motion["human"], motion["vehicle"], on_demand]})
        sub = flt.split(".", 1)[1]
        if sub in motion:
            return httpx.Response(200, json={"data": [motion[sub]]})
        # the Playground ignores the filter: it returns its on_demand event for every filter
        return httpx.Response(200, json={"data": [on_demand]})

    respx.get(HIST_URL).mock(side_effect=handler)
    async with make_client(fake_time) as c:
        events = await c.history_tagged(DEV)
    assert [(e.id[-2:], e.event_type, e.sub_type) for e in events] == [
        ("E1", "motion", "human"), ("E2", "motion", "vehicle"), ("E3", "on_demand", None)]


# ------------------------------------------------------------------------------------------ chime
@respx.mock
async def test_chime_is_disabled_by_default(fake_time):
    route = respx.post(f"{API}/v1/devices/{DEV}/media/audio/playback").mock(return_value=httpx.Response(200, json={}))
    async with make_client(fake_time) as c:
        with pytest.raises(FeatureDisabledError):
            await c.chime_play(DEV, "ref")
    assert route.call_count == 0


@respx.mock
async def test_chime_play_body_and_response(fake_time):
    route = respx.post(f"{API}/v1/devices/{DEV}/media/audio/playback").mock(return_value=httpx.Response(
        200, json={"data": {"type": "audio", "id": "ref-1", "attributes": {"status": "completed"}}}))
    async with make_client(fake_time, chime_enabled=True) as c:
        out = await c.chime_play(DEV, "ref-1")
    assert out["data"]["attributes"]["status"] == "completed"
    assert json.loads(route.calls.last.request.content) == {
        "data": {"type": "audio", "attributes": {"audio_ref": "ref-1"}}}


@respx.mock
async def test_chime_400_in_the_playground_is_typed_and_not_retried(fake_time):
    """P0-4: the Playground answers 400 'Validation Error' (no chime slots on the virtual device)."""
    route = respx.post(f"{API}/v1/devices/{DEV}/media/audio/playback").mock(return_value=httpx.Response(
        400, json={"errors": [{"detail": "The request contains invalid input.", "status": "400", "title": "Validation Error"}]}))
    async with make_client(fake_time, chime_enabled=True) as c:
        with pytest.raises(InvalidPayloadError) as ei:
            await c.chime_play(DEV, "spike-probe")
    assert route.call_count == 1 and ei.value.title == "Validation Error"


@respx.mock
async def test_chime_is_not_replayed_on_server_errors(fake_time):
    route = respx.post(f"{API}/v1/devices/{DEV}/media/audio/playback").mock(return_value=httpx.Response(503))
    async with make_client(fake_time, chime_enabled=True) as c:
        with pytest.raises(ServerError):
            await c.chime_play(DEV, "ref")
    assert route.call_count == 1 and fake_time.sleeps == []


# ------------------------------------------------------------------------------------------ error mapping
def test_error_mapping_from_real_bodies():
    errs = load_fixture("errors.json")
    e = error_from_response(403, json.dumps(errs["403_time_range"]), {"x-request-id": "r"}, step="request")
    assert isinstance(e, TimeRangeNotAuthorizedError) and e.code == "TIME_RANGE_NOT_AUTHORIZED"
    assert e.detail == "Requested time range is not within authorized boundaries"
    e = error_from_response(416, json.dumps(errs["416_media_not_found"]), {}, step="download")
    assert isinstance(e, MediaNotFoundError) and e.code == "MEDIA_NOT_FOUND"
    e = error_from_response(404, json.dumps(errs["404_not_found"]), {})
    assert isinstance(e, NotFoundError) and e.code is None and e.title == "Not Found"
    e = error_from_response(401, "", {})
    assert isinstance(e, RingAuthError) and e.status == 401
    e = error_from_response(502, "<html>bad gateway</html>", {})
    assert isinstance(e, ServerError) and e.to_dict() == {"error": "Ring API error (HTTP 502)", "code": None}


def test_retry_after_http_date_and_garbage():
    from exemplar.ring.errors import parse_retry_after
    assert parse_retry_after("12") == 12.0 and parse_retry_after("0.5") == 0.5
    assert parse_retry_after(None) is None and parse_retry_after("soon") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0          # past dates clamp to 0


async def test_client_default_http_client_has_no_default_authorization_header():
    c = RingClient(PlaygroundToken(TOKEN))
    try:
        assert "authorization" not in c._client().headers
    finally:
        await c.aclose()
