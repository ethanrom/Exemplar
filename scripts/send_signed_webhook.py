#!/usr/bin/env python3
"""Replay a Ring webhook fixture against the web app, signed like Ring signs it.

The Developer Playground sends no webhooks, so this is how the signed-webhook path (and stage-0
`sub_type` pruning) is exercised end to end:

    # replay a fixture by name (engine/tests/fixtures/webhooks/<name>.json) or any JSON file
    uv run --project engine python scripts/send_signed_webhook.py motion_human
    uv run --project engine python scripts/send_signed_webhook.py motion_vehicle --url http://localhost:3000/api/ring/webhook

    # same payload again -> the route answers 200 {"status":"duplicate"}
    uv run --project engine python scripts/send_signed_webhook.py motion_human --repeat 2

    # a fresh delivery (new request_id/event id/timestamp), optionally with another subtype or device
    uv run --project engine python scripts/send_signed_webhook.py motion_human --fresh --sub-type vehicle

    # negative cases: wrong key, altered body, no signature header -> the route answers 401
    uv run --project engine python scripts/send_signed_webhook.py motion_human --tamper
    uv run --project engine python scripts/send_signed_webhook.py motion_human --no-signature
    uv run --project engine python scripts/send_signed_webhook.py motion_human --key wrong-key

    uv run --project engine python scripts/send_signed_webhook.py --list

The body is signed as the exact bytes sent: `X-Signature: sha256=<hex HMAC-SHA256(key, body)>`. The
signing key must equal RING_WEBHOOK_SIGNING_KEY on the receiving app (the fixtures use
`exemplar-test-signing-key`). Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "engine" / "tests" / "fixtures" / "webhooks"
DEFAULT_KEY = "exemplar-test-signing-key"
DEFAULT_URL = "http://localhost:3000/api/ring/webhook"


def sign(body: bytes, key: str) -> str:
    """`X-Signature` header value for `body`."""
    return "sha256=" + hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()


def list_fixtures() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))


def load_payload(spec: str) -> tuple[bytes, dict]:
    """Return (raw body bytes, fixture headers). A fixture file holds {expect, headers, body: "<raw json string>"};
    any other JSON file is used as the body itself."""
    path = Path(spec)
    if not path.suffix and (FIXTURE_DIR / f"{spec}.json").is_file():
        path = FIXTURE_DIR / f"{spec}.json"
    elif not path.is_file() and (FIXTURE_DIR / spec).is_file():
        path = FIXTURE_DIR / spec
    if not path.is_file():
        raise SystemExit(f"no such fixture or file: {spec!r} (try --list)")
    text = path.read_text(encoding="utf-8")
    doc = json.loads(text)
    if isinstance(doc, dict) and isinstance(doc.get("body"), str) and "headers" in doc:
        return doc["body"].encode("utf-8"), doc["headers"]
    return text.encode("utf-8"), {}


def freshen(body: bytes, sub_type: str | None, device_id: str | None) -> bytes:
    """New request_id / event id / timestamp (and optionally subtype or device) so the delivery is not
    deduplicated. Re-serialised compactly, which is fine because we sign the bytes we send."""
    doc = json.loads(body)
    suffix = secrets.token_hex(4)
    now_ms = int(time.time() * 1000)
    doc["meta"]["request_id"] = f"req-{suffix}"
    doc["meta"]["time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data = doc["data"]
    data["id"] = f"evt-{suffix}"
    data.setdefault("attributes", {})["timestamp"] = now_ms
    if sub_type:
        data["subType"] = sub_type
    if device_id:
        data["attributes"]["source"] = device_id
        data.setdefault("relationships", {}).setdefault("devices", {})["links"] = {"self": f"/v1/devices/{device_id}"}
    return json.dumps(doc, separators=(",", ":")).encode("utf-8")


def post(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        raise SystemExit(f"could not reach {url}: {e.reason}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("payload", nargs="?", help="fixture name (e.g. motion_human) or path to a JSON file")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"default {DEFAULT_URL}")
    ap.add_argument("--key", default=DEFAULT_KEY, help="signing key (default: the test key)")
    ap.add_argument("--list", action="store_true", help="list fixture names and exit")
    ap.add_argument("--fresh", action="store_true", help="new request_id / event id / timestamp")
    ap.add_argument("--sub-type", choices=["motion", "human", "vehicle", "other_motion"], help="override data.subType (implies --fresh)")
    ap.add_argument("--device-id", help="override the source device id (implies --fresh)")
    ap.add_argument("--repeat", type=int, default=1, help="send the same signed body N times (duplicates after the first)")
    ap.add_argument("--tamper", action="store_true", help="alter the body after signing -> expect 401")
    ap.add_argument("--no-signature", action="store_true", help="omit X-Signature -> expect 401")
    ap.add_argument("--use-fixture-signature", action="store_true", help="send the fixture's own X-Signature header instead of re-signing")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args(argv)

    if args.list:
        for n in list_fixtures():
            doc = json.loads((FIXTURE_DIR / f"{n}.json").read_text(encoding="utf-8"))
            print(f"{n:24s} expect={doc.get('expect')}")
        return 0
    if not args.payload:
        ap.error("give a fixture name or file (or --list)")

    body, fixture_headers = load_payload(args.payload)
    if args.fresh or args.sub_type or args.device_id:
        body = freshen(body, args.sub_type, args.device_id)

    headers = {"Content-Type": "application/json"}
    if args.use_fixture_signature:
        if "X-Signature" in fixture_headers:
            headers["X-Signature"] = fixture_headers["X-Signature"]
    elif not args.no_signature:
        headers["X-Signature"] = sign(body, args.key)
    if args.tamper:
        body = body.replace(b'"type":', b'"type" :', 1) if b'"type":' in body else body + b" "

    code = 0
    for i in range(max(1, args.repeat)):
        status, text = post(args.url, body, headers, args.timeout)
        rid = ""
        try:
            rid = json.loads(body).get("meta", {}).get("request_id", "")
        except ValueError:
            pass
        print(f"[{i + 1}/{args.repeat}] POST {args.url} request_id={rid} -> {status} {text.strip()[:300]}")
        if status >= 400:
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
