"""DSL AST node types and text grammar (PLAN.md §2.2). Frozen contract.

Stream C implements the parser (using `GRAMMAR`), typechecker, printers and evaluators against
these types; streams D/E/H build and consume them. Nodes are immutable pydantic models with an
`op` discriminator, so a rule round-trips through JSON (API, SQLite) unchanged.

Time bounds and durations are in **seconds** (floats); `hour` bounds are integers 0–23.
Holes (`?name`) may appear wherever a number may; a rule is *closed* when it has no holes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .ontology import SubType


class _Node(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Hole(_Node):
    op: Literal["hole"] = "hole"
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")


Bound = Union[float, Hole]


class Atom(_Node):
    """pred(args). Each arg is a bound variable name, a Zone literal, or an attr Label literal."""
    op: Literal["atom"] = "atom"
    pred: str
    args: tuple[str, ...]


class Not(_Node):
    op: Literal["not"] = "not"
    arg: "Phi"


class And(_Node):
    op: Literal["and"] = "and"
    args: tuple["Phi", ...] = Field(min_length=2)     # n-ary; the parser flattens nested `and`


class Or(_Node):
    op: Literal["or"] = "or"
    args: tuple["Phi", ...] = Field(min_length=2)


class Eventually(_Node):
    op: Literal["eventually"] = "eventually"
    a: Bound
    b: Bound
    arg: "Phi"


class Always(_Node):
    op: Literal["always"] = "always"
    a: Bound
    b: Bound
    arg: "Phi"


class Then(_Node):
    """left then[a,b] right: `right` occurs within [a,b] s after `left`."""
    op: Literal["then"] = "then"
    a: Bound
    b: Bound
    left: "Phi"
    right: "Phi"


class HoldsFor(_Node):
    """holds_for >= d arg: `arg` holds continuously for at least d s."""
    op: Literal["holds_for"] = "holds_for"
    d: Bound
    arg: "Phi"


Phi = Annotated[Union[Atom, Not, And, Or, Eventually, Always, Then, HoldsFor], Field(discriminator="op")]


class HourIn(_Node):
    """Local hour in [h1, h2] (inclusive; h1 > h2 wraps past midnight, e.g. [22, 6])."""
    op: Literal["hour_in"] = "hour_in"
    h1: Union[int, Hole]
    h2: Union[int, Hole]


class SubtypeEq(_Node):
    op: Literal["subtype_eq"] = "subtype_eq"
    value: SubType


class DeviceEq(_Node):
    op: Literal["device_eq"] = "device_eq"
    value: str


Ctx = Annotated[Union[HourIn, SubtypeEq, DeviceEq], Field(discriminator="op")]

VarType = Literal["Entity", "Person", "Vehicle", "Package", "Animal", "Object", "Carryable"]


class VarDecl(_Node):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: VarType


class Rule(_Node):
    """exists v1:T1, …: body [when ctx and …]."""
    vars: tuple[VarDecl, ...] = Field(min_length=1)
    body: Phi
    when: tuple[Ctx, ...] = ()


for _m in (Not, And, Or, Eventually, Always, Then, HoldsFor, Rule):
    _m.model_rebuild()


# ---------------------------------------------------------------------- generic traversal
def children(node: BaseModel) -> tuple[BaseModel, ...]:
    if isinstance(node, Rule):
        return (node.body, *node.when)
    if isinstance(node, (And, Or)):
        return node.args
    if isinstance(node, Then):
        return (node.left, node.right)
    if isinstance(node, (Not, Eventually, Always, HoldsFor)):
        return (node.arg,)
    return ()


def _bound_fields(node: BaseModel) -> tuple[str, ...]:
    return {"eventually": ("a", "b"), "always": ("a", "b"), "then": ("a", "b"),
            "holds_for": ("d",), "hour_in": ("h1", "h2")}.get(getattr(node, "op", ""), ())


def holes(node: BaseModel) -> list[str]:
    """Hole names in first-occurrence order (pre-order, bounds before children)."""
    out: list[str] = []
    def walk(n: BaseModel) -> None:
        for f in _bound_fields(n):
            v = getattr(n, f)
            if isinstance(v, Hole) and v.name not in out:
                out.append(v.name)
        for c in children(n):
            walk(c)
    walk(node)
    return out


def fill_holes(node: BaseModel, values: dict[str, float]) -> BaseModel:
    """Substitute hole values (seconds; hours are rounded to int). Unknown holes are left in place."""
    upd: dict = {}
    for f in _bound_fields(node):
        v = getattr(node, f)
        if isinstance(v, Hole) and v.name in values:
            x = values[v.name]
            upd[f] = int(round(x)) if node.op == "hour_in" else float(x)
    if isinstance(node, Rule):
        upd["body"] = fill_holes(node.body, values)
        upd["when"] = tuple(fill_holes(c, values) for c in node.when)
    elif isinstance(node, (And, Or)):
        upd["args"] = tuple(fill_holes(c, values) for c in node.args)
    elif isinstance(node, Then):
        upd["left"], upd["right"] = fill_holes(node.left, values), fill_holes(node.right, values)
    elif isinstance(node, (Not, Eventually, Always, HoldsFor)):
        upd["arg"] = fill_holes(node.arg, values)
    return node.model_copy(update=upd) if upd else node


def node_count(node: BaseModel) -> int:
    """AST nodes excluding bounds (used by MDL, §2.3)."""
    return 1 + sum(node_count(c) for c in children(node))


# ---------------------------------------------------------------------- text grammar (Lark, LALR)
# Precedence, loosest → tightest:  or  <  and  <  then  <  prefix (not, eventually, always, holds_for).
# `then` is left-associative:  a then[..] b then[..] c  ==  (a then[..] b) then[..] c.
# Examples:
#   exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)
#   exists v: Vehicle: holds_for >= 120 in_zone(v, dock) when hour in [6, 22]
#   exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)
GRAMMAR = r"""
?start: rule

rule: "exists" vardecl ("," vardecl)* ":" phi ("when" ctx ("and" ctx)*)?
vardecl: NAME ":" VARTYPE

?phi: or_
?or_: and_ ("or" and_)*
?and_: then_ ("and" then_)*
?then_: unary ("then" window unary)*
?unary: "not" unary                         -> not_
      | "eventually" window unary           -> eventually
      | "always" window unary               -> always
      | "holds_for" ">=" bound unary        -> holds_for
      | atom
      | "(" phi ")"

window: "[" bound "," bound "]"
atom: PRED "(" [ARG ("," ARG)*] ")"

ctx: "hour" "in" "[" bound "," bound "]"   -> hour_in
   | "subtype" "=" NAME                     -> subtype_eq
   | "device" "=" DEVICE                    -> device_eq

?bound: NUMBER | HOLE
HOLE: "?" /[a-z][a-z0-9_]*/
VARTYPE: "Entity" | "Person" | "Vehicle" | "Package" | "Animal" | "Object" | "Carryable"
PRED.2: /[a-z][a-z0-9_]*(?=\s*\()/
// PRED is any name followed by "(": unknown predicates parse and are rejected by the typechecker
// with a readable message (the LLM sketch loop feeds that message back).
ARG: /[a-z][a-z0-9_]*/
DEVICE: /[A-Za-z0-9._-]+/
NAME: /[a-z][a-z0-9_]*/

%import common.NUMBER
%import common.WS
%ignore WS
"""
