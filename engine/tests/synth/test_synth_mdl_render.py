"""MDL score and the compact trace rendering."""
from __future__ import annotations

import math

import pytest

from exemplar.contracts.dsl_ast import node_count
from exemplar.contracts.ontology import PREDICATES
from exemplar.dsl import parse
from exemplar.synth import mdl, render_trace_text
from exemplar.synth.mdl import BITS_PER_NODE, OPS_ALPHABET
from dsl_helpers import ALL_FIXTURES, load


def test_mdl_formula():
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)")
    assert OPS_ALPHABET == 7 + len(PREDICATES) + 3
    n = node_count(sk)
    assert mdl(sk, 0) == pytest.approx(n * math.log2(OPS_ALPHABET) + 8 * 2)
    assert mdl(sk, 3, lam=4.0) == pytest.approx(mdl(sk, 0) + 12)
    assert mdl(sk, 1, lam=10) == pytest.approx(mdl(sk, 0) + 10)


def test_mdl_prefers_simpler_and_fewer_holes():
    simple = parse("exists k: Package: holds_for >= ?d in_zone(k, steps)")
    bigger = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k) and not attr(p, hoodie)")
    assert mdl(simple, 0) < mdl(bigger, 0)
    assert mdl(simple, 1) > mdl(simple, 0)


def test_mdl_closed_rule_charges_its_numeric_slots():
    sk = parse("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)")
    closed = parse("exists p: Person, k: Package: picks_up(p, k) then[0, 12.5] carrying(p, k)")
    assert mdl(closed, 0) == pytest.approx(mdl(sk, 0))          # 2 slots either way


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_render_is_deterministic_and_complete(name):
    tr = load(name)
    text = render_trace_text(tr)
    assert text == render_trace_text(tr)
    assert text.startswith(f"clip {tr.clip_id}:")
    if tr.status == "ok":
        for e in tr.entities:
            assert e.id in text
        for fr in tr.frames[:1]:
            assert f"t={fr.t_ms / 1000:g}s" in text


def test_render_theft_a_snapshot():
    text = render_trace_text(load("theft_a"))
    assert "entities: p1 person {hoodie}; k1 package {box}" in text
    assert "t=6s: in_zone(p1,porch)[high] picks_up(p1,k1)[high]" in text
    assert "t=16s..20s (2 frames, same facts): (no facts)" in text       # identical empty frames are collapsed
    assert text.count("\n") < 20


def test_render_collapses_runs_and_marks_failures():
    assert "perception failed" in render_trace_text(load("perception_failed"))
    text = render_trace_text(load("unattended_package"))
    assert "same facts" in text and len(text) < 1500
