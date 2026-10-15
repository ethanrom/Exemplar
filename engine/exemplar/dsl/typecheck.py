"""Typechecker: `typecheck(rule) -> list[str]`. Messages are written to be fed back to an LLM."""
from __future__ import annotations

import math
import re

from ..contracts.dsl_ast import (Always, And, Atom, DeviceEq, Eventually, HoldsFor, Hole, HourIn, Not, Or, Rule,
                                 SubtypeEq, Then)
from ..contracts.ontology import PREDICATES, SUB_TYPES, VAR_TYPES, ZONES
from .printer import bound_text, to_text
from .util import fmt_num

_LABEL_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_DEVICE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _sig(pred: str) -> str:
    return f"{pred}({', '.join(PREDICATES[pred])})"


def _slot(kind: str) -> str:
    if kind == "Entity":
        return "an entity variable (any type)"
    if kind == "Carryable":
        return "a Carryable (Package or Object) variable"
    return f"a {kind} variable"


def _fits(var_type: str, kind: str) -> bool:
    """A variable of type T fits a slot of kind K iff VAR_TYPES[T] is a subset of VAR_TYPES[K]."""
    return set(VAR_TYPES[var_type]) <= set(VAR_TYPES[kind])


def _num(x) -> bool:
    return not isinstance(x, Hole)


def typecheck(rule: Rule) -> list[str]:
    """Return a list of human-readable problems; an empty list means the rule is well-typed.

    Checks: unique variable names; every atom argument is a declared variable, a Zone literal or (for
    `attr`'s second argument) a label; predicate known and arity right; variable type fits each slot;
    numeric windows satisfy ``0 <= a <= b``; ``holds_for`` d >= 0; hours in 0-23; no unused variables.
    Holes (`?name`) are accepted wherever a number may appear.
    """
    errs: list[str] = []
    declared: dict[str, str] = {}
    for v in rule.vars:
        if v.name in declared:
            errs.append(f"variable '{v.name}' is declared more than once; every variable needs a unique name")
        elif v.name in ZONES:
            errs.append(f"variable name '{v.name}' clashes with the zone '{v.name}'; rename the variable")
        declared.setdefault(v.name, v.type)
    used: set[str] = set()

    def bound_ok(what: str, x, *, hour: bool = False) -> bool:
        """Check one concrete bound; holes pass."""
        if not _num(x):
            return True
        if isinstance(x, float) and not math.isfinite(x):
            errs.append(f"{what}: bound must be a finite number, got {x}")
            return False
        if hour:
            if not isinstance(x, int) or not 0 <= x <= 23:
                errs.append(f"{what}: hours must be whole numbers between 0 and 23, got {fmt_num(x)}")
                return False
        elif x < 0:
            errs.append(f"{what}: bounds are seconds and must be >= 0, got {fmt_num(x)}")
            return False
        return True

    def window(name: str, lo, hi) -> None:
        text = f"{name}[{bound_text(lo)}, {bound_text(hi)}]"
        ok_lo = bound_ok(text, lo)
        ok_hi = bound_ok(text, hi)
        if ok_lo and ok_hi and _num(lo) and _num(hi) and lo > hi:
            errs.append(f"{text}: the lower bound must be <= the upper bound (needs 0 <= a <= b)")

    def atom(a: Atom) -> None:
        kinds = PREDICATES.get(a.pred)
        if kinds is None:
            errs.append(f"unknown predicate '{a.pred}'; known: {', '.join(PREDICATES)}")
            used.update(x for x in a.args if x in declared)
            return
        if len(a.args) != len(kinds):
            errs.append(f"{a.pred} takes {len(kinds)} argument{'s' if len(kinds) != 1 else ''} "
                        f"({_sig(a.pred)}), got {len(a.args)}: {to_text(a)}")
            used.update(x for x in a.args if x in declared)
            return
        for i, (kind, arg) in enumerate(zip(kinds, a.args), 1):
            where = f"argument {i} of {a.pred}"
            if kind == "Zone":
                if arg in ZONES:
                    continue
                if arg in declared:
                    used.add(arg)
                    errs.append(f"{where} must be a zone literal ({', '.join(ZONES)}), not the variable '{arg}'")
                else:
                    errs.append(f"{where}: '{arg}' is not a zone; zones are: {', '.join(ZONES)}")
            elif kind == "Label":
                if arg in declared:
                    used.add(arg)
                    errs.append(f"{where} must be a label literal such as hoodie or delivery_uniform, "
                                f"not the variable '{arg}'")
                elif not _LABEL_RE.match(arg):
                    errs.append(f"{where}: '{arg}' is not a valid label (lower-case letters, digits, underscores)")
            else:
                if arg in declared:
                    used.add(arg)
                    if not _fits(declared[arg], kind):
                        errs.append(f"{where} must be {_slot(kind)} ({_sig(a.pred)}), but '{arg}' is declared "
                                    f"{declared[arg]}")
                elif arg in ZONES:
                    errs.append(f"{where} must be {_slot(kind)}, not the zone '{arg}' ({_sig(a.pred)})")
                else:
                    have = ", ".join(f"{n}: {t}" for n, t in declared.items())
                    errs.append(f"undeclared variable '{arg}' in {to_text(a)}; declared variables: {have}")

    def walk(n) -> None:
        if isinstance(n, Atom):
            atom(n)
        elif isinstance(n, (And, Or)):
            for c in n.args:
                walk(c)
        elif isinstance(n, Not):
            walk(n.arg)
        elif isinstance(n, (Eventually, Always)):
            window(n.op, n.a, n.b)
            walk(n.arg)
        elif isinstance(n, Then):
            window("then", n.a, n.b)
            walk(n.left)
            walk(n.right)
        elif isinstance(n, HoldsFor):
            bound_ok("holds_for", n.d)
            walk(n.arg)
        else:  # pragma: no cover - the AST union is closed
            errs.append(f"unsupported node {type(n).__name__}")

    walk(rule.body)

    for name in declared:
        if name not in used:
            errs.append(f"variable '{name}' is declared but never used in the formula")

    for c in rule.when:
        if isinstance(c, HourIn):
            bound_ok("hour in [...]", c.h1, hour=True)
            bound_ok("hour in [...]", c.h2, hour=True)
        elif isinstance(c, SubtypeEq):
            if c.value not in SUB_TYPES:
                errs.append(f"unknown subtype '{c.value}'; known: {', '.join(SUB_TYPES)}")
        elif isinstance(c, DeviceEq):
            if not _DEVICE_RE.match(c.value):
                errs.append(f"device id '{c.value}' may only contain letters, digits, '.', '_' and '-'")
    return errs
