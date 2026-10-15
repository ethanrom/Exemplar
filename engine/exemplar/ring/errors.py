"""Typed Ring API errors. Every API error carries the HTTP status and Ring's error `code`
(e.g. TIME_RANGE_NOT_AUTHORIZED, MEDIA_NOT_FOUND) so callers can branch without string matching.

Ring error bodies (error_handling.md, media_clips.md):
    {"errors": [{"id": "...", "status": "416", "code": "MEDIA_NOT_FOUND", "title": "...", "detail": "..."}]}
OAuth endpoint errors use the RFC 6749 shape: {"error": "invalid_grant", "error_description": "..."}.
"""
from __future__ import annotations

import json
from typing import Any


class RingError(Exception):
    """Base class for everything this package raises."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        title: str | None = None,
        detail: str | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
        step: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.request_id = request_id
        self.retry_after = retry_after
        self.step = step  # "request" (POST to api) | "download" (GET of the pre-signed URL) | None

    def __str__(self) -> str:
        bits = [self.message]
        if self.status is not None:
            bits.append(f"status={self.status}")
        if self.code:
            bits.append(f"code={self.code}")
        if self.step:
            bits.append(f"step={self.step}")
        return " ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        """Shape of the engine's `Error` schema (api.yaml): {error, code}."""
        return {"error": self.message, "code": self.code}


class RingAuthError(RingError):
    """401, a missing token, or a failed OAuth exchange/refresh."""


class RingForbiddenError(RingError):
    """403 (REQUEST_FORBIDDEN, 'Out of Scope Access', ...). Never retried."""


class TimeRangeNotAuthorizedError(RingForbiddenError):
    """403 TIME_RANGE_NOT_AUTHORIZED: the requested time is before the user's consent date
    (for the Playground: before the first token's `iat`). Never retried."""


class IPBlockedError(RingError):
    """406 Not Acceptable: Ring Security blocked our IP. Never retried (contact Ring support)."""


class InvalidPayloadError(RingError):
    """400 INVALID_PAYLOAD / OAuth invalid_request."""


class NotFoundError(RingError):
    """404 (unknown device, removed resource)."""


class MediaNotFoundError(RingError):
    """416 MEDIA_NOT_FOUND: nothing recorded for that time (yet). Retried on media calls."""


class RecordingNotReadyError(RingError):
    """425 RECORDING_NOT_READY. Retried on media calls."""


class UnprocessableMediaError(RingError):
    """422 on the media GET: CORRUPT_RECORDING per the docs, but the Playground also answers
    `GRECO_NO_VALID_KEY` for latest_in_range (undocumented) - inspect `.code`. Not retried."""


CorruptRecordingError = UnprocessableMediaError  # documented name


class RateLimitedError(RingError):
    """429. `retry_after` holds the Retry-After header (seconds) when present."""


class ServerError(RingError):
    """500 / 503 (SERVER_BUSY, device offline). Retried."""


class RingTransportError(RingError):
    """Network-level failure (e.g. httpx.RemoteProtocolError 'Server disconnected'). Retried."""

    def __init__(self, message: str, *, cause: BaseException | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.__cause__ = cause


class FeatureDisabledError(RingError):
    """A gated feature (chime playback) was called while its flag is off."""


# Errors worth retrying on any call (bounded by the retry policy).
RETRYABLE = (RateLimitedError, ServerError, RingTransportError)
# Additionally retried on media downloads while the recording materialises.
MEDIA_RETRYABLE = (MediaNotFoundError, RecordingNotReadyError)


def parse_error_body(text: str | bytes | None) -> dict[str, Any]:
    """Extract {code,title,detail,id} from a Ring (JSON:API) or OAuth (RFC 6749) error body."""
    if not text:
        return {}
    try:
        body = json.loads(text)
    except (ValueError, TypeError):
        return {}
    if not isinstance(body, dict):
        return {}
    errors = body.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        e = errors[0]
        return {k: e.get(k) for k in ("code", "title", "detail", "id")}
    if "error" in body:  # OAuth style
        return {"code": str(body.get("error")), "title": str(body.get("error")),
                "detail": body.get("error_description"), "id": None}
    return {}


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After: delta-seconds or an HTTP date. Returns seconds >= 0, or None."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def error_from_response(
    status: int,
    body: str | bytes | None,
    headers: Any = None,
    *,
    step: str | None = None,
) -> RingError:
    """Map an HTTP error response to the right typed exception."""
    info = parse_error_body(body)
    code = info.get("code")
    title = info.get("title")
    detail = info.get("detail")
    rid = info.get("id") or (headers.get("x-request-id") if headers is not None else None)
    ra = parse_retry_after(headers.get("retry-after") if headers is not None else None)
    msg = detail or title or f"Ring API error (HTTP {status})"
    kw: dict[str, Any] = dict(status=status, code=code, title=title, detail=detail, request_id=rid,
                              retry_after=ra, step=step)
    if status == 400:
        return InvalidPayloadError(msg, **kw)
    if status == 401:
        return RingAuthError(msg, **kw)
    if status == 403:
        if code == "TIME_RANGE_NOT_AUTHORIZED":
            return TimeRangeNotAuthorizedError(msg, **kw)
        return RingForbiddenError(msg, **kw)
    if status == 404:
        return NotFoundError(msg, **kw)
    if status == 406:
        return IPBlockedError(msg, **kw)
    if status == 416:
        return MediaNotFoundError(msg, **kw)
    if status == 422:
        return CorruptRecordingError(msg, **kw)
    if status == 425:
        return RecordingNotReadyError(msg, **kw)
    if status == 429:
        return RateLimitedError(msg, **kw)
    if status >= 500:
        return ServerError(msg, **kw)
    return RingError(msg, **kw)
