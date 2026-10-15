"""Ring webhook verification + dedupe (notifications.md).

* Header: `X-Signature: sha256=<lowercase hex>`; HMAC-SHA256 over the RAW request body bytes, key used as-is
  (UTF-8). Re-serialising the JSON changes the bytes and breaks the signature, so callers must pass the
  body exactly as received.
* Dedupe on `meta.request_id` (Ring retries). Verify FIRST, then claim: a forged request must not be able
  to burn a legitimate request_id.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

SIGNATURE_HEADER = "X-Signature"
LIFECYCLE_EVENTS = ("app_integration_added", "app_integration_removed")


def sign_body(raw_body: bytes, key: str) -> str:
    """The `X-Signature` header value for `raw_body`."""
    return "sha256=" + hmac.new(key.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, header: str | None, key: str) -> bool:
    """Constant-time check of `X-Signature` against the raw body. Never raises on bad input."""
    if not key or header is None or not isinstance(raw_body, (bytes, bytearray)):
        return False
    scheme, sep, hexdigest = header.strip().partition("=")
    if not sep or scheme.lower() != "sha256":
        return False
    try:
        given = bytes.fromhex(hexdigest.strip())
    except ValueError:
        return False
    expected = hmac.new(key.encode("utf-8"), bytes(raw_body), hashlib.sha256).digest()
    return hmac.compare_digest(given, expected)


# ------------------------------------------------------------------------------------------ dedupe
class WebhookDeduper(Protocol):
    def claim(self, request_id: str, event_type: str | None = None) -> bool:
        """Atomically record `request_id`. True if it is new, False if it was already delivered."""
        ...


class InMemoryDeduper:
    """Bounded LRU of delivered request ids. H replaces it with the `webhook_deliveries` table
    (`INSERT OR IGNORE`, claim() = rowcount == 1)."""

    def __init__(self, max_size: int = 2000) -> None:
        self.max_size = max_size
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def claim(self, request_id: str, event_type: str | None = None) -> bool:
        with self._lock:
            if request_id in self._seen:
                self._seen.move_to_end(request_id)
                return False
            self._seen[request_id] = None
            while len(self._seen) > self.max_size:
                self._seen.popitem(last=False)
            return True

    def release(self, request_id: str) -> None:
        with self._lock:
            self._seen.pop(request_id, None)

    def __len__(self) -> int:
        return len(self._seen)


# ------------------------------------------------------------------------------------------ parsing
@dataclass(frozen=True)
class WebhookEvent:
    request_id: str
    event_type: str                  # data.type: motion_detected | button_press | device_* | app_integration_* ...
    sub_type: str | None             # data.subType (motion_detected only)
    device_id: str | None            # attributes.source when source_type == "devices"
    account_id: str | None
    timestamp_ms: int | None
    event_id: str | None
    raw: dict[str, Any]

    @property
    def is_lifecycle(self) -> bool:
        return self.event_type in LIFECYCLE_EVENTS


def parse_webhook(raw_body: bytes | str) -> WebhookEvent:
    """Parse a (verified) delivery. Raises ValueError if it is not a Ring notification envelope."""
    try:
        body = json.loads(raw_body)
    except (ValueError, TypeError) as e:
        raise ValueError("webhook body is not JSON") from e
    if not isinstance(body, dict) or not isinstance(body.get("meta"), dict) or not isinstance(body.get("data"), dict):
        raise ValueError("webhook body is missing meta/data")
    meta, data = body["meta"], body["data"]
    rid = meta.get("request_id")
    etype = data.get("type")
    if not isinstance(rid, str) or not rid or not isinstance(etype, str):
        raise ValueError("webhook is missing meta.request_id or data.type")
    attrs = data.get("attributes") or {}
    ts = attrs.get("timestamp")
    device = attrs.get("source") if attrs.get("source_type") == "devices" else None
    return WebhookEvent(request_id=rid, event_type=etype, sub_type=data.get("subType"), device_id=device,
                        account_id=meta.get("account_id"),
                        timestamp_ms=int(ts) if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None,
                        event_id=data.get("id"), raw=body)


@dataclass(frozen=True)
class Delivery:
    status: str                      # "accepted" | "rejected" | "duplicate"
    reason: str | None = None
    event: WebhookEvent | None = None


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if not headers:
        return None
    lname = name.lower()
    for k, v in headers.items():
        if k.lower() == lname:
            return v
    return None


def process_delivery(raw_body: bytes, headers: Mapping[str, str] | None, key: str | None,
                     deduper: WebhookDeduper) -> Delivery:
    """verify -> parse -> dedupe. 'rejected' means answer 401 (bad/missing signature) or 400 (not Ring)."""
    if not key:
        return Delivery("rejected", "signing key not configured")
    if not verify_signature(raw_body, _header(headers, SIGNATURE_HEADER), key):
        return Delivery("rejected", "bad or missing signature")
    try:
        ev = parse_webhook(raw_body)
    except ValueError as e:
        return Delivery("rejected", str(e))
    if not deduper.claim(ev.request_id, ev.event_type):
        return Delivery("duplicate", "request_id already delivered", ev)
    return Delivery("accepted", None, ev)
