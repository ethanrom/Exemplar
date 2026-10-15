"""Contract tests (PLAN.md §4 Phase 0). These pin the frozen contracts; streams must keep them green."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest
import yaml
from lark import Lark
from pydantic import TypeAdapter, ValidationError

from exemplar.contracts import gen_schemas
from exemplar.contracts.dsl_ast import (GRAMMAR, And, Atom, Eventually, Hole, HoldsFor, HourIn, Not, Rule, Then,
                                        VarDecl, fill_holes, holes, node_count)
from exemplar.contracts.labels import Label, for_calibration, for_synthesis
from exemplar.contracts.ontology import ABSENT_VALUE, CONF_VALUE
from exemplar.contracts.trace import Trace

CONTRACTS = Path(__file__).parents[1] / "exemplar" / "contracts"
FIXTURES = Path(__file__).parent / "fixtures"
TRACES = sorted((FIXTURES / "traces").glob("*.json"))
WEBHOOKS = sorted((FIXTURES / "webhooks").glob("*.json"))
WEBHOOK_TEST_KEY = "exemplar-test-signing-key"


def load(name: str) -> Trace:
    return Trace.model_validate_json((FIXTURES / "traces" / f"{name}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ trace
def test_fixture_count():
    assert len(TRACES) >= 10 and len(WEBHOOKS) >= 5


@pytest.mark.parametrize("path", TRACES, ids=lambda p: p.stem)
def test_fixture_traces_validate_and_roundtrip(path):
    tr = Trace.model_validate_json(path.read_text(encoding="utf-8"))
    assert Trace.model_validate_json(tr.model_dump_json()) == tr


def test_signal_values_and_implied_presence():
    tr = load("theft_a")
    s = tr.signal("picks_up", ("p1", "k1"))
    assert s.dtype == np.float64 and len(s) == len(tr.frames)
    assert s[3] == CONF_VALUE["high"] and s[0] == ABSENT_VALUE
    # present(p1) is implied by any fact mentioning p1 in that frame
    pres = tr.signal("present", ("p1",))
    assert pres[0] == ABSENT_VALUE and pres[1] == CONF_VALUE["med"] and pres[3] == CONF_VALUE["high"]


def test_attr_signal_uses_clip_level_attrs():
    tr = load("delivery_a")
    assert (tr.signal("attr", ("p1", "delivery_uniform")) == CONF_VALUE["med"]).all()
    assert (tr.signal("attr", ("p1", "hoodie")) == ABSENT_VALUE).all()


def test_times_are_integer_ms():
    tr = load("theft_a")
    assert tr.t_ms.dtype == np.int64 and tr.t_ms[1] == 2000


def test_bindings_are_type_correct_and_distinct():
    tr = load("theft_a")
    assert tr.bindings(("Person", "Package")) == [("p1", "k1")]
    assert tr.bindings(("Person", "Carryable")) == [("p1", "k1")]
    assert tr.bindings(("Vehicle",)) == []
    assert tr.bindings(("Entity", "Entity")) == [("p1", "k1"), ("k1", "p1")]


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["frames"][0]["facts"].append({"pred": "rings_doorbell", "args": ["p1"], "conf": "high"}), "unknown predicate"),
    (lambda d: d["frames"][0]["facts"].append({"pred": "in_zone", "args": ["p1", "garage"], "conf": "high"}), "not a valid Zone"),
    (lambda d: d["frames"][0]["facts"].append({"pred": "picks_up", "args": ["k1", "p1"], "conf": "high"}), "not a valid Person"),
    (lambda d: d["frames"][0]["facts"].append({"pred": "near", "args": ["p1"], "conf": "high"}), "takes 2 args"),
    (lambda d: d["frames"][0]["facts"].append({"pred": "present", "args": ["p9"], "conf": "high"}), "not a valid Entity"),
    (lambda d: d["frames"].reverse(), "strictly increasing"),
])
def test_invalid_traces_rejected(mutate, msg):
    d = json.loads((FIXTURES / "traces" / "theft_a.json").read_text(encoding="utf-8"))
    mutate(d)
    with pytest.raises(ValidationError, match=msg):
        Trace.model_validate(d)


# ------------------------------------------------------------------ DSL
EXAMPLES = [
    "exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)",
    "exists v: Vehicle: holds_for >= 120 in_zone(v, dock) when hour in [6, 22]",
    "exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)",
    "exists p: Person, k: Carryable: (carrying(p, k) or near(p, k)) then[?a, ?b] leaves(p, porch) when subtype = human and device = ava1.ring.device.ABC",
    "exists k: Package: always[0, ?d] in_zone(k, steps) and not eventually[0, ?d] present(k)",
]


@pytest.mark.parametrize("text", EXAMPLES)
def test_grammar_parses_examples(text):
    Lark(GRAMMAR, parser="lalr").parse(text)


@pytest.mark.parametrize("text", ["exists p: Person: not (present(p) or rings_bell(p))",
                                  "exists p: Person: not(present(p))",
                                  "exists p: Person: nothing_pred(p)"])
def test_grammar_not_keyword_vs_predicate(text):
    Lark(GRAMMAR, parser="lalr").parse(text)


def test_grammar_lets_unknown_predicates_through_to_typechecker():
    Lark(GRAMMAR, parser="lalr").parse("exists p: Person: rings_doorbell(p)")


def _theft_rule() -> Rule:
    return Rule(vars=(VarDecl(name="p", type="Person"), VarDecl(name="k", type="Package")),
                body=Then(a=0.0, b=Hole(name="b"), left=Atom(pred="picks_up", args=("p", "k")),
                          right=And(args=(Atom(pred="leaves", args=("p", "porch")),
                                          Not(arg=Eventually(a=0.0, b=Hole(name="b"), arg=Atom(pred="attr", args=("p", "delivery_uniform"))))))),
                when=(HourIn(h1=Hole(name="h1"), h2=22),))


def test_rule_json_roundtrip():
    r = _theft_rule()
    ta = TypeAdapter(Rule)
    assert ta.validate_json(ta.dump_json(r)) == r


def test_holes_fill_and_count():
    r = _theft_rule()
    assert holes(r) == ["b", "h1"]
    closed = fill_holes(r, {"b": 20.0, "h1": 6.4})
    assert holes(closed) == [] and closed.body.b == 20.0 and closed.when[0].h1 == 6
    assert r.body.b == Hole(name="b")       # immutable: original untouched
    assert node_count(r) == 9               # rule, then, atom, and, atom, not, eventually, atom, hour_in
    assert node_count(Rule(vars=(VarDecl(name="v", type="Vehicle"),),
                           body=HoldsFor(d=120.0, arg=Atom(pred="in_zone", args=("v", "dock"))))) == 3


def test_and_requires_two_children():
    with pytest.raises(ValidationError):
        And(args=(Atom(pred="present", args=("p",)),))


# ------------------------------------------------------------------ labels
def test_label_provenance_partition():
    ls = [Label(concept_id="c", clip_id=f"x{i}", value="neg", provenance=p) for i, p in enumerate(["example", "active", "random"])]
    assert [l.provenance for l in for_synthesis(ls)] == ["example", "active"]
    assert [l.provenance for l in for_calibration(ls)] == ["random"]
    assert not set(map(id, for_synthesis(ls))) & set(map(id, for_calibration(ls)))


# ------------------------------------------------------------------ SQL
def test_schema_sql_applies_idempotently():
    sql = (CONTRACTS / "schema.sql").read_text(encoding="utf-8")
    db = sqlite3.connect(":memory:")
    db.executescript(sql)
    db.executescript(sql)
    tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    assert {"events", "clips", "traces", "concepts", "labels", "runs", "run_events", "rules", "firings",
            "actions_log", "webhook_deliveries", "cost_ledger", "ring_auth"} <= tables
    db.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into clips (id, event_id, created_at_ms) values ('c1', 'missing', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into events (id, source, start_ms, created_at_ms) values ('e1', 'youtube', 0, 0)")


# ------------------------------------------------------------------ API
def test_generated_schemas_up_to_date():
    assert gen_schemas.main.__module__ and gen_schemas.render().keys() == {"Trace", "Rule", "Label"}
    for name, text in gen_schemas.render().items():
        assert (CONTRACTS / "schemas" / f"{name}.json").read_text(encoding="utf-8") == text, \
            "run: uv run --project engine python -m exemplar.contracts.gen_schemas"


def test_api_yaml_is_valid_openapi():
    from openapi_spec_validator import validate
    spec = yaml.safe_load((CONTRACTS / "api.yaml").read_text(encoding="utf-8"))
    validate(spec, base_uri=(CONTRACTS / "api.yaml").as_uri())
    ops = [op["operationId"] for path in spec["paths"].values() for op in path.values()]
    assert len(ops) == len(set(ops))


# ------------------------------------------------------------------ webhooks
def _verify(raw: bytes, header: str | None) -> bool:
    """Reference verifier (notifications.md): HMAC-SHA256 over the raw body, key used as-is."""
    if not header or not header.startswith("sha256="):
        return False
    want = hmac.new(WEBHOOK_TEST_KEY.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, header[len("sha256="):])


@pytest.mark.parametrize("path", WEBHOOKS, ids=lambda p: p.stem)
def test_webhook_fixtures_signatures(path):
    w = json.loads(path.read_text(encoding="utf-8"))
    ok = _verify(w["body"].encode(), w["headers"].get("X-Signature"))
    assert ok == (w["expect"] in ("accept", "duplicate"))


def test_duplicate_fixture_shares_request_id():
    a = json.loads(json.loads((FIXTURES / "webhooks" / "motion_human.json").read_text(encoding="utf-8"))["body"])
    b = json.loads(json.loads((FIXTURES / "webhooks" / "duplicate.json").read_text(encoding="utf-8"))["body"])
    assert a["meta"]["request_id"] == b["meta"]["request_id"]
