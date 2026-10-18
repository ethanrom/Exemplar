"""Recursive scrubbing of everything the export writes.

Every string at any depth is free text: known original ids are replaced by their aliases, and then the string is
checked against the exact-value deny set and the shape patterns. Anything that still matches stops the export
(nothing is silently deleted). Numbers must be finite. Findings are reported by *kind* and JSON path, never with
the offending value.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scan"))
from denylist import Denylist, build_denylist, shape_findings   # noqa: E402

from common import ExportError   # noqa: E402

# Context clauses that must never appear in an exported rule (a device id would be the value).
FORBIDDEN_AST_OPS = ("device_eq",)


class Scrubber:
    def __init__(self, replacements: dict[str, str], deny: Denylist | None = None) -> None:
        self.deny = deny if deny is not None else build_denylist()
        keys = sorted(replacements, key=len, reverse=True)
        self._rep = replacements
        self._rx = re.compile("|".join(re.escape(k) for k in keys)) if keys else None
        self.replaced = 0
        self.checked_strings = 0

    # ---------------------------------------------------------------------------------------- strings
    def text(self, s: str, path: str = "$") -> str:
        out = s
        if self._rx is not None:
            def sub(m: re.Match) -> str:
                self.replaced += 1
                return self._rep[m.group(0)]
            out = self._rx.sub(sub, s)
        self.checked_strings += 1
        kinds = self.deny.find_text(out) + shape_findings(out)
        if kinds:
            raise ExportError(f"scrub: {sorted(set(kinds))} found at {path} after alias replacement")
        return out

    # ---------------------------------------------------------------------------------------- objects
    def obj(self, o: Any, path: str = "$") -> Any:
        if isinstance(o, str):
            return self.text(o, path)
        if isinstance(o, bool) or o is None:
            return o
        if isinstance(o, int):
            return o
        if isinstance(o, float):
            if not math.isfinite(o):
                raise ExportError(f"scrub: non-finite number at {path}")
            return o
        if isinstance(o, (list, tuple)):
            return [self.obj(v, f"{path}[{i}]") for i, v in enumerate(o)]
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if not isinstance(k, str):
                    raise ExportError(f"scrub: non-string key at {path}")
                out[self.text(k, f"{path}.<key>")] = self.obj(v, f"{path}.{k}")
            return out
        raise ExportError(f"scrub: unsupported type {type(o).__name__} at {path}")


def check_ast(node: Any, path: str = "ast") -> None:
    """Context clauses: no device_eq anywhere; subtype_eq must be in the ontology; hour_in values must be integers."""
    from exemplar.contracts.ontology import SUB_TYPES
    if isinstance(node, dict):
        op = node.get("op")
        if op in FORBIDDEN_AST_OPS:
            raise ExportError(f"scrub: forbidden context clause {op!r} at {path}")
        if op == "subtype_eq" and node.get("value") not in SUB_TYPES:
            raise ExportError(f"scrub: subtype_eq outside the ontology at {path}")
        if op == "hour_in":
            for f in ("h1", "h2"):
                v = node.get(f)
                if isinstance(v, dict) and v.get("op") == "hole":
                    continue
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ExportError(f"scrub: hour_in bound {f} is not an integer at {path}")
        for k, v in node.items():
            check_ast(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            check_ast(v, f"{path}[{i}]")
