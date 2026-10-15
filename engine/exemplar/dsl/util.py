"""Small shared helpers: number formatting, AST normalisation, hole handling."""
from __future__ import annotations

import math
from typing import Mapping, Optional

from pydantic import BaseModel

from ..contracts.dsl_ast import (Always, And, Eventually, HoldsFor, Hole, Not, Or, Rule, Then, fill_holes,
                                 holes as _holes)
from .errors import UnboundHoleError


def fmt_num(x: float, exact: bool = False) -> str:
    """Canonical number text. Integers print without ``.0``; others with up to 3 decimals.

    ``exact=True`` (used by the DSL printer) falls back to the shortest round-trip repr when 3
    decimals would change the value, so ``parse(to_text(r)) == r`` holds for every rule.
    """
    if isinstance(x, bool):  # defensive: bool is an int subclass
        x = float(x)
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        return repr(x)
    if x == int(x):
        return str(int(x))
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    if exact and float(s) != x:
        s = repr(float(x))
    return s


def normalize(node: BaseModel) -> BaseModel:
    """Flatten nested ``and`` / ``or`` into n-ary nodes (what the parser always produces)."""
    if isinstance(node, Rule):
        return node.model_copy(update={"body": normalize(node.body)})
    if isinstance(node, (And, Or)):
        flat: list = []
        for c in node.args:
            c = normalize(c)
            if type(c) is type(node):
                flat.extend(c.args)
            else:
                flat.append(c)
        return type(node)(args=tuple(flat))
    if isinstance(node, Not):
        return Not(arg=normalize(node.arg))
    if isinstance(node, (Eventually, Always)):
        return type(node)(a=node.a, b=node.b, arg=normalize(node.arg))
    if isinstance(node, HoldsFor):
        return HoldsFor(d=node.d, arg=normalize(node.arg))
    if isinstance(node, Then):
        return Then(a=node.a, b=node.b, left=normalize(node.left), right=normalize(node.right))
    return node


def resolve_holes(rule: Rule, values: Optional[Mapping[str, float]]) -> Rule:
    """``fill_holes`` if values are given, then require the rule to be closed."""
    if values:
        rule = fill_holes(rule, dict(values))
    left = _holes(rule)
    if left:
        raise UnboundHoleError(left)
    return rule


def bound_value(b, values: Optional[Mapping[str, float]], hour: bool = False):
    """Numeric value of a bound; looks a hole up in ``values`` (hours round like ``fill_holes``)."""
    if isinstance(b, Hole):
        if values is None or b.name not in values:
            raise UnboundHoleError([b.name])
        x = values[b.name]
        return int(round(x)) if hour else float(x)
    return b
