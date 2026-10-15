"""Registers the opt-in `live` marker for the monitor smoke test (EXEMPLAR_LIVE=1 to run it)."""
from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: hits real Bedrock (needs EXEMPLAR_LIVE=1 and credentials)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("EXEMPLAR_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set EXEMPLAR_LIVE=1 (spends a few cents on Bedrock)")
    here = os.path.dirname(__file__)
    for item in items:
        if "live" in item.keywords and str(item.fspath).startswith(here):
            item.add_marker(skip)
