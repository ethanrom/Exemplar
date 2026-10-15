"""Actions: ui, webhook_out (retries, HMAC), slack, chime (flag, 400 from the Playground). No real network, no sleeping."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
import pytest
import respx

from exemplar.monitor import ActionRunner, Monitor, chime_via_ring_client
from exemplar.ring import InvalidPayloadError, PlaygroundToken, RingClient
from monitor_helpers import THEFT, Perceiver, Sink, deployed, event, load, validator

THEFT_A = load("theft_a")
WEBHOOK = "https://hooks.example.com/ring-secret-path-123"
SLACK = "https://hooks.slack.com/services/T000/B000/SECRETSECRET"
API = "https://api.amazonvision.com"


class Http:
    """httpx.Client on a MockTransport; replies from a script of statuses / exceptions, records requests."""

    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        status, headers = item if isinstance(item, tuple) else (item, {})
        return httpx.Response(status, headers=headers, text="ok")


def fire(runner: ActionRunner, actions=("ui",), *, sub_type="human", device_id="dev1"):
    sink = Sink()
    mon = Monitor(perceive_fast=Perceiver({"e1": THEFT_A}), perceive_strong=Perceiver(), on_firing=sink.on_firing,
                  on_event=sink.on_event, actions=runner, clock=lambda: 1_700_000_000.0)
    mon.deploy(deployed("theft", THEFT, actions=actions))
    (rec,) = mon.process(event("e1", sub_type=sub_type, device_id=device_id))
    assert rec.fired
    return rec, sink


def runner(http=None, sleeps=None, **kw):
    sleeps = [] if sleeps is None else sleeps
    return ActionRunner(http=http.client if http else None, sleep=sleeps.append, **kw), sleeps


# ------------------------------------------------------------------------------------------ ui
def test_ui_action_emits_rule_fired_first_and_is_always_on():
    r, _ = runner()
    for actions in (("ui",), (), ("webhook_out", "ui", "ui"), ("slack",)):
        rec, sink = fire(r, actions)
        assert rec.actions[0]["action"] == "ui" and rec.actions[0]["status"] == "ok"
        assert sink.types()[0] == "rule_fired"
        ev = sink.of("rule_fired")[0]
        assert ev["firing"]["witness"]["rule_id"] == "theft" and ev["message"].startswith("There is a person")
    assert [a["action"] for a in fire(r, ("slack", "ui", "slack"))[0].actions] == ["ui", "slack"]


def test_unconfigured_actions_are_skipped_with_a_reason():
    rec, sink = fire(runner()[0], ("webhook_out", "slack", "chime"))
    got = {a["action"]: (a["status"], a["detail"]) for a in rec.actions}
    assert got == {"ui": ("ok", None), "webhook_out": ("skipped", "webhook URL not configured"),
                   "slack": ("skipped", "Slack webhook URL not configured"), "chime": ("skipped", "chime flag is off")}
    assert sink.types() == ["rule_fired"] + ["action_result"] * 4 + ["cost_update"]


def test_unknown_action_is_skipped_not_raised():
    rec, _ = fire(runner()[0], ("sms",))
    assert rec.actions[1] == {"action": "sms", "status": "skipped", "detail": "unknown action 'sms'"}


# ------------------------------------------------------------------------------------------ webhook_out
def test_webhook_posts_the_witness_with_a_valid_hmac_signature():
    http = Http([200])
    r, sleeps = runner(http, webhook_url=WEBHOOK, webhook_secret="s3cret")
    rec, sink = fire(r, ("webhook_out",))
    (req,) = http.requests
    assert str(req.url) == WEBHOOK and req.method == "POST" and req.headers["content-type"] == "application/json"
    body = req.content
    expect = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert req.headers["x-signature"] == expect                       # over the exact raw bytes
    assert req.headers["x-exemplar-delivery"] == rec.id
    payload = json.loads(body)
    assert payload["type"] == "rule_fired" and payload["rule_id"] == "theft" and payload["event_id"] == "e1"
    assert payload["witness"]["bindings"] == {"p": "p1", "k": "k1"} and payload["score"] == pytest.approx(0.45)
    assert payload["english"].startswith("There is a person") and payload["clip_id"] == "clip_e1"
    assert [a["status"] for a in rec.actions] == ["ok", "ok"] and sleeps == []
    assert rec.actions[1]["detail"] == "HTTP 200 from hooks.example.com"
    # rule_fired was already emitted when the webhook went out (the UI is not blocked by slow actions)
    assert sink.types()[:3] == ["rule_fired", "action_result", "action_result"]
    for e in sink.events:
        validator("MonitorEvent").validate(e)


def test_webhook_without_a_secret_has_no_signature_header():
    http = Http([204])
    fire(runner(http, webhook_url=WEBHOOK)[0], ("webhook_out",))
    assert "x-signature" not in http.requests[0].headers


def test_webhook_retries_5xx_with_exponential_backoff_then_succeeds():
    http = Http([503, 502, 200])
    r, sleeps = runner(http, webhook_url=WEBHOOK)
    rec, _ = fire(r, ("webhook_out",))
    assert len(http.requests) == 3 and sleeps == [0.5, 1.0]
    assert rec.actions[1]["status"] == "ok" and "after 3 attempts" in rec.actions[1]["detail"]


def test_webhook_gives_up_after_three_retries_and_never_leaks_the_url():
    http = Http([500])
    r, sleeps = runner(http, webhook_url=WEBHOOK, webhook_secret="s3cret")
    rec, sink = fire(r, ("webhook_out",))
    assert len(http.requests) == 4 and sleeps == [0.5, 1.0, 2.0]
    a = rec.actions[1]
    assert a["status"] == "failed" and a["detail"] == "HTTP 500 from hooks.example.com after 4 attempts"
    assert "secret-path" not in json.dumps(sink.events) and "s3cret" not in json.dumps(sink.events)
    assert rec.fired                                                  # a failed action does not undo the firing


def test_webhook_honours_retry_after_but_caps_it():
    http = Http([(429, {"Retry-After": "3"}), (429, {"Retry-After": "9999"}), 200])
    r, sleeps = runner(http, webhook_url=WEBHOOK)
    fire(r, ("webhook_out",))
    assert sleeps == [3.0, 8.0]


def test_webhook_4xx_is_not_retried():
    http = Http([400])
    r, sleeps = runner(http, webhook_url=WEBHOOK)
    rec, _ = fire(r, ("webhook_out",))
    assert len(http.requests) == 1 and sleeps == []
    assert rec.actions[1] == {"action": "webhook_out", "status": "failed", "detail": "HTTP 400 from hooks.example.com (not retried)"}


def test_webhook_transport_errors_are_retried_and_recorded():
    http = Http([httpx.ConnectError("refused")])
    r, sleeps = runner(http, webhook_url=WEBHOOK, retries=2)
    rec, _ = fire(r, ("webhook_out",))
    assert len(http.requests) == 3 and sleeps == [0.5, 1.0]
    assert rec.actions[1]["status"] == "failed" and "ConnectError" in rec.actions[1]["detail"]
    http = Http([httpx.ReadTimeout("slow"), 200])
    rec, _ = fire(runner(http, webhook_url=WEBHOOK)[0], ("webhook_out",))
    assert rec.actions[1]["status"] == "ok"


# ------------------------------------------------------------------------------------------ slack
def test_slack_message_has_the_english_rule_and_the_top_witness_span():
    http = Http([200])
    rec, _ = fire(runner(http, slack_url=SLACK)[0], ("slack",))
    (req,) = http.requests
    assert str(req.url) == SLACK and "x-signature" not in req.headers
    text = json.loads(req.content)["text"]
    assert text.startswith("Exemplar: There is a person p and a package k such that")
    assert "event e1" in text and "score +0.45 (tau 0.00)" in text
    assert "evidence: picks_up(p, k) then[0, 10] carrying(p, k) at 6.0-8.0 s" in text
    assert len(text) <= 600
    assert rec.actions[1]["status"] == "ok" and "SECRET" not in json.dumps(rec.actions)


def test_slack_text_is_escaped_and_bounded():
    from exemplar.monitor.actions import slack_text
    from exemplar.monitor import FiringRecord
    d = deployed("r", THEFT)
    d.english = "A <!channel> & B " + "x" * 2000
    rec = FiringRecord(id="f", rule_id="r", event_id="e", stage=1, score=0.3, tau=0.0, fired=True, created_at_ms=0, actions=(),
                       witness={"spans": [{"op": "atom", "text": "a<b", "t_start_ms": 0, "t_end_ms": 1000}]})
    t = slack_text(d, rec)
    assert "<!channel>" not in t and "&lt;!channel&gt; &amp; B" in t and len(t) <= 600 and t.endswith("…")
    rec2 = FiringRecord(id="f", rule_id="r", event_id="e", stage=1, score=0.3, tau=0.0, fired=True, created_at_ms=0,
                        actions=(), witness={"spans": [{"op": "atom", "text": "a<b", "t_start_ms": 0, "t_end_ms": 1000},
                                                       {"op": "then", "text": "x then y", "t_start_ms": 2000, "t_end_ms": 3500}]})
    d.english = "short"
    t = slack_text(d, rec2)
    assert "evidence: x then y at 2.0-3.5 s" in t                     # the first temporal span wins over the atom
    assert slack_text(d, FiringRecord(id="f", rule_id="r", event_id="e", stage=1, score=None, tau=None, fired=True,
                                      created_at_ms=0, actions=(), witness=None)).count("\n") == 1


def test_slack_failure_is_recorded():
    http = Http([404])
    rec, _ = fire(runner(http, slack_url=SLACK)[0], ("slack",))
    assert rec.actions[1] == {"action": "slack", "status": "failed", "detail": "HTTP 404 from hooks.slack.com (not retried)"}


# ------------------------------------------------------------------------------------------ chime
def test_chime_is_skipped_unless_the_flag_is_on():
    calls = []
    rec, _ = fire(runner(chime=lambda d, a: calls.append((d, a)))[0], ("chime",))
    assert rec.actions[1] == {"action": "chime", "status": "skipped", "detail": "chime flag is off"} and calls == []
    rec, _ = fire(runner(chime_enabled=True)[0], ("chime",))
    assert rec.actions[1]["status"] == "skipped" and "no chime backend" in rec.actions[1]["detail"]


def test_chime_calls_the_backend_with_device_and_audio_ref():
    calls = []
    r, _ = runner(chime=lambda d, a: calls.append((d, a)), chime_enabled=True, chime_audio_ref="doorbell-2")
    rec, _ = fire(r, ("chime",), device_id="dev-7")
    assert calls == [("dev-7", "doorbell-2")] and rec.actions[1] == {"action": "chime", "status": "ok", "detail": None}


def test_chime_without_a_device_id_fails_cleanly():
    r, _ = runner(chime=lambda d, a: None, chime_enabled=True)
    bare = THEFT_A.model_copy(update={"context": THEFT_A.context.model_copy(update={"device_id": None})})
    sink = Sink()
    mon = Monitor(perceive_fast=Perceiver({"e1": bare}), perceive_strong=Perceiver(), on_firing=sink.on_firing, actions=r)
    mon.deploy(deployed("theft", THEFT, actions=("chime",)))
    (rec,) = mon.process(event("e1", device_id=None))
    assert rec.fired and rec.actions[1] == {"action": "chime", "status": "failed", "detail": "event has no device id"}


def test_chime_400_from_the_playground_is_recorded_as_failed_never_raised():
    def playground_chime(device_id, audio_ref):
        raise InvalidPayloadError("Validation Error: The request contains invalid input.", status=400, code="INVALID_PAYLOAD")

    rec, sink = fire(runner(chime=playground_chime, chime_enabled=True)[0], ("chime",))
    a = rec.actions[1]
    assert rec.fired and a["status"] == "failed" and "400" in a["detail"] and "InvalidPayloadError" in a["detail"]
    assert "chime failed" in sink.of("action_result")[1]["message"]


async def test_chime_via_ring_client_against_the_playground_400():
    """Real RingClient (flag on) on mocked HTTP: the sync adapter works from inside a running event loop."""
    token = PlaygroundToken(_jwt(iat=1_792_045_683, exp=9_999_999_999))

    async def nosleep(_):
        return None

    with respx.mock:
        route = respx.post(f"{API}/v1/devices/dev1/media/audio/playback").mock(return_value=httpx.Response(
            400, json={"errors": [{"detail": "The request contains invalid input.", "status": "400", "title": "Validation Error"}]}))
        async with RingClient(token, sleep=nosleep, chime_enabled=True) as client:
            rec, _ = fire(runner(chime=chime_via_ring_client(client), chime_enabled=True, chime_audio_ref="spike")[0], ("chime",))
        assert route.call_count == 1
        assert json.loads(route.calls.last.request.content)["data"]["attributes"]["audio_ref"] == "spike"
    a = rec.actions[1]
    assert a["status"] == "failed" and "InvalidPayloadError" in a["detail"] and "400" in a["detail"]


async def test_chime_via_ring_client_success_and_flag_off_in_the_client():
    token = PlaygroundToken(_jwt(iat=1_792_045_683, exp=9_999_999_999))

    async def nosleep(_):
        return None

    with respx.mock:
        respx.post(f"{API}/v1/devices/dev1/media/audio/playback").mock(return_value=httpx.Response(200, json={"data": {}}))
        async with RingClient(token, sleep=nosleep, chime_enabled=True) as client:
            rec, _ = fire(runner(chime=chime_via_ring_client(client), chime_enabled=True)[0], ("chime",))
        assert rec.actions[1]["status"] == "ok"
        async with RingClient(token, sleep=nosleep, chime_enabled=False) as off:      # the client's own flag is off
            rec, _ = fire(runner(chime=chime_via_ring_client(off), chime_enabled=True)[0], ("chime",))
        assert rec.actions[1]["status"] == "failed" and "FeatureDisabledError" in rec.actions[1]["detail"]


def _jwt(**claims) -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}.c2ln"


# ------------------------------------------------------------------------------------------ robustness
def test_an_unexpected_exception_inside_an_action_is_a_failed_result():
    class Broken(ActionRunner):
        def _slack(self, ctx):
            raise KeyError("boom")

    rec, _ = fire(Broken(slack_url=SLACK), ("slack",))
    assert rec.fired and rec.actions[1]["status"] == "failed" and "KeyError" in rec.actions[1]["detail"]


def test_actions_results_are_in_the_firing_api_payload():
    http = Http([200])
    rec, sink = fire(runner(http, webhook_url=WEBHOOK)[0], ("webhook_out",))
    api = rec.to_api()
    validator("Firing").validate(api)
    assert [a["action"] for a in api["actions"]] == ["ui", "webhook_out"]
    assert sink.firings == [rec]
