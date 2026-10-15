"""Shared helpers for the DSL tests (imported by plain name; pytest puts this directory on sys.path)."""
from __future__ import annotations

from pathlib import Path

from exemplar.contracts.trace import Trace

FIXTURES = Path(__file__).parents[1] / "fixtures" / "traces"
ALL_FIXTURES = sorted(p.stem for p in FIXTURES.glob("*.json"))


def load(name: str) -> Trace:
    return Trace.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
