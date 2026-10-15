"""DSL text -> AST (`parse`). Uses the frozen Lark grammar `contracts.dsl_ast.GRAMMAR` unchanged."""
from __future__ import annotations

from functools import lru_cache

from lark import Lark, Token, Transformer
from lark.exceptions import (UnexpectedCharacters, UnexpectedEOF, UnexpectedInput, UnexpectedToken, VisitError)
from pydantic import ValidationError

from ..contracts.dsl_ast import (GRAMMAR, Always, And, Atom, DeviceEq, Eventually, HoldsFor, Hole, HourIn, Not, Or,
                                 Rule, SubtypeEq, Then, VarDecl)
from ..contracts.ontology import SUB_TYPES
from .errors import DSLSyntaxError

# --------------------------------------------------------------------------- readable token names
_KEYWORDS = {"EXISTS", "WHEN", "AND", "OR", "NOT", "THEN", "EVENTUALLY", "ALWAYS", "HOLDS_FOR", "HOUR", "IN",
             "SUBTYPE", "__ANON_1"}
_TOKEN_NAMES = {
    "LPAR": "'('", "RPAR": "')'", "LSQB": "'['", "RSQB": "']'", "COMMA": "','", "COLON": "':'", "EQUAL": "'='",
    "__ANON_0": "'>='", "__ANON_1": "'device'", "NAME": "a lower-case name", "ARG": "a variable, zone or label",
    "PRED": "a predicate name", "NUMBER": "a number", "HOLE": "a hole like ?b", "DEVICE": "a device id",
    "VARTYPE": "a type (Entity, Person, Vehicle, Package, Animal, Object or Carryable)", "$END": "end of input",
}
_FORMULA_START = {"NOT", "EVENTUALLY", "ALWAYS", "HOLDS_FOR", "PRED", "LPAR"}


def _describe_expected(names: set[str]) -> str:
    names = set(names)
    items: list[str] = []
    if _FORMULA_START <= names:
        names -= _FORMULA_START
        items.append("a formula (an atom like present(p), or not / eventually[a, b] / always[a, b] / holds_for >= d, or '(')")
    for n in sorted(names):
        items.append(_TOKEN_NAMES.get(n) or (f"'{n.lower()}'" if n in _KEYWORDS else n.lower()))
    items = sorted(set(items), key=lambda s: (not s.startswith("a formula"), s))
    if len(items) > 8:
        items = items[:8] + ["..."]
    return " or ".join(items) if len(items) <= 2 else ", ".join(items[:-1]) + " or " + items[-1]


def _context(text: str, line: int, column: int) -> str:
    lines = text.splitlines() or [""]
    src = lines[min(max(line, 1), len(lines)) - 1]
    return f"{src}\n{' ' * (max(column, 1) - 1)}^"


# --------------------------------------------------------------------------- lark -> AST
def _bound(tok: Token):
    if tok.type == "HOLE":
        return Hole(name=str(tok)[1:])
    return float(tok)


def _hour(tok: Token):
    if tok.type == "HOLE":
        return Hole(name=str(tok)[1:])
    x = float(tok)
    if x != int(x):
        raise DSLSyntaxError(f"hour bounds must be whole numbers 0-23, got {str(tok)}", tok.line, tok.column)
    return int(x)


def _flatten(cls, items):
    flat: list = []
    for c in items:
        if isinstance(c, cls):
            flat.extend(c.args)
        else:
            flat.append(c)
    return cls(args=tuple(flat))


class _ToAST(Transformer):
    def rule(self, items):
        decls = tuple(i for i in items if isinstance(i, VarDecl))
        ctx = tuple(i for i in items if isinstance(i, (HourIn, SubtypeEq, DeviceEq)))
        (body,) = [i for i in items if not isinstance(i, (VarDecl, HourIn, SubtypeEq, DeviceEq))]
        return Rule(vars=decls, body=body, when=ctx)

    def vardecl(self, items):
        return VarDecl(name=str(items[0]), type=str(items[1]))

    def atom(self, items):
        return Atom(pred=str(items[0]), args=tuple(str(t) for t in items[1:] if t is not None))

    def not_(self, items):
        return Not(arg=items[0])

    def and_(self, items):
        return _flatten(And, items)

    def or_(self, items):
        return _flatten(Or, items)

    def then_(self, items):
        left = items[0]
        for k in range(1, len(items), 2):
            (a, b), right = items[k], items[k + 1]
            left = Then(a=a, b=b, left=left, right=right)
        return left

    def eventually(self, items):
        (a, b), arg = items
        return Eventually(a=a, b=b, arg=arg)

    def always(self, items):
        (a, b), arg = items
        return Always(a=a, b=b, arg=arg)

    def holds_for(self, items):
        return HoldsFor(d=_bound(items[0]), arg=items[1])

    def window(self, items):
        return _bound(items[0]), _bound(items[1])

    def hour_in(self, items):
        return HourIn(h1=_hour(items[0]), h2=_hour(items[1]))

    def subtype_eq(self, items):
        tok = items[0]
        if str(tok) not in SUB_TYPES:
            raise DSLSyntaxError(f"unknown subtype '{tok}'; known: {', '.join(SUB_TYPES)}", tok.line, tok.column)
        return SubtypeEq(value=str(tok))

    def device_eq(self, items):
        return DeviceEq(value=str(items[0]))


@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(GRAMMAR, parser="lalr")


def _accepted(exc: UnexpectedToken) -> set[str]:
    """Terminals the parser can actually accept here (LALR `expected` over-approximates after reductions)."""
    ip = getattr(exc, "interactive_parser", None)
    if ip is not None:
        try:
            names = set(ip.accepts())
            if names:
                return names
        except Exception:  # pragma: no cover - fall back to Lark's own set
            pass
    return set(exc.expected)


def _syntax_error(exc: UnexpectedInput, text: str) -> DSLSyntaxError:
    line, col = getattr(exc, "line", -1), getattr(exc, "column", -1)
    if isinstance(exc, UnexpectedToken):
        exc.expected = _accepted(exc)
        if exc.token.type == "$END":
            lines = text.splitlines() or [""]
            line, col = len(lines), len(lines[-1]) + 1
            msg = f"unexpected end of input; expected {_describe_expected(exc.expected)}"
        else:
            msg = f"unexpected '{exc.token}'; expected {_describe_expected(exc.expected)}"
    elif isinstance(exc, UnexpectedEOF):
        lines = text.splitlines() or [""]
        line, col = len(lines), len(lines[-1]) + 1
        msg = f"unexpected end of input; expected {_describe_expected(exc.expected)}"
    elif isinstance(exc, UnexpectedCharacters):
        msg = f"unexpected character {exc.char!r}"
        if exc.allowed:
            msg += f"; expected {_describe_expected(exc.allowed)}"
    else:  # pragma: no cover - defensive
        msg = str(exc).splitlines()[0]
    if line is None or line < 1:
        line, col = 1, 1
    return DSLSyntaxError(msg, line, col, _context(text, line, col))


def parse(text: str) -> Rule:
    """Parse DSL text into a `Rule`.

    Nested ``and``/``or`` are flattened into n-ary nodes, time bounds become floats, hour bounds
    become ints, ``?name`` becomes a `Hole`. Raises `DSLSyntaxError` (with line/column) on bad text.
    Parsing does not typecheck: unknown predicates and ill-typed arguments are `typecheck`'s job.
    """
    try:
        tree = _parser().parse(text)
        rule = _ToAST().transform(tree)
    except UnexpectedInput as e:
        raise _syntax_error(e, text) from None
    except VisitError as e:
        if isinstance(e.orig_exc, DSLSyntaxError):
            err = e.orig_exc
            err.context = _context(text, err.line, err.column)
            raise err from None
        raise
    except ValidationError as e:  # pragma: no cover - the grammar produces valid nodes
        raise DSLSyntaxError(str(e).splitlines()[0]) from None
    return rule
