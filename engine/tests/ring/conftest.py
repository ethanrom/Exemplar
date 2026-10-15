"""Shared fixtures for the Ring tests. The `live` marker is registered here (not in pyproject)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
WEBHOOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "webhooks"
SIGNING_KEY = "exemplar-test-signing-key"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: hits the real Ring API (needs EXEMPLAR_LIVE=1 and a fresh token)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("EXEMPLAR_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live Ring test: set EXEMPLAR_LIVE=1 (needs a fresh Playground token)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


class FakeTime:
    """Injectable clock + sleep: sleeping advances the clock, nothing really waits."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.t

    async def sleep(self, d: float) -> None:
        self.sleeps.append(d)
        self.t += d


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_jwt(iat: int | None = None, exp: int | None = None, **extra: object) -> str:
    """An unsigned-looking JWT with the given claims (seconds). The signature segment is junk."""
    import base64

    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    claims: dict = dict(extra)
    if iat is not None:
        claims["iat"] = iat
    if exp is not None:
        claims["exp"] = exp
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}.c2ln"
