"""One sketch on 40 labelled clips x 24 frames solves well inside the 10 s per-sketch timeout."""
from __future__ import annotations

import random
import time

import pytest

from exemplar.contracts.trace import Entity, Fact, Frame, Trace, TraceContext
from exemplar.dsl import parse, to_text
from exemplar.synth import Example, solve_sketch

CONF = ["low", "med", "high"]


def make_trace(seed: int, planted: bool, frames: int = 24) -> Trace:
    """A noisy porch scene; positives get a pick-up followed by leaving the porch a few seconds later."""
    r = random.Random(seed)
    ents = [Entity(id="p1", type="person"), Entity(id="k1", type="package")]
    if r.random() < 0.5:
        ents.append(Entity(id="p2", type="person"))
    if r.random() < 0.3:
        ents.append(Entity(id="v1", type="vehicle"))
    ts = [int((i + 0.5) * 30000 / frames) for i in range(frames)]
    pick, gap = r.randrange(3, 18), r.randrange(1, 6)
    out = []
    for i, t in enumerate(ts):
        facts = []
        if r.random() < 0.7:
            facts.append(Fact(pred="in_zone", args=("k1", r.choice(["porch", "steps"])), conf=r.choice(CONF)))
        if i >= 2 and r.random() < 0.6:
            facts.append(Fact(pred="in_zone", args=("p1", r.choice(["porch", "steps", "yard"])), conf=r.choice(CONF)))
        if r.random() < 0.3:
            facts.append(Fact(pred="near", args=("p1", "k1"), conf=r.choice(CONF)))
        if r.random() < 0.2:
            facts.append(Fact(pred="carrying", args=("p1", "k1"), conf=r.choice(CONF)))
        if r.random() < 0.15:
            facts.append(Fact(pred="leaves", args=("p1", "porch"), conf=r.choice(CONF)))
        if r.random() < 0.1:
            facts.append(Fact(pred="picks_up", args=("p1", "k1"), conf=r.choice(CONF)))
        if planted:
            if i == pick:
                facts.append(Fact(pred="picks_up", args=("p1", "k1"), conf="high"))
            if i == min(frames - 1, pick + gap):
                facts.append(Fact(pred="leaves", args=("p1", "porch"), conf="high"))
        out.append(Frame(t_ms=t, facts=tuple(facts)))
    return Trace(clip_id=f"c{seed}", source="fixture", duration_ms=30000, entities=tuple(ents), frames=tuple(out),
                 context=TraceContext(local_hour=r.randrange(24)))


@pytest.mark.parametrize("sketch", [
    "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch)",
    "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] (carrying(p, k) or leaves(p, porch)) and holds_for >= ?d in_zone(k, porch)",
])
def test_40_clips_x_24_frames_solve_within_the_timeout(sketch):
    ex = [Example(make_trace(i, True), True, 3.0) for i in range(10)] + \
         [Example(make_trace(100 + i, False), False, 1.0) for i in range(30)]
    t0 = time.perf_counter()
    res = solve_sketch(parse(sketch), ex, timeout_s=10.0)
    dt = time.perf_counter() - t0
    print(f"\n40 clips x 24 frames, {len(res.holes)} holes: {res.status} in {dt * 1000:.0f} ms ({to_text(res.rule)})")
    assert res.status == "sat" and res.diff_check_ok
    assert dt < 10.0
