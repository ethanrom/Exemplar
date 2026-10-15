import random

import pytest

from eval.data import annotations as A
from eval.data import windows as W

V = 300_000  # 5-minute video


def _act(name, f0, f1, act_id=1):
    return A.Activity("v", name, act_id, (1,), f0, f1, A.frame_to_ms(f0), A.frame_to_ms(f1 + 1))


@pytest.mark.parametrize("seed", range(40))
def test_window_around_invariants(seed):
    rng = random.Random(seed)
    s = rng.randint(0, V - 12_000)
    e = s + rng.randint(1_000, 10_000)
    w = W.window_around(s, e, V, rng)
    assert w is not None
    assert W.MIN_MS <= w.dur_ms <= W.MAX_MS
    assert 0 <= w.start_ms and w.end_ms <= V
    assert w.start_ms <= s and e <= w.end_ms  # contains the whole instance


def test_window_around_edges_and_impossible():
    rng = random.Random(0)
    w = W.window_around(0, 3_000, V, rng)  # instance at the very start: padding only on the right
    assert w is not None and w.start_ms == 0
    w = W.window_around(V - 2_000, V, V, rng)  # instance at the very end
    assert w is not None and w.end_ms == V
    assert W.window_around(0, 25_000, V, rng) is None  # longer than the maximum window
    assert W.window_around(V - 1_000, V + 500, V, rng) is None  # sticks out of the video
    assert W.window_around(5_000, 6_000, V, rng, occupied=[W.Window(0, 12_000)]) is None  # inside an occupied window


def test_window_around_respects_occupied():
    rng = random.Random(1)
    occ = [W.Window(40_000, 15_000)]
    for _ in range(30):
        w = W.window_around(60_000, 64_000, V, rng, occ)
        assert w is not None and w.start_ms >= 55_000


def test_place_positives_dedupes_and_is_deterministic():
    insts = [_act("a", 300, 360, 1), _act("a", 420, 480, 2), _act("a", 3000, 3090, 3)]  # first two are 2 s apart
    w1, sk1 = W.place_positives(insts, V, random.Random(7))
    w2, sk2 = W.place_positives(insts, V, random.Random(7))
    assert w1 == w2 and sk1 == sk2  # deterministic for a seed
    assert len(w1) == 2 and sk1.get("covered_by_earlier_window") == 1
    for a, b in zip(w1, w1[1:]):
        assert a.end_ms <= b.start_ms  # disjoint
    for wi in w1:
        assert W.MIN_MS <= wi.dur_ms <= W.MAX_MS
    assert any(w.start_ms <= insts[2].start_ms and insts[2].end_ms <= w.end_ms for w in w1)


def test_place_positives_skips_instances_beyond_the_video():
    w, sk = W.place_positives([_act("a", 8990, 9059)], V, random.Random(0))
    assert w == [] and sk == {"beyond_video_end": 1}


def _forbidden_ok(w, forbidden, guard):
    return all(not A.overlaps(w.start_ms, w.end_ms, s - guard, e + guard) for s, e in forbidden)


@pytest.mark.parametrize("seed", range(10))
def test_negatives_never_touch_instances(seed):
    rng = random.Random(seed)
    forbidden = [(20_000, 24_000), (100_000, 103_000), (180_000, 186_000), (250_000, 252_000)]
    occupied = [W.Window(10_000, 17_000)]
    anchors = [(60_000, 62_000), (140_000, 143_000)]
    negs = W.sample_negatives(8, V, forbidden, occupied, anchors, rng)
    assert len(negs) == 8
    for i, w in enumerate(negs):
        assert W.MIN_MS <= w.dur_ms <= W.MAX_MS and 0 <= w.start_ms and w.end_ms <= V
        assert _forbidden_ok(w, forbidden, W.GUARD_MS)
        assert not A.overlaps(w.start_ms, w.end_ms, occupied[0].start_ms, occupied[0].end_ms)
        for o in negs[i + 1:]:
            assert not A.overlaps(w.start_ms, w.end_ms, o.start_ms, o.end_ms)
    # hard slots contain a confuser anchor
    hard = [w for w in negs if any(w.start_ms <= s and e <= w.end_ms for s, e in anchors)]
    assert len(hard) >= 2


def test_negatives_deterministic_and_gives_up_gracefully():
    kw = dict(video_ms=V, forbidden=[(50_000, 52_000)], occupied=[], hard_anchors=[])
    a = W.sample_negatives(5, rng=random.Random(3), **kw)
    b = W.sample_negatives(5, rng=random.Random(3), **kw)
    assert a == b
    # more windows requested than fit: returns what fits, never overlapping
    many = W.sample_negatives(100, V, [], [], [], random.Random(0))
    assert 0 < len(many) < 100
    for x, y in zip(many, many[1:]):
        assert x.end_ms <= y.start_ms


def test_allocate_respects_caps_and_total():
    out = W.allocate(10, [1, 1, 1], [2, 20, 20])
    assert sum(out) == 10 and out[0] <= 2
    assert W.allocate(5, [1, 0, 0], [10, 10, 10])[0] == 5
    assert W.allocate(50, [1, 1], [3, 4]) == [3, 4]  # cannot exceed capacity
