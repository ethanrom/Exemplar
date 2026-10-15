"""Runs last: every operation in api.yaml must have been served (and schema-validated) by the suite above."""
from __future__ import annotations

import pytest

from .conftest import EXERCISED, HTTP_METHODS, SPEC

REQUIRED_MODULES = {"test_api_ring", "test_api_ingest", "test_api_library", "test_api_teach", "test_api_rules",
                    "test_api_live_monitor"}
SUCCESS = range(200, 400)


def test_every_operation_of_api_yaml_was_exercised(request):
    seen_modules = {item.module.__name__.rsplit(".", 1)[-1] for item in request.session.items}
    if not REQUIRED_MODULES <= seen_modules:
        pytest.skip("partial run: this check needs the whole tests/api suite")
    missing = []
    for path, ops in SPEC["paths"].items():
        for method in ops:
            if method not in HTTP_METHODS:
                continue
            statuses = {s for m, p, s in EXERCISED if m == method.upper() and p == path}
            if not any(s in SUCCESS for s in statuses):
                missing.append(f"{method.upper()} {path} (saw {sorted(statuses) or 'nothing'})")
    assert not missing, "operations never answered with a success status:\n  " + "\n  ".join(missing)


def test_error_statuses_documented_in_the_contract_are_all_reachable():
    """The documented non-2xx codes (404, 409, 400, 401) each occurred at least once somewhere in the suite."""
    wanted = set()
    for path, ops in SPEC["paths"].items():
        for method, op in ops.items():
            if method in HTTP_METHODS:
                wanted |= {(method.upper(), path, int(s)) for s in op["responses"] if s.isdigit() and int(s) >= 400}
    if len(EXERCISED) < 40:
        pytest.skip("partial run")
    missing = sorted(w for w in wanted if w not in EXERCISED)
    assert not missing, f"documented error responses never produced: {missing}"
