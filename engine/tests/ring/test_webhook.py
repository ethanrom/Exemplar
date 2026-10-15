"""Webhook HMAC verification + dedupe against the signed fixtures in tests/fixtures/webhooks/*.json.

Each fixture has `expect` in {accept, reject, duplicate}, `headers` and the RAW `body` string; the
signing key is `exemplar-test-signing-key`. The same fixtures drive the Node verifier test
(apps/web/lib/ring/webhook.test.mjs)."""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from exemplar.ring import (
    InMemoryDeduper,
    parse_webhook,
    process_delivery,
    sign_body,
    verify_signature,
)

from .conftest import SIGNING_KEY, WEBHOOK_FIXTURES

FIXTURES = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(WEBHOOK_FIXTURES.glob("*.json"))}


def raw(name: str) -> bytes:
    return FIXTURES[name]["body"].encode("utf-8")


def sig(name: str) -> str | None:
    return FIXTURES[name]["headers"].get("X-Signature")


def test_all_expected_fixtures_exist():
    assert {"motion_human", "motion_vehicle", "button_press", "app_integration_added", "app_integration_removed",
            "duplicate", "tampered", "reserialised", "missing_signature"} <= set(FIXTURES)
    assert {f["expect"] for f in FIXTURES.values()} == {"accept", "reject", "duplicate"}


@pytest.mark.parametrize("name", [n for n, f in FIXTURES.items() if f["expect"] in ("accept", "duplicate")])
def test_valid_fixtures_verify(name):
    assert verify_signature(raw(name), sig(name), SIGNING_KEY) is True


@pytest.mark.parametrize("name", [n for n, f in FIXTURES.items() if f["expect"] == "reject"])
def test_rejected_fixtures_fail_verification(name):
    assert verify_signature(raw(name), sig(name), SIGNING_KEY) is False


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_verdicts_via_process_delivery(name):
    f = FIXTURES[name]
    dedupe = InMemoryDeduper()
    if f["expect"] == "duplicate":
        first = process_delivery(raw("motion_human"), FIXTURES["motion_human"]["headers"], SIGNING_KEY, dedupe)
        assert first.status == "accepted"
    d = process_delivery(raw(name), f["headers"], SIGNING_KEY, dedupe)
    assert {"accept": "accepted", "reject": "rejected", "duplicate": "duplicate"}[f["expect"]] == d.status, d.reason


def test_replay_of_the_same_delivery_is_a_duplicate_only_the_second_time():
    dedupe = InMemoryDeduper()
    h = FIXTURES["motion_human"]["headers"]
    assert process_delivery(raw("motion_human"), h, SIGNING_KEY, dedupe).status == "accepted"
    assert process_delivery(raw("motion_human"), h, SIGNING_KEY, dedupe).status == "duplicate"
    assert process_delivery(raw("motion_vehicle"), FIXTURES["motion_vehicle"]["headers"], SIGNING_KEY,
                            dedupe).status == "accepted"


def test_rejected_deliveries_do_not_consume_the_request_id():
    dedupe = InMemoryDeduper()
    for bad in ("tampered", "reserialised", "missing_signature"):      # all carry request_id req-0001
        assert process_delivery(raw(bad), FIXTURES[bad]["headers"], SIGNING_KEY, dedupe).status == "rejected"
    assert len(dedupe) == 0
    assert process_delivery(raw("motion_human"), FIXTURES["motion_human"]["headers"], SIGNING_KEY,
                            dedupe).status == "accepted"


def test_signature_is_over_the_raw_bytes_not_the_parsed_json():
    body = raw("motion_human")
    reser = json.dumps(json.loads(body), indent=1).encode()                 # same JSON, different bytes
    assert json.loads(reser) == json.loads(body)
    assert verify_signature(reser, sig("motion_human"), SIGNING_KEY) is False
    assert verify_signature(body + b" ", sig("motion_human"), SIGNING_KEY) is False


def test_sign_body_matches_the_fixture_signatures():
    for name in ("motion_human", "motion_vehicle", "button_press", "app_integration_added", "app_integration_removed"):
        assert sign_body(raw(name), SIGNING_KEY) == sig(name)
    assert sign_body(b"x", "k") == "sha256=" + hmac.new(b"k", b"x", hashlib.sha256).hexdigest()


@pytest.mark.parametrize("header", [
    None, "", "sha256=", "sha256", "sha1=" + "0" * 40, "sha256=zz" + "0" * 62, "sha256=" + "0" * 63,
    "sha256=" + "0" * 64, "md5=abc", "=", "sha256 =" + "0" * 64,
])
def test_garbage_headers_never_verify_and_never_raise(header):
    assert verify_signature(raw("motion_human"), header, SIGNING_KEY) is False


def test_wrong_or_empty_key_never_verifies():
    assert verify_signature(raw("motion_human"), sig("motion_human"), "another-key") is False
    assert verify_signature(raw("motion_human"), sig("motion_human"), "") is False
    assert verify_signature(raw("motion_human"), sig("motion_human"), SIGNING_KEY.upper()) is False


def test_header_accepts_uppercase_hex_and_surrounding_whitespace():
    h = sig("motion_human")
    assert verify_signature(raw("motion_human"), "  " + h.upper().replace("SHA256=", "sha256=") + " \n", SIGNING_KEY)


def test_signature_header_lookup_is_case_insensitive():
    h = {"x-signature": sig("motion_human")}
    assert process_delivery(raw("motion_human"), h, SIGNING_KEY, InMemoryDeduper()).status == "accepted"


def test_unconfigured_key_rejects_everything():
    d = process_delivery(raw("motion_human"), FIXTURES["motion_human"]["headers"], None, InMemoryDeduper())
    assert d.status == "rejected" and "not configured" in d.reason


def test_validly_signed_garbage_is_rejected_not_crashed():
    body = b'{"hello": "world"}'
    d = process_delivery(body, {"X-Signature": sign_body(body, SIGNING_KEY)}, SIGNING_KEY, InMemoryDeduper())
    assert d.status == "rejected"
    body = b"not json"
    d = process_delivery(body, {"X-Signature": sign_body(body, SIGNING_KEY)}, SIGNING_KEY, InMemoryDeduper())
    assert d.status == "rejected"


def test_deduper_is_a_bounded_lru():
    d = InMemoryDeduper(max_size=3)
    assert [d.claim(x) for x in ("a", "b", "c")] == [True, True, True]
    assert d.claim("a") is False                       # refreshes 'a'
    assert d.claim("d") is True                        # evicts the least recent: 'b'
    assert len(d) == 3
    assert d.claim("b") is True                        # forgotten; this evicts 'c'
    assert d.claim("a") is False                       # 'a' was refreshed earlier, so it survived
    assert d.claim("c") is True                        # evicted above
    d.release("d")
    assert d.claim("d") is True


def test_parse_webhook_fields():
    ev = parse_webhook(raw("motion_vehicle"))
    assert (ev.request_id, ev.event_type, ev.sub_type) == ("req-0002", "motion_detected", "vehicle")
    assert ev.device_id == "ava1.ring.device.FIXTUREDEVICE0001" and ev.timestamp_ms == 1_792_048_103_109
    assert ev.account_id == "ava1.ring.account.FIXTUREACCOUNT" and not ev.is_lifecycle
    ev = parse_webhook(raw("button_press"))
    assert ev.event_type == "button_press" and ev.sub_type is None


@pytest.mark.parametrize("name", ["app_integration_added", "app_integration_removed"])
def test_lifecycle_events_have_no_device(name):
    ev = parse_webhook(raw(name))
    assert ev.is_lifecycle and ev.device_id is None          # source is the account (source_type 'users')
    assert ev.raw["data"]["type"] == name


@pytest.mark.parametrize("bad", [b"", b"[]", b'{"meta":{},"data":{}}', b'{"meta":{"request_id":"x"},"data":{}}',
                                 b'{"meta":{"request_id":""},"data":{"type":"x"}}'])
def test_parse_webhook_rejects_non_envelopes(bad):
    with pytest.raises(ValueError):
        parse_webhook(bad)
