"""Shared setup for the synthesis tests: the `live` marker and a path to the DSL test helpers (read-only use)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_DSL_TESTS = Path(__file__).resolve().parents[1] / "dsl"
if str(_DSL_TESTS) not in sys.path:          # dsl_helpers / dsl_strategies are imported by plain name (no packages)
    sys.path.insert(0, str(_DSL_TESTS))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: calls real Bedrock; run with EXEMPLAR_LIVE=1 (spends budget)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("EXEMPLAR_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set EXEMPLAR_LIVE=1 to run (spends Bedrock budget)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
