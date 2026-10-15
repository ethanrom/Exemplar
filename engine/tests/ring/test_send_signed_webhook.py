"""scripts/send_signed_webhook.py against a tiny local receiver that uses the engine's own verifier."""
from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from exemplar.ring import InMemoryDeduper, process_delivery, verify_signature

from .conftest import SIGNING_KEY, WEBHOOK_FIXTURES

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "send_signed_webhook.py"
spec = importlib.util.spec_from_file_location("send_signed_webhook", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


@pytest.fixture
def receiver():
    dedupe = InMemoryDeduper()
    received: list[tuple[int, dict]] = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            d = process_delivery(raw, dict(self.headers), SIGNING_KEY, dedupe)
            code = {"accepted": 200, "duplicate": 200, "rejected": 401}[d.status]
            body = json.dumps({"status": d.status}).encode()
            received.append((code, {"status": d.status, "event": d.event}))
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # silence
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/api/ring/webhook", received
    srv.shutdown()


def statuses(received):
    return [r[1]["status"] for r in received]


def test_sign_matches_fixture_signatures():
    for name in ("motion_human", "motion_vehicle", "button_press"):
        doc = json.loads((WEBHOOK_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        assert script.sign(doc["body"].encode(), SIGNING_KEY) == doc["headers"]["X-Signature"]


def test_list_fixtures_and_load_payload():
    names = script.list_fixtures()
    assert {"motion_human", "tampered", "app_integration_added"} <= set(names)
    body, headers = script.load_payload("motion_human")
    assert json.loads(body)["meta"]["request_id"] == "req-0001" and "X-Signature" in headers
    with pytest.raises(SystemExit):
        script.load_payload("nope")


def test_fixture_replay_is_accepted_then_duplicate(receiver, capsys):
    url, received = receiver
    assert script.main(["motion_human", "--url", url, "--repeat", "2"]) == 0
    assert statuses(received) == ["accepted", "duplicate"]
    out = capsys.readouterr().out
    assert "request_id=req-0001 -> 200" in out


def test_fresh_delivery_gets_a_new_id_and_a_valid_signature(receiver):
    url, received = receiver
    assert script.main(["motion_human", "--url", url]) == 0
    assert script.main(["motion_human", "--url", url, "--fresh", "--sub-type", "vehicle", "--device-id", "ava1.ring.device.OTHER"]) == 0
    assert statuses(received) == ["accepted", "accepted"]
    ev = received[1][1]["event"]
    assert ev.request_id != "req-0001" and ev.sub_type == "vehicle" and ev.device_id == "ava1.ring.device.OTHER"
    assert ev.event_type == "motion_detected"


@pytest.mark.parametrize("flags", [["--tamper"], ["--no-signature"], ["--key", "wrong-key"]])
def test_bad_signatures_are_rejected_and_exit_nonzero(receiver, flags):
    url, received = receiver
    assert script.main(["motion_human", "--url", url, *flags]) == 1
    assert statuses(received) == ["rejected"]


def test_use_fixture_signature_replays_the_tampered_fixture_as_rejected(receiver):
    url, received = receiver
    assert script.main(["tampered", "--url", url, "--use-fixture-signature"]) == 1
    assert statuses(received) == ["rejected"]


def test_lifecycle_fixture_roundtrip(receiver):
    url, received = receiver
    assert script.main(["app_integration_added", "--url", url]) == 0
    assert received[0][1]["event"].is_lifecycle


def test_freshen_output_verifies_with_the_engine_verifier():
    body, _ = script.load_payload("motion_human")
    fresh = script.freshen(body, None, None)
    assert fresh != body and json.loads(fresh)["data"]["type"] == "motion_detected"
    assert verify_signature(fresh, script.sign(fresh, SIGNING_KEY), SIGNING_KEY)
