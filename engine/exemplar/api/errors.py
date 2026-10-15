"""API error types and the `{"error": ..., "code": ...}` body shape (api.yaml `Error`)."""
from __future__ import annotations

from typing import Any

from exemplar.ring import (IPBlockedError, InvalidPayloadError, NotFoundError, RateLimitedError, RingAuthError,
                           RingError, RingForbiddenError)


def error_body(message: str, code: str | None = None) -> dict[str, Any]:
    return {"error": message, "code": code}


class ApiError(Exception):
    """Raise from a route to answer with `status` and an `Error` body."""

    def __init__(self, status: int, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code

    def body(self) -> dict[str, Any]:
        return error_body(self.message, self.code)


class NotFound(ApiError):
    def __init__(self, what: str) -> None:
        super().__init__(404, f"{what} not found", "NOT_FOUND")


class BadRequest(ApiError):
    def __init__(self, message: str, code: str = "INVALID_PAYLOAD") -> None:
        super().__init__(400, message, code)


class NotAvailable(ApiError):
    """A feature whose module is not available (synth/agent, active/calibrate/monitor)."""

    def __init__(self, what: str) -> None:
        super().__init__(503, f"{what} not available yet", "NOT_AVAILABLE")


def ring_status(e: RingError) -> int:
    """HTTP status the engine answers with for a typed Ring error."""
    if isinstance(e, RingAuthError):
        return 401
    if isinstance(e, RingForbiddenError):
        return 403
    if isinstance(e, NotFoundError):
        return 404
    if isinstance(e, InvalidPayloadError):
        return 400
    if isinstance(e, RateLimitedError):
        return 429
    if isinstance(e, IPBlockedError):
        return 502
    return 502


def ring_error(e: RingError) -> ApiError:
    return ApiError(ring_status(e), e.message, e.code)


def short_error(e: BaseException, limit: int = 300) -> str:
    """One-line description for status columns and logs (never includes tokens or model ids: the Ring and perception layers scrub them)."""
    msg = str(e) or type(e).__name__
    return (f"{type(e).__name__}: {msg}" if type(e).__name__ not in msg else msg)[:limit]
