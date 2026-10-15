"""Conformal threshold arithmetic, ties, the k > n message, delta and the Clopper-Pearson recall CI."""
from __future__ import annotations

import math

import pytest
import yaml
from jsonschema import Draft202012Validator
from pathlib import Path
from scipy.special import bdtr, bdtrc

from exemplar.calibrate import (Calibration, conformal_rank, conformal_threshold, escalation_delta, min_negatives,
                                recall_ci)

API = Path(__file__).parents[2] / "exemplar" / "contracts" / "api.yaml"


def calibration_validator() -> Draft202012Validator:
    spec = yaml.safe_load(API.read_text(encoding="utf-8"))
    return Draft202012Validator(spec["components"]["schemas"]["Calibration"])


# ------------------------------------------------------------------------------------------ rank / threshold
@pytest.mark.parametrize("n,alpha,k", [
    (9, 0.1, 9), (10, 0.1, 10), (19, 0.1, 18), (29, 0.1, 27), (99, 0.1, 90),
    (19, 0.05, 19), (4, 0.2, 4), (7, 0.25, 6), (0, 0.5, 1), (1, 0.5, 1), (2, 0.5, 2),
])
def test_conformal_rank_matches_the_formula(n, alpha, k):
    assert conformal_rank(n, alpha) == k == math.ceil((n + 1) * (1 - alpha) - 1e-9)


def test_conformal_rank_is_exact_where_float_arithmetic_is_not():
    # 150 * (1 - 0.18) is 123.00000000000001 in floating point, so a naive ceil() would give 124.
    assert math.ceil(150 * (1 - 0.18)) == 124
    assert conformal_rank(149, 0.18) == 123


@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.1, 0.15, 0.18, 0.2, 0.25, 0.3, 0.5])
def test_guarantee_available_exactly_when_n_reaches_ceil_one_over_alpha_minus_one(alpha):
    need = min_negatives(alpha)
    assert need == math.ceil(1 / alpha - 1e-9) - 1
    for n in range(0, min(need + 5, 400)):
        k = conformal_rank(n, alpha)
        cal = conformal_threshold([0.1] * n, alpha)
        assert (k <= n) == (n >= need) == cal.guarantee
        assert cal.k == (k if k <= n else None)


def test_tau_is_the_kth_smallest_score():
    scores = [0.30, -0.45, 0.45, -0.5, 0.1, -0.45, 0.3, 0.45, -0.1]       # n = 9 -> k = 9 for alpha 0.1
    cal = conformal_threshold(scores, 0.1)
    assert (cal.n_random_neg, cal.k, cal.guarantee, cal.message) == (9, 9, True, None)
    assert cal.tau_alpha == 0.45 and cal.tau == 0.45
    # n = 20: k = ceil(21 * 0.9) = 19, the 2nd largest
    s20 = [i / 100 for i in range(20)]
    cal = conformal_threshold(s20, 0.1)
    assert cal.k == 19 and cal.tau_alpha == s20[18]
    assert conformal_threshold(list(reversed(s20)), 0.1).tau_alpha == s20[18]       # order does not matter


def test_too_few_negatives_has_no_guarantee_and_an_exact_message():
    cal = conformal_threshold([-0.45] * 8, 0.1)
    assert cal.guarantee is False and cal.k is None and cal.tau == 0.0 and cal.tau_alpha is None
    assert cal.message == "guarantee needs ≥ 9 random negatives (have 8)"
    assert conformal_threshold([], 0.1).message == "guarantee needs ≥ 9 random negatives (have 0)"
    assert conformal_threshold([0.2] * 18, 0.05).message == "guarantee needs ≥ 19 random negatives (have 18)"
    assert conformal_threshold([0.2] * 2, 0.3).message == "guarantee needs ≥ 3 random negatives (have 2)"    # 1/0.3 = 3.33
    assert conformal_threshold([0.2] * 9, 0.1).guarantee is True


def test_no_guarantee_still_fires_on_score_above_zero():
    cal = conformal_threshold([0.4, 0.4], 0.1)             # scores above 0, but too few: tau stays 0, not 0.4
    assert cal.tau == 0.0 and not cal.guarantee


# ------------------------------------------------------------------------------------------ ties and the plateau
def test_plateau_ties_threshold_is_the_plateau_and_floored_at_zero():
    cal = conformal_threshold([-0.5] * 12, 0.1)
    assert cal.guarantee and cal.k == 12                                 # k = ceil(13 * 0.9) = 12
    assert cal.tau_alpha == -0.5
    assert cal.tau == 0.0                       # never fire on a clip the rule does not hold on
    # a clip on the plateau is not above tau; a matching clip is
    assert not (-0.5 > cal.tau) and (0.3 > cal.tau)


def test_ties_at_the_kth_value_use_a_strict_comparison():
    # n = 10, alpha 0.1 -> k = 10: tau_alpha = max = 0.3, which is also the value of two other negatives.
    scores = [-0.5] * 5 + [0.1, 0.3, 0.3, 0.3, 0.3]
    cal = conformal_threshold(scores, 0.1)
    assert cal.k == 10 and cal.tau == 0.3
    assert not (0.3 > cal.tau)                  # a test negative tied with tau does not fire
    assert 0.31 > cal.tau


def test_tau_alpha_below_zero_is_floored_but_kept():
    cal = conformal_threshold([-0.45] * 5 + [-0.5] * 5, 0.1)
    assert cal.tau_alpha == -0.45 and cal.tau == 0.0


def test_rejects_bad_input():
    with pytest.raises(ValueError):
        conformal_threshold([0.0, float("nan")], 0.1)
    for a in (0.0, 1.0, -0.1, 1.5, float("nan")):
        with pytest.raises(ValueError):
            conformal_threshold([0.0] * 20, a)


# ------------------------------------------------------------------------------------------ delta
def test_delta_defaults_when_n_is_small_and_clamps_otherwise():
    assert escalation_delta([]) == 0.1 and escalation_delta([-0.5] * 7) == 0.1
    assert escalation_delta([-0.5] * 8) == 0.05                     # all tied: IQR 0 -> lower clamp
    wide = [-0.5] * 5 + [0.45] * 5
    assert escalation_delta(wide) == 0.2                            # IQR 0.95 -> upper clamp
    mid = [i * 0.03 for i in range(-5, 5)]                          # IQR about 0.135 -> 0.07
    assert escalation_delta(mid) == pytest.approx(0.068, abs=0.002)
    assert conformal_threshold([-0.5] * 12, 0.1).delta == 0.05
    assert conformal_threshold([-0.5] * 3, 0.1).delta == 0.1


# ------------------------------------------------------------------------------------------ recall CI
def test_recall_ci_none_without_positives():
    assert recall_ci([], 0.0) == (None, None)


def test_recall_ci_known_values():
    r, (lo, hi) = recall_ci([0.45] * 10, 0.0)
    assert r == 1.0 and hi == 1.0 and lo == pytest.approx(0.025 ** 0.1, abs=1e-9)           # 0.6915
    r, (lo, hi) = recall_ci([-0.45] * 10, 0.0)
    assert r == 0.0 and lo == 0.0 and hi == pytest.approx(1 - 0.025 ** 0.1, abs=1e-9)       # 0.3085
    r, (lo, hi) = recall_ci([0.45] * 5 + [-0.45] * 5, 0.0)
    assert r == 0.5 and (lo, hi) == (pytest.approx(0.1871, abs=5e-4), pytest.approx(0.8129, abs=5e-4))


@pytest.mark.parametrize("n", [1, 2, 7, 20, 60])
def test_recall_ci_is_the_exact_binomial_inversion(n):
    for x in range(0, n + 1):
        scores = [0.3] * x + [-0.3] * (n - x)
        r, (lo, hi) = recall_ci(scores, 0.0)
        assert r == x / n and 0.0 <= lo <= x / n <= hi <= 1.0
        if x > 0:    # P(X >= x | p = lo) = 0.025
            assert bdtrc(x - 1, n, lo) == pytest.approx(0.025, abs=1e-9)
        if x < n:    # P(X <= x | p = hi) = 0.025
            assert bdtr(x, n, hi) == pytest.approx(0.025, abs=1e-9)


def test_recall_ci_uses_a_strict_comparison_against_tau():
    r, _ = recall_ci([0.1, 0.1, 0.3], 0.1)
    assert r == pytest.approx(1 / 3)
    assert recall_ci([0.1], 0.1)[0] == 0.0


def test_recall_ci_level():
    _, (lo95, hi95) = recall_ci([0.3] * 6 + [-0.3] * 4, 0.0)
    _, (lo80, hi80) = recall_ci([0.3] * 6 + [-0.3] * 4, 0.0, level=0.8)
    assert lo80 > lo95 and hi80 < hi95
    with pytest.raises(ValueError):
        recall_ci([0.3], 0.0, level=1.0)


# ------------------------------------------------------------------------------------------ API shape
def test_calibration_to_api_validates_against_the_schema():
    v = calibration_validator()
    for cal in (conformal_threshold([-0.5] * 3, 0.1), conformal_threshold([-0.45] * 12, 0.1),
                Calibration(alpha=0.1, n_random_neg=12, n_random_pos=3, k=11, tau=0.0, guarantee=True, delta=0.07,
                            recall=2 / 3, recall_ci95=(0.094, 0.992))):
        d = cal.to_api()
        v.validate(d)
        assert "tau_alpha" not in d
    d = Calibration(alpha=0.1, n_random_neg=12, recall_ci95=(0.1, 0.9)).to_api()
    assert d["recall_ci95"] == [0.1, 0.9] and d["k"] is None and d["message"] is None
