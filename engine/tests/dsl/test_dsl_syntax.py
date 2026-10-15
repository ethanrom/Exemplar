"""Parser, printer, typechecker and English printer: example-based tests."""
from __future__ import annotations

import pytest

from exemplar.contracts.dsl_ast import (Always, And, Atom, Eventually, HoldsFor, Hole, HourIn, Not, Or, Rule, SubtypeEq,
                                        Then, VarDecl, DeviceEq)
from exemplar.contracts.ontology import PREDICATES
from exemplar.dsl import (DSLSyntaxError, fmt_num, normalize, parse, to_english, to_text, typecheck)

# The five grammar examples pinned in tests/test_contracts.py.
EXAMPLES = [
    "exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)",
    "exists v: Vehicle: holds_for >= 120 in_zone(v, dock) when hour in [6, 22]",
    "exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)",
    "exists p: Person, k: Carryable: (carrying(p, k) or near(p, k)) then[?a, ?b] leaves(p, porch) "
    "when subtype = human and device = ava1.ring.device.ABC",
    "exists k: Package: always[0, ?d] in_zone(k, steps) and not eventually[0, ?d] present(k)",
]


def at(pred, *args):
    return Atom(pred=pred, args=tuple(args))


# ------------------------------------------------------------------ parse
@pytest.mark.parametrize("text", EXAMPLES)
def test_contract_examples_parse_typecheck_and_roundtrip(text):
    r = parse(text)
    assert typecheck(r) == []
    assert to_text(r) == text                    # the contract examples are already canonical
    assert parse(to_text(r)) == r


def test_parse_builds_expected_ast():
    r = parse("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch) when hour in [6, 22]")
    assert r == Rule(vars=(VarDecl(name="p", type="Person"), VarDecl(name="k", type="Package")),
                     body=Then(a=0.0, b=Hole(name="b"), left=at("picks_up", "p", "k"), right=at("leaves", "p", "porch")),
                     when=(HourIn(h1=6, h2=22),))
    assert isinstance(r.when[0].h1, int) and isinstance(r.body.a, float)


def test_numbers_become_floats_hours_ints():
    r = parse("exists p: Person: eventually[0.5, 1e1] present(p) when hour in [6, 22]")
    assert r.body.a == 0.5 and r.body.b == 10.0 and isinstance(r.body.b, float)
    assert r.when[0].h1 == 6 and isinstance(r.when[0].h1, int)


def test_and_or_are_flattened_n_ary():
    r = parse("exists p: Person: present(p) and (facing_camera(p) and rings_bell(p)) and near(p, p)")
    assert isinstance(r.body, And) and len(r.body.args) == 4
    r = parse("exists p: Person: (present(p) or rings_bell(p)) or (facing_camera(p) or near(p, p))")
    assert isinstance(r.body, Or) and len(r.body.args) == 4
    # different operators are not merged
    r = parse("exists p: Person: present(p) and (rings_bell(p) or facing_camera(p))")
    assert isinstance(r.body.args[1], Or)


def test_precedence_or_and_then_unary():
    r = parse("exists p: Person: present(p) or rings_bell(p) and facing_camera(p)")
    assert isinstance(r.body, Or) and isinstance(r.body.args[1], And)
    r = parse("exists p: Person: present(p) and rings_bell(p) then[0, 1] facing_camera(p)")
    assert isinstance(r.body, And) and isinstance(r.body.args[1], Then)
    r = parse("exists p: Person: not eventually[0, 1] present(p) and rings_bell(p)")
    assert isinstance(r.body, And) and isinstance(r.body.args[0], Not) and isinstance(r.body.args[0].arg, Eventually)


def test_then_is_left_associative():
    r = parse("exists p: Person: present(p) then[0, 1] rings_bell(p) then[0, 2] facing_camera(p)")
    assert isinstance(r.body, Then) and r.body.b == 2.0 and isinstance(r.body.left, Then) and r.body.left.b == 1.0
    r = parse("exists p: Person: present(p) then[0, 1] (rings_bell(p) then[0, 2] facing_camera(p))")
    assert isinstance(r.body.right, Then) and r.body.right.b == 2.0


@pytest.mark.parametrize("text", ["exists p: Person: not (present(p))", "exists p: Person: not(present(p) or rings_bell(p))",
                                  "exists p: Person: present(p) and not (rings_bell(p))"])
def test_not_followed_by_parenthesis(text):
    """Regression: the contract grammar lexes 'not (' as a predicate name; parse() re-tags the keyword."""
    r = parse(text)
    assert typecheck(r) == [] and "not" in to_text(r) and parse(to_text(r)) == r


def test_context_atoms():
    r = parse("exists p: Person: present(p) when subtype = package_delivery and device = ava1.ring.device.X-1 "
              "and hour in [?h1, 5]")
    assert r.when == (SubtypeEq(value="package_delivery"), DeviceEq(value="ava1.ring.device.X-1"),
                      HourIn(h1=Hole(name="h1"), h2=5))


def test_whitespace_and_newlines_are_insignificant():
    a = parse("exists p: Person,\n   k: Package:\n picks_up(p,k)\n then[0,?b]\n leaves(p,porch)")
    assert a == parse("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)")


@pytest.mark.parametrize("text,line,col,frag", [
    ("", 1, 1, "expected 'exists'"),
    ("exists p Person: present(p)", 1, 10, "expected ':'"),
    ("exists p: Person: present(p", 1, 28, "expected ')' or ','"),
    ("exists p: Person: present(p) then present(p)", 1, 35, "expected '['"),
    ("exists p: Person: eventually[0 5] present(p)", 1, 32, "unexpected '5'; expected ','"),
    ("exists p: Person: Present(p)", 1, 19, "expected a formula"),
    ("exists p: Person: present(p) when hour in [6.5, 7]", 1, 44, "whole numbers"),
    ("exists p: Person: present(p) when subtype = foo", 1, 45, "unknown subtype 'foo'; known: human"),
    ("exists p: Person: present(p) and", 1, 33, "unexpected end of input"),
    ("exists p: Person: holds_for > 5 present(p)", 1, 29, "unexpected character '>'"),
    ("exists p: Person:\n  present(p)\n  and 5", 3, 7, "unexpected '5'"),
    ("exists p: Person: present(p) when hour in [6, 7] and", 1, 53, "'hour'"),
    ("exists p: Person: present(p) @", 1, 30, "unexpected character '@'"),
])
def test_syntax_errors_have_position_and_message(text, line, col, frag):
    with pytest.raises(DSLSyntaxError) as ei:
        parse(text)
    e = ei.value
    assert (e.line, e.column) == (line, col)
    assert frag in e.message and str(e).startswith(f"line {line}, column {col}: ")
    assert "^" in e.context


# ------------------------------------------------------------------ printer
def test_number_formatting():
    assert [fmt_num(x) for x in (20.0, 0.0, 0.5, 1.25, 0.333333, 7.0001, 1e-9, 120)] == \
        ["20", "0", "0.5", "1.25", "0.333", "7", "0", "120"]
    assert fmt_num(0.333333, exact=True) == "0.333333" and fmt_num(1.25, exact=True) == "1.25"
    assert fmt_num(1e-9, exact=True) == "1e-09" and fmt_num(2.0, exact=True) == "2"


def test_to_text_minimal_parentheses():
    cases = {
        "exists p: Person: present(p) and rings_bell(p) or facing_camera(p)":
            "exists p: Person: present(p) and rings_bell(p) or facing_camera(p)",
        "exists p: Person: (present(p) or rings_bell(p)) and facing_camera(p)":
            "exists p: Person: (present(p) or rings_bell(p)) and facing_camera(p)",
        "exists p: Person: (present(p) and rings_bell(p)) or facing_camera(p)":
            "exists p: Person: present(p) and rings_bell(p) or facing_camera(p)",
        "exists p: Person: ((present(p)))": "exists p: Person: present(p)",
        "exists p: Person: not (not present(p))": "exists p: Person: not not present(p)",
        "exists p: Person: not (present(p) then[0, 1] rings_bell(p))":
            "exists p: Person: not (present(p) then[0, 1] rings_bell(p))",
        "exists p: Person: eventually[0, 1] (present(p) and rings_bell(p))":
            "exists p: Person: eventually[0, 1] (present(p) and rings_bell(p))",
        "exists p: Person: (eventually[0, 1] present(p)) and rings_bell(p)":
            "exists p: Person: eventually[0, 1] present(p) and rings_bell(p)",
        "exists p: Person: (present(p) then[0, 1] rings_bell(p)) then[0, 2] facing_camera(p)":
            "exists p: Person: present(p) then[0, 1] rings_bell(p) then[0, 2] facing_camera(p)",
        "exists p: Person: present(p) then[0, 1] (rings_bell(p) then[0, 2] facing_camera(p))":
            "exists p: Person: present(p) then[0, 1] (rings_bell(p) then[0, 2] facing_camera(p))",
        "exists p: Person: holds_for >= 2.50 (present(p) or rings_bell(p))":
            "exists p: Person: holds_for >= 2.5 (present(p) or rings_bell(p))",
    }
    for src, want in cases.items():
        r = parse(src)
        assert to_text(r) == want, src
        assert parse(want) == r


def test_to_text_accepts_subnodes():
    r = parse("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch) when hour in [6, 22]")
    assert to_text(r.body) == "picks_up(p, k) then[0, ?b] leaves(p, porch)"
    assert to_text(r.body.left) == "picks_up(p, k)"
    assert to_text(r.when[0]) == "hour in [6, 22]"


def test_normalize_flattens_hand_built_nesting():
    nested = Rule(vars=(VarDecl(name="p", type="Person"),),
                  body=And(args=(And(args=(at("present", "p"), at("rings_bell", "p"))), at("facing_camera", "p"))))
    flat = normalize(nested)
    assert len(flat.body.args) == 3 and parse(to_text(flat)) == flat
    assert normalize(flat) == flat


# ------------------------------------------------------------------ typecheck
def tc(text):
    return typecheck(parse(text))


def test_typecheck_ok():
    assert tc("exists p: Person, k: Package: picks_up(p, k) then[0, 20] leaves(p, porch)") == []
    assert tc("exists p: Person, k: Carryable: picks_up(p, k)") == []
    assert tc("exists e: Entity, p: Person: near(e, p) and attr(e, hoodie)") == []
    assert tc("exists p: Person: eventually[?a, ?b] present(p) when hour in [?h, 3]") == []


def test_unknown_predicate_message_lists_known_predicates():
    (msg,) = tc("exists p: Person: rings_doorbell(p)")
    assert msg == ("unknown predicate 'rings_doorbell'; known: present, in_zone, near, carrying, picks_up, "
                   "puts_down, rings_bell, enters, leaves, facing_camera, attr")


def test_arity():
    (msg,) = tc("exists p: Person: rings_bell(p, p)")
    assert msg == "rings_bell takes 1 argument (rings_bell(Person)), got 2: rings_bell(p, p)"
    assert "takes 2 arguments (in_zone(Entity, Zone)), got 1" in tc("exists p: Person: in_zone(p)")[0]
    assert "got 0" in tc("exists p: Person: present()")[0]


def test_variable_type_compatibility():
    (m,) = tc("exists p: Entity: rings_bell(p)")
    assert m == "argument 1 of rings_bell must be a Person variable (rings_bell(Person)), but 'p' is declared Entity"
    assert tc("exists p: Person, k: Package: picks_up(k, p)") == [
        "argument 1 of picks_up must be a Person variable (picks_up(Person, Carryable)), but 'k' is declared Package",
        "argument 2 of picks_up must be a Carryable (Package or Object) variable (picks_up(Person, Carryable)), "
        "but 'p' is declared Person"]
    assert tc("exists p: Person, k: Vehicle: carrying(p, k)")[0].endswith("but 'k' is declared Vehicle")
    # Package and Object both fit a Carryable slot; Carryable does not fit a Package-only slot (none exists), and
    # a Carryable does not fit a Person slot
    assert tc("exists p: Person, k: Object: carrying(p, k)") == []
    assert tc("exists p: Carryable: rings_bell(p)")[0].endswith("declared Carryable")


def test_zone_label_and_variable_slots():
    assert tc("exists p: Person: in_zone(p, garage)") == [
        "argument 2 of in_zone: 'garage' is not a zone; zones are: door, porch, steps, yard, driveway, sidewalk, street, dock"]
    assert "not the variable 'p'" in tc("exists p: Person: in_zone(p, p)")[0]
    assert "not the zone 'porch'" in tc("exists p: Person: in_zone(porch, porch)")[0]
    assert tc("exists p: Person, k: Package: attr(p, k) and present(k)") == [
        "argument 2 of attr must be a label literal such as hoodie or delivery_uniform, not the variable 'k'"]
    assert tc("exists p: Person: attr(p, delivery_uniform) and near(p, q)") == [
        "undeclared variable 'q' in near(p, q); declared variables: p: Person"]


def test_variable_declarations():
    assert tc("exists p: Person, p: Package: present(p)") == [
        "variable 'p' is declared more than once; every variable needs a unique name"]
    assert tc("exists p: Person, k: Package: present(p)") == ["variable 'k' is declared but never used in the formula"]
    assert tc("exists door: Person: present(door)") == [
        "variable name 'door' clashes with the zone 'door'; rename the variable"]
    # an unknown predicate does not cascade into 'never used' errors
    assert len(tc("exists p: Person: rings_doorbell(p)")) == 1


def test_numeric_bounds():
    assert tc("exists p: Person: eventually[5, 2] present(p)") == [
        "eventually[5, 2]: the lower bound must be <= the upper bound (needs 0 <= a <= b)"]
    assert tc("exists p: Person: present(p) then[0, 5] present(p) then[3, 1] present(p)")[0].startswith("then[3, 1]")
    assert tc("exists p: Person: eventually[?a, 1] present(p) and always[2, ?b] present(p)") == []
    r = Rule(vars=(VarDecl(name="p", type="Person"),),
             body=And(args=(Eventually(a=-1.0, b=2.0, arg=at("present", "p")), HoldsFor(d=-3.0, arg=at("present", "p")),
                            Always(a=0.0, b=float("inf"), arg=at("present", "p")))))
    msgs = typecheck(r)
    assert any("must be >= 0, got -1" in m for m in msgs) and any("holds_for" in m and "-3" in m for m in msgs)
    assert any("finite" in m for m in msgs)


def test_hours_and_context():
    assert tc("exists p: Person: present(p) when hour in [0, 23]") == []
    assert tc("exists p: Person: present(p) when hour in [6, 22] and hour in [22, 6]") == []
    (m,) = tc("exists p: Person: present(p) when hour in [6, 24]")
    assert m == "hour in [...]: hours must be whole numbers between 0 and 23, got 24"
    r = Rule(vars=(VarDecl(name="p", type="Person"),), body=at("present", "p"), when=(DeviceEq(value="bad id!"),))
    assert "device id" in typecheck(r)[0]


def test_typecheck_covers_every_predicate_signature():
    """Each predicate accepts a well-typed use and rejects arity errors."""
    uses = {"present": "present(e)", "in_zone": "in_zone(e, yard)", "near": "near(e, e2)", "carrying": "carrying(p, c)",
            "picks_up": "picks_up(p, c)", "puts_down": "puts_down(p, c)", "rings_bell": "rings_bell(p)",
            "enters": "enters(e, door)", "leaves": "leaves(e, door)", "facing_camera": "facing_camera(p)",
            "attr": "attr(e, hoodie)"}
    assert set(uses) == set(PREDICATES)
    for pred, use in uses.items():
        r = parse(f"exists e: Entity, e2: Entity, p: Person, c: Carryable: {use} and "
                  f"present(e) and present(e2) and rings_bell(p) and picks_up(p, c)")
        assert typecheck(r) == [], pred


# ------------------------------------------------------------------ English
def en(text):
    return to_english(parse(text))


def test_english_spec_example():
    assert en("exists p: Person, k: Package: picks_up(p, k) then[0, 20] leaves(p, porch)") == \
        "There is a person p and a package k such that p picks up k, and then within 0 to 20 s p leaves the porch."


def test_english_holes_context_and_variables():
    assert en("exists p: Person, k: Carryable, v: Vehicle: (carrying(p, k) or near(p, v)) then[?a, ?b] leaves(p, porch)"
              " when subtype = human and device = ava1.ring.device.ABC") == (
        "There is a person p, a package or object k and a vehicle v such that (p is carrying k or p is near v), "
        "and then within ?a to ?b s p leaves the porch, when the event sub-type is human and the device is "
        "ava1.ring.device.ABC.")
    assert en("exists a: Animal, o: Object, e: Entity: near(a, o) and present(e)") == \
        "There is an animal a, an object o and an entity e such that a is near o and e is present."
    assert en("exists v: Vehicle: holds_for >= 120 in_zone(v, dock) when hour in [6, 22]") == \
        "There is a vehicle v such that v is at the dock continuously for at least 120 s, when the local hour is between 6 and 22 inclusive."
    assert en("exists v: Vehicle: present(v) when hour in [22, 6]").endswith("when the local hour is 22 or later, or 6 or earlier.")
    assert en("exists v: Vehicle: present(v) when hour in [?h1, 6]").endswith("in [?h1, 6] (inclusive; wraps past midnight if the first is larger).")
    assert en("exists p: Person: present(p) when subtype = package_delivery") == \
        "There is a person p such that p is present, when the event sub-type is package delivery."


def test_english_every_predicate_and_negation():
    cases = {
        "present(p)": ("p is present", "p is not present"),
        "in_zone(p, steps)": ("p is on the steps", "p is not on the steps"),
        "near(p, q)": ("p is near q", "p is not near q"),
        "carrying(p, k)": ("p is carrying k", "p is not carrying k"),
        "picks_up(p, k)": ("p picks up k", "p does not pick up k"),
        "puts_down(p, k)": ("p puts down k", "p does not put down k"),
        "rings_bell(p)": ("p rings the doorbell", "p does not ring the doorbell"),
        "enters(p, yard)": ("p enters the yard", "p does not enter the yard"),
        "leaves(p, dock)": ("p leaves the dock", "p does not leave the dock"),
        "facing_camera(p)": ("p faces the camera", "p does not face the camera"),
        "attr(p, hi_vis)": ('p has the attribute "hi vis"', 'p does not have the attribute "hi vis"'),
    }
    for atom, (pos, neg) in cases.items():
        decl = "exists p: Person, q: Person, k: Carryable"
        assert en(f"{decl}: {atom} and present(q) and present(k)") == \
            f"There is a person p, a person q and a package or object k such that {pos} and q is present and k is present."
        assert en(f"{decl}: not {atom} and present(q) and present(k)").split(" such that ")[1].startswith(neg + " and")
    for z, phrase in {"door": "at the door", "porch": "on the porch", "steps": "on the steps", "yard": "in the yard",
                      "driveway": "in the driveway", "sidewalk": "on the sidewalk", "street": "in the street",
                      "dock": "at the dock"}.items():
        assert en(f"exists p: Person: in_zone(p, {z})") == f"There is a person p such that p is {phrase}."


def test_english_operators_and_scope_parentheses():
    assert en("exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)") == (
        "There is a person p such that (at some point within 0 to 30 s, p is at the door) and "
        "at no point within 0 to 30 s, p rings the doorbell.")
    assert en("exists p: Person: always[0, 5] present(p)") == \
        "There is a person p such that at every moment within 0 to 5 s, p is present."
    assert en("exists p: Person: not (present(p) or facing_camera(p))") == \
        "There is a person p such that it is not the case that (p is present or p faces the camera)."
    assert en("exists p: Person: not always[0, 5] present(p)") == \
        "There is a person p such that it is not the case that at every moment within 0 to 5 s, p is present."
    assert en("exists p: Person: present(p) or rings_bell(p) and facing_camera(p)") == \
        "There is a person p such that p is present or (p rings the doorbell and p faces the camera)."
    assert en("exists p: Person: (present(p) or rings_bell(p)) and facing_camera(p)") == \
        "There is a person p such that (p is present or p rings the doorbell) and p faces the camera."
    assert en("exists p: Person: present(p) then[0, 1] rings_bell(p) then[0, 2] facing_camera(p)") == (
        "There is a person p such that (p is present, and then within 0 to 1 s p rings the doorbell), "
        "and then within 0 to 2 s p faces the camera.")
    assert en("exists p: Person: present(p) and eventually[1.5, 2.25] rings_bell(p)") == \
        "There is a person p such that p is present and at some point within 1.5 to 2.25 s, p rings the doorbell."
    assert en("exists v: Vehicle: holds_for >= ?d (present(v) and in_zone(v, dock))") == \
        "There is a vehicle v such that (v is present and v is at the dock) continuously for at least ?d s."


def test_english_is_deterministic_and_handles_nodes():
    r = parse("exists p: Person, k: Package: picks_up(p, k) then[0, 20] leaves(p, porch) when hour in [6, 22]")
    assert to_english(r) == to_english(parse(to_text(r)))
    assert to_english(r.body) == "p picks up k, and then within 0 to 20 s p leaves the porch"
    assert to_english(r.when[0]) == "the local hour is between 6 and 22 inclusive"
    assert to_english(r.vars[0]) == "a person p"
