"""Mutation check: the differential test of the Z3 encoder must notice a planted encoder bug.

`test_synth_encoding.py` asserts that the Z3 encoding agrees with the NumPy evaluator.  An agreement test is only worth
something if it fails when the encoder is wrong, so each case below monkeypatches one realistic bug into the encoder
(an off-by-one on a window edge, a dropped GE / LE swap, a lost midnight wrap, ...) and checks that the same comparison
(`check_encoding`) reports a mismatch.  The harness is a few hand-built cases plus derandomized Hypothesis streams
without an example database, so the result is the same on every run (every bug below is already caught by the
hand-built cases alone).  A control case runs the unmutated encoder through the identical harness and must pass.

    uv run --project engine pytest engine/tests/synth/test_synth_mutations.py
"""
from __future__ import annotations

import random
from fractions import Fraction

import pytest
import z3
from hypothesis import HealthCheck, Phase, assume, given, settings
from hypothesis import strategies as st

from exemplar.contracts.trace import Entity, Fact, Frame, Trace, TraceContext
from exemplar.dsl import parse, typecheck
from exemplar.synth import Example, z3enc
from synth_support import hole_candidates, instances
from test_synth_encoding import check_encoding, focused_instances

_HC = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]


# ---------------------------------------------------------------------------------------------------- the harness
def _differential(strategy, *, max_examples: int, points: int) -> None:
    """The comparison of `test_synth_encoding.py` on a derandomized stream of instances; raises on a mismatch."""

    @settings(max_examples=max_examples, deadline=None, database=None, derandomize=True,
              phases=[Phase.generate], report_multiple_bugs=False, suppress_health_check=_HC)
    @given(strategy, st.randoms(use_true_random=False))
    def prop(inst, rnd: random.Random) -> None:
        sketch, examples = inst
        assume(not typecheck(sketch))
        cands = hole_candidates(sketch, examples)
        check_encoding(sketch, examples, [{h: rnd.choice(v) for h, v in cands.items()} for _ in range(points)])

    prop()


# Hand-built cases for the operators where random traces rarely hit the discriminating shape: a hole exactly on a frame
# gap, a `then` / `holds_for` nested inside a bounded operator (docs/DSL.md, convention 3), an empty window, a window
# across midnight.  Frames at 0, 2, 6 and 7 s; the second clip never carries the package.
def _fact(pred: str, *args: str) -> Fact:
    return Fact(pred=pred, args=args, conf="high")


_ENTITIES = (Entity(id="p1", type="person"), Entity(id="k1", type="package"))
_CLIP_A = Trace(clip_id="m0", source="fixture", duration_ms=7000, entities=_ENTITIES,
                context=TraceContext(sub_type="human", local_hour=23),
                frames=(Frame(t_ms=0), Frame(t_ms=2000), Frame(t_ms=6000, facts=(_fact("picks_up", "p1", "k1"),)),
                        Frame(t_ms=7000, facts=(_fact("carrying", "p1", "k1"),))))
_CLIP_B = Trace(clip_id="m1", source="fixture", duration_ms=7000, entities=_ENTITIES,
                context=TraceContext(sub_type="human", local_hour=3),
                frames=(Frame(t_ms=0, facts=(_fact("picks_up", "p1", "k1"),)), Frame(t_ms=2000),
                        Frame(t_ms=6000), Frame(t_ms=7000)))
_EXAMPLES = [Example(_CLIP_A, True, 1.0, "m0"), Example(_CLIP_B, False, 1.0, "m1")]
_TARGETED = [
    "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] carrying(p, k)",
    "exists p: Person, k: Package: eventually[0, ?b] (picks_up(p, k) then[0, ?c] carrying(p, k))",
    "exists p: Person, k: Package: always[?a, ?b] holds_for >= ?d carrying(p, k)",
    "exists p: Person, k: Package: not eventually[?a, ?b] carrying(p, k)",
    "exists p: Person, k: Package: eventually[0, 10] carrying(p, k) when hour in [?h1, ?h2]",
]


def _targeted() -> None:
    rnd = random.Random(11)
    for text in _TARGETED:
        sketch = parse(text)
        assert not typecheck(sketch), text
        cands = hole_candidates(sketch, _EXAMPLES)
        check_encoding(sketch, _EXAMPLES, [{h: rnd.choice(v) for h, v in cands.items()} for _ in range(40)])


def _run_harness() -> None:
    """The hand-built cases, then random sketches (every operator, context atoms), then temporal operators on top of
    small bodies: the three comparisons of `test_synth_encoding.py`."""
    _targeted()
    _differential(instances(max_frames=8, max_holes=3, n_examples=(1, 2)), max_examples=40, points=4)
    _differential(focused_instances(), max_examples=40, points=5)


# ---------------------------------------------------------------------------------------------------- the bugs
def _lower_ok_strict(self, a, diff_ms):
    """Window lower edge: `a < gap` instead of `a <= gap` (a hole placed exactly on a frame gap falls out)."""
    if isinstance(a, str):
        return False if diff_ms < 0 else self.hv[a] < self.rv(Fraction(diff_ms, 1000))
    return bool(a <= diff_ms / 1000)


def _upper_ok_strict(self, b, diff_ms):
    """Window upper edge: `gap < b` instead of `gap <= b`."""
    if isinstance(b, str):
        return True if diff_ms <= 0 else self.hv[b] > self.rv(Fraction(diff_ms, 1000))
    return bool(diff_ms / 1000 <= b)


def _ge_const_strict(self, c):
    """A constant robustness equal to the margin no longer satisfies `rho >= m`."""
    return c > self.margin


def _not_forgets_the_swap(original):
    def _vec(self, n, bind):
        if n.op == "not":
            return self.vec(n.kids[0], bind)             # GE and LE of the operand are not exchanged
        return original(self, n, bind)
    return _vec


def _suffix_searches_one_start(self, xs, combine):
    """`then` / `holds_for` look only at the start frame i instead of every later start i1 >= i."""
    return list(xs)


def _empty_window_is_nonempty(self, a, b):
    """An empty `always` window counts as non-empty (vacuous truth instead of robustness -C)."""
    return [True] * self.T


def _hour_without_midnight_wrap(self, c, hour):
    """`hour in [h1, h2]` with h1 > h2 (a window across midnight) is treated as empty."""
    if hour is None:
        return False
    h1 = self.hv[c.h1.name] if isinstance(c.h1, z3enc.Hole) else z3.IntVal(c.h1, self.ctx)
    h2 = self.hv[c.h2.name] if isinstance(c.h2, z3enc.Hole) else z3.IntVal(c.h2, self.ctx)
    return z3.And(h1 <= h2, h1 <= hour, hour <= h2)


def _plant(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    enc, ex = z3enc.Encoder, z3enc._ExampleEncoder
    if name == "window lower edge is strict":
        monkeypatch.setattr(enc, "lower_ok", _lower_ok_strict)
    elif name == "window upper edge is strict":
        monkeypatch.setattr(enc, "upper_ok", _upper_ok_strict)
    elif name == "margin comparison is strict":
        monkeypatch.setattr(enc, "ge_const", _ge_const_strict)
    elif name == "negation does not swap GE and LE":
        monkeypatch.setattr(ex, "_vec", _not_forgets_the_swap(ex._vec))
    elif name == "then / holds_for search one start only":
        monkeypatch.setattr(ex, "_suffix", _suffix_searches_one_start)
    elif name == "empty always window is vacuously true":
        monkeypatch.setattr(ex, "nonempty", _empty_window_is_nonempty)
    elif name == "hour window loses its midnight wrap":
        monkeypatch.setattr(enc, "_hour_expr", _hour_without_midnight_wrap)
    else:  # pragma: no cover
        raise AssertionError(name)


BUGS = [
    "window lower edge is strict",
    "window upper edge is strict",
    "margin comparison is strict",
    "negation does not swap GE and LE",
    "then / holds_for search one start only",
    "empty always window is vacuously true",
    "hour window loses its midnight wrap",
]


# ---------------------------------------------------------------------------------------------------- the tests
def test_control_unmutated_encoder_passes_the_harness():
    _run_harness()


@pytest.mark.parametrize("bug", BUGS)
def test_differential_check_catches_planted_encoder_bug(monkeypatch, bug):
    _plant(monkeypatch, bug)
    with pytest.raises(AssertionError, match=r"'(GE|LE)'"):             # a GE / LE mismatch, nothing else
        _run_harness()
