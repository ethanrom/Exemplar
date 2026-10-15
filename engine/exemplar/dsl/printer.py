"""Canonical DSL text printer (`to_text`): minimal parentheses by precedence, parseable by `parse`."""
from __future__ import annotations

from pydantic import BaseModel

from ..contracts.dsl_ast import (Always, And, Atom, DeviceEq, Eventually, HoldsFor, Hole, HourIn, Not, Or, Rule,
                                 SubtypeEq, Then, VarDecl)
from .util import fmt_num

# Precedence, loosest -> tightest. A child printed in a context of higher level gets parentheses.
_OR, _AND, _THEN, _UNARY, _ATOM = 0, 1, 2, 3, 4


def bound_text(b) -> str:
    return "?" + b.name if isinstance(b, Hole) else fmt_num(b, exact=True)


def _level(node) -> int:
    if isinstance(node, Or):
        return _OR
    if isinstance(node, And):
        return _AND
    if isinstance(node, Then):
        return _THEN
    if isinstance(node, (Not, Eventually, Always, HoldsFor)):
        return _UNARY
    return _ATOM


def _wrap(node, ctx_level: int) -> str:
    s = _phi(node)
    return f"({s})" if _level(node) < ctx_level else s


def _phi(node) -> str:
    if isinstance(node, Atom):
        return f"{node.pred}({', '.join(node.args)})"
    if isinstance(node, Not):
        return f"not {_wrap(node.arg, _UNARY)}"
    if isinstance(node, And):
        return " and ".join(_wrap(c, _THEN) for c in node.args)
    if isinstance(node, Or):
        return " or ".join(_wrap(c, _AND) for c in node.args)
    if isinstance(node, (Eventually, Always)):
        return f"{node.op}[{bound_text(node.a)}, {bound_text(node.b)}] {_wrap(node.arg, _UNARY)}"
    if isinstance(node, Then):
        return f"{_wrap(node.left, _THEN)} then[{bound_text(node.a)}, {bound_text(node.b)}] {_wrap(node.right, _UNARY)}"
    if isinstance(node, HoldsFor):
        return f"holds_for >= {bound_text(node.d)} {_wrap(node.arg, _UNARY)}"
    raise TypeError(f"not a formula: {node!r}")


def _ctx(node) -> str:
    if isinstance(node, HourIn):
        return f"hour in [{bound_text(node.h1)}, {bound_text(node.h2)}]"
    if isinstance(node, SubtypeEq):
        return f"subtype = {node.value}"
    if isinstance(node, DeviceEq):
        return f"device = {node.value}"
    raise TypeError(f"not a context atom: {node!r}")


def to_text(node: BaseModel) -> str:
    """Canonical DSL text of a `Rule`, a formula node, a context atom or a `VarDecl`.

    For every well-typed rule in normal form (nested and/or flattened, which is all the parser
    produces), ``parse(to_text(r)) == r``; use `normalize` first for hand-built nested trees.
    """
    if isinstance(node, Rule):
        s = "exists " + ", ".join(f"{v.name}: {v.type}" for v in node.vars) + ": " + _phi(node.body)
        if node.when:
            s += " when " + " and ".join(_ctx(c) for c in node.when)
        return s
    if isinstance(node, VarDecl):
        return f"{node.name}: {node.type}"
    if isinstance(node, (HourIn, SubtypeEq, DeviceEq)):
        return _ctx(node)
    return _phi(node)
