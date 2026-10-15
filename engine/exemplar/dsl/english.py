"""Deterministic English printer (`to_english`). Never an LLM: the UI shows exactly this text.

Templates are tabulated in docs/DSL.md ("English templates"). Scope is made explicit with parentheses:
a phrase that extends to the right (``at some point within ..., X``, ``X, and then within ... Y``,
``it is not the case that X``) is parenthesised unless it is the last thing in the sentence.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..contracts.dsl_ast import (Always, And, Atom, DeviceEq, Eventually, HoldsFor, Hole, HourIn, Not, Or, Rule,
                                 SubtypeEq, Then, VarDecl)
from ..contracts.ontology import PREDICATES, ZONES
from .util import fmt_num

# levels, loosest -> tightest (same idea as the DSL printer)
_OR, _AND, _THEN, _UNARY, _ATOM = 0, 1, 2, 3, 4

ZONE_PHRASE = {"door": "at the door", "porch": "on the porch", "steps": "on the steps", "yard": "in the yard",
               "driveway": "in the driveway", "sidewalk": "on the sidewalk", "street": "in the street",
               "dock": "at the dock"}
assert set(ZONE_PHRASE) == set(ZONES)

# predicate -> (positive template, negative template); {0} {1} are arguments, {z} the zone as "the porch",
# {zp} the zone as "on the porch", {label} an attr label with underscores replaced by spaces.
ATOM_TEMPLATES: dict[str, tuple[str, str]] = {
    "present": ("{0} is present", "{0} is not present"),
    "in_zone": ("{0} is {zp}", "{0} is not {zp}"),
    "near": ("{0} is near {1}", "{0} is not near {1}"),
    "carrying": ("{0} is carrying {1}", "{0} is not carrying {1}"),
    "picks_up": ("{0} picks up {1}", "{0} does not pick up {1}"),
    "puts_down": ("{0} puts down {1}", "{0} does not put down {1}"),
    "rings_bell": ("{0} rings the doorbell", "{0} does not ring the doorbell"),
    "enters": ("{0} enters {z}", "{0} does not enter {z}"),
    "leaves": ("{0} leaves {z}", "{0} does not leave {z}"),
    "facing_camera": ("{0} faces the camera", "{0} does not face the camera"),
    "attr": ('{0} has the attribute "{label}"', '{0} does not have the attribute "{label}"'),
}

TYPE_WORDS = {"Entity": ("an", "entity"), "Person": ("a", "person"), "Vehicle": ("a", "vehicle"),
              "Package": ("a", "package"), "Animal": ("an", "animal"), "Object": ("an", "object"),
              "Carryable": ("a", "package or object")}


def _num(b) -> str:
    return "?" + b.name if isinstance(b, Hole) else fmt_num(b)


def _atom(a: Atom, negated: bool) -> str:
    tpl = ATOM_TEMPLATES.get(a.pred)
    if tpl is None or len(a.args) != len(PREDICATES[a.pred]):
        text = f"{a.pred}({', '.join(a.args)})"                    # unknown / malformed: show the raw atom
        return f"not {text}" if negated else text
    args = list(a.args)
    zone = args[1] if len(args) > 1 else ""
    return tpl[1 if negated else 0].format(
        *args, z=f"the {zone}", zp=ZONE_PHRASE.get(zone, f"in {zone}"), label=zone.replace("_", " "))


def _window(a, b) -> str:
    return f"within {_num(a)} to {_num(b)} s"


class _Printer:
    # _c returns (text, level, extends_right): extends_right means the phrase runs to the end of the
    # enclosing clause, so it needs parentheses unless it is the last thing in the sentence.
    def c(self, n, tail: bool) -> tuple[str, int, bool]:
        if isinstance(n, Atom):
            return _atom(n, False), _ATOM, False
        if isinstance(n, Not):
            x = n.arg
            if isinstance(x, Atom):
                return _atom(x, True), _ATOM, False
            if isinstance(x, Eventually):
                return f"at no point {_window(x.a, x.b)}, {self.child(x.arg, _UNARY, tail)}", _UNARY, True
            return f"it is not the case that {self.child(x, _UNARY, tail)}", _UNARY, True
        if isinstance(n, And):
            return self.join(n.args, " and ", tail), _AND, False
        if isinstance(n, Or):
            return self.join(n.args, " or ", tail), _OR, False
        if isinstance(n, Eventually):
            return f"at some point {_window(n.a, n.b)}, {self.child(n.arg, _UNARY, tail)}", _UNARY, True
        if isinstance(n, Always):
            return f"at every moment {_window(n.a, n.b)}, {self.child(n.arg, _UNARY, tail)}", _UNARY, True
        if isinstance(n, Then):
            left = self.child(n.left, _UNARY, False)
            return f"{left}, and then {_window(n.a, n.b)} {self.child(n.right, _UNARY, tail)}", _THEN, True
        if isinstance(n, HoldsFor):
            return f"{self.child(n.arg, _ATOM, False)} continuously for at least {_num(n.d)} s", _UNARY, False
        raise TypeError(f"not a formula: {n!r}")

    def child(self, n, min_level: int, tail: bool) -> str:
        text, level, extends = self.c(n, tail)
        if level < min_level or (extends and not tail):
            return f"({text if tail else self.c(n, True)[0]})"        # inside parentheses the scope is closed
        return text

    def join(self, kids, sep: str, tail: bool) -> str:
        last = len(kids) - 1
        return sep.join(self.child(k, _UNARY, tail and i == last) for i, k in enumerate(kids))


def _hour(c: HourIn) -> str:
    if isinstance(c.h1, int) and isinstance(c.h2, int):
        if c.h1 <= c.h2:
            return f"the local hour is between {c.h1} and {c.h2} inclusive"
        return f"the local hour is {c.h1} or later, or {c.h2} or earlier"
    return f"the local hour is in [{_num(c.h1)}, {_num(c.h2)}] (inclusive; wraps past midnight if the first is larger)"


def _ctx(c) -> str:
    if isinstance(c, HourIn):
        return _hour(c)
    if isinstance(c, SubtypeEq):
        return f"the event sub-type is {c.value.replace('_', ' ')}"
    if isinstance(c, DeviceEq):
        return f"the device is {c.value}"
    raise TypeError(f"not a context atom: {c!r}")


def _var(v: VarDecl) -> str:
    art, word = TYPE_WORDS[v.type]
    return f"{art} {word} {v.name}"


def _list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def to_english(node: BaseModel) -> str:
    """Deterministic English for a `Rule` (a full sentence), a formula (a clause) or a context atom.

    Example: ``exists p: Person, k: Package: picks_up(p, k) then[0, 20] leaves(p, porch)`` ->
    "There is a person p and a package k such that p picks up k, and then within 0 to 20 s p leaves the porch."
    Holes print as ``?name``; numbers with up to 3 decimals.
    """
    if isinstance(node, Rule):
        s = f"There is {_list([_var(v) for v in node.vars])} such that {_Printer().c(node.body, True)[0]}"
        if node.when:
            s += ", when " + " and ".join(_ctx(c) for c in node.when)
        return s + "."
    if isinstance(node, VarDecl):
        return _var(node)
    if isinstance(node, (HourIn, SubtypeEq, DeviceEq)):
        return _ctx(node)
    return _Printer().c(node, True)[0]
