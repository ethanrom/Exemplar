"""Generate contracts/schemas/*.json from the pydantic contracts (referenced by api.yaml).

    uv run --project engine python -m exemplar.contracts.gen_schemas          # write
    uv run --project engine python -m exemplar.contracts.gen_schemas --check  # exit 1 if stale
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from .dsl_ast import Rule
from .labels import Label
from .trace import Trace

SCHEMAS = {"Trace": Trace, "Rule": Rule, "Label": Label}
OUT = Path(__file__).parent / "schemas"


def render() -> dict[str, str]:
    return {name: json.dumps(TypeAdapter(m).json_schema(mode="serialization"), indent=2, sort_keys=True) + "\n"
            for name, m in SCHEMAS.items()}


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    OUT.mkdir(exist_ok=True)
    for name, text in render().items():
        p = OUT / f"{name}.json"
        if check:
            if not p.exists() or p.read_text(encoding="utf-8") != text:
                stale.append(p.name)
        else:
            p.write_text(text, encoding="utf-8")
    if stale:
        print("stale schemas:", ", ".join(stale), "— run python -m exemplar.contracts.gen_schemas")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
