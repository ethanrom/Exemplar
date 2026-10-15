"""Metric arithmetic: conformal threshold, confusion / PRF, Clopper-Pearson, escalation band, cost per event."""
import math

import pytest

from eval.harness import metrics


def test_conformal_rank_matches_the_plan_formula():
    assert metrics.conformal_k(9, 0.1) == 9          # ceil(10 * 0.9)
    assert metrics.conformal_k(19, 0.1) == 18        # ceil(20 * 0.9)
    assert metrics.conformal_k(20, 0.1) == 19        # ceil(21 * 0.9) = ceil(18.9)
    assert metrics.conformal_k(8, 0.1) == 9          # ceil(9 * 0.9) = ceil(8.1) = 9 > n: no guarantee


def test_threshold_is_the_kth_smallest_negative():
    neg = [0.3, -0.5, 0.1, -0.45, 0.2, -0.45, -0.5, 0.0, 0.4]       # n = 9 -> k = 9 -> the maximum
    th = metrics.conformal_threshold(neg, 0.1)
    assert th.guarantee and th.k == 9 and th.n == 9 and th.tau == 0.4
    neg20 = [-0.45] * 17 + [0.1] * 3
    th = metrics.conformal_threshold(neg20, 0.1)
    assert th.k == 19 and th.tau == 0.1


def test_threshold_without_enough_negatives_falls_back_and_flags_no_guarantee():
    th = metrics.conformal_threshold([0.1] * 8, 0.1, fallback=0.5)
    assert not th.guarantee and th.k is None and th.tau == 0.5 and th.n == 8
    assert not metrics.conformal_threshold([], 0.1).guarantee
    with pytest.raises(ValueError):
        metrics.conformal_threshold([0.1], 1.5)


def test_fire_is_strictly_above_tau():
    assert not metrics.fires(0.1, 0.1) and metrics.fires(0.1000001, 0.1)


def test_confusion_and_prf_hand_example():
    scores = [0.9, 0.8, 0.2, 0.7, 0.1, 0.05, 0.6, 0.3]
    pos = [True, True, True, False, False, False, False, True]
    c = metrics.confusion(scores, pos, 0.5)
    assert (c.tp, c.fp, c.fn, c.tn) == (2, 2, 2, 2)
    m = metrics.prf(c)
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["f1"] == 0.5 and m["false_alarm_rate"] == 0.5
    with pytest.raises(ValueError):
        metrics.confusion([1.0], [True, False], 0.5)


def test_prf_degenerate_cases_are_zero_not_nan():
    m = metrics.prf(metrics.confusion([0.0, 0.0], [True, False], 0.5))     # nothing fires
    assert m == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "false_alarm_rate": 0.0}
    m = metrics.prf(metrics.confusion([1.0, 1.0], [False, False], 0.5))    # no positives at all
    assert m["recall"] == 0.0 and m["f1"] == 0.0 and m["false_alarm_rate"] == 1.0


def test_clopper_pearson_known_values():
    lo, hi = metrics.clopper_pearson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(1 - 0.025 ** (1 / 10), abs=1e-9)        # 0.3085
    lo, hi = metrics.clopper_pearson(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.025 ** (1 / 10), abs=1e-9)
    lo, hi = metrics.clopper_pearson(5, 20)
    assert (lo, hi) == pytest.approx((0.0866, 0.4910), abs=2e-4)
    assert metrics.clopper_pearson(0, 0) == (0.0, 1.0)


def test_escalation_band_fraction():
    scores = [0.0, 0.05, 0.15, 0.3, -0.5]
    assert metrics.escalated_fraction(scores, 0.1, 0.1) == pytest.approx(3 / 5)      # 0.0, 0.05, 0.15
    assert metrics.escalated_fraction([], 0.1, 0.1) == 0.0
    assert metrics.escalated_fraction([0.2], 0.1, 0.1) == 1.0                         # |0.2 - 0.1| <= 0.1 (inclusive edge)


def test_percentile_interpolates_and_handles_empty():
    assert metrics.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert metrics.percentile([10], 0.5) == 10
    assert math.isnan(metrics.percentile([], 0.5))


def test_usd_per_event_amortises_synthesis_and_adds_expected_escalation():
    v = metrics.usd_per_event([0.001, 0.003], synth_usd=0.4, n_events=200, esc_fraction=0.25, esc_usd=0.02)
    assert v == pytest.approx(0.002 + 0.002 + 0.005)
    assert metrics.usd_per_event([]) == 0.0


def test_mean_std():
    assert metrics.mean_std([1.0, 3.0]) == (2.0, 1.0)


def test_local_threshold_agrees_with_the_calibrate_module():
    calibrate = pytest.importorskip("exemplar.calibrate")
    if not hasattr(calibrate, "conformal_threshold"):
        pytest.skip("exemplar.calibrate.conformal_threshold not available")
    import random
    rng = random.Random(1)
    for n in (5, 9, 10, 30, 99):
        neg = [rng.uniform(-0.5, 0.5) for _ in range(n)]
        mine = metrics.conformal_threshold(neg, 0.1)
        theirs = calibrate.conformal_threshold(neg, 0.1)
        assert mine.guarantee == theirs.guarantee
        if mine.guarantee:
            assert mine.k == theirs.k and max(mine.tau, 0.0) == pytest.approx(theirs.tau)
