"""Statistical validity of the conformal threshold: P(false alarm) <= alpha for exchangeable negatives,
including heavy ties at the -C = -0.5 plateau (PLAN.md §2.5).

Two independent checks:

1. exact: enumerate every calibration outcome of a small discrete distribution (ties everywhere) and sum
   the exact false-alarm probability; it must be <= alpha with no tolerance;
2. Monte Carlo (seeded): many calibration/test draws; the number of false alarms must not exceed the
   Binomial(M, alpha) upper quantile at 1e-6, i.e. a fail means the bound is violated, not bad luck.
   A mutated quantile (k - 2) must fail the same check, which shows the test has power.
"""
from __future__ import annotations

import itertools

import numpy as np
import pytest
from scipy.special import bdtr, bdtrc

from exemplar.calibrate import conformal_rank, conformal_threshold

M = 100_000
SUPPORT = np.array([-0.5, -0.45, 0.1, 0.3])
PROBS = np.array([0.55, 0.25, 0.10, 0.10])


# ------------------------------------------------------------------------------------------ distributions
def d_continuous(rng, shape):
    return rng.uniform(-0.45, 0.45, shape)


def d_plateau(rng, shape):               # 70% exactly -0.5 (no binding), the rest continuous
    return np.where(rng.random(shape) < 0.7, -0.5, rng.uniform(-0.45, 0.45, shape))


def d_atoms(rng, shape):                 # what ST robustness on confidence levels really looks like
    return rng.choice([-0.5, -0.45, 0.3], size=shape, p=[0.6, 0.3, 0.1])


def d_top_ties(rng, shape):              # heavy ties near the top, so tau_alpha often equals an atom
    return rng.choice([-0.5, -0.1, 0.3, 0.45], size=shape, p=[0.1, 0.2, 0.5, 0.2])


DISTS = {"continuous": d_continuous, "plateau70": d_plateau, "atoms": d_atoms, "top_ties": d_top_ties}


def false_alarm_counts(dist, n, alpha, seed, k=None):
    rng = np.random.default_rng(seed)
    k = conformal_rank(n, alpha) if k is None else k
    calib = dist(rng, (M, n))
    test = dist(rng, (M,))
    tau_alpha = np.sort(calib, axis=1)[:, k - 1]
    return int((test > tau_alpha).sum()), int((test > np.maximum(tau_alpha, 0.0)).sum())


def binom_upper(m, p, tail=1e-6):
    """Smallest c with P(Binomial(m, p) > c) <= tail."""
    cs = np.arange(0, m + 1)
    return int(cs[np.argmax(bdtrc(cs, m, p) <= tail)])


def binom_lower(m, p, tail=1e-6):
    """Largest c with P(Binomial(m, p) < c) <= tail."""
    cs = np.arange(0, m + 1)
    return int(cs[np.argmax(bdtr(cs, m, p) > tail)])


def upper_bound(alpha):
    return binom_upper(M, alpha)


# ------------------------------------------------------------------------------------------ Monte Carlo
@pytest.mark.parametrize("name", list(DISTS))
@pytest.mark.parametrize("n,alpha", [(9, 0.1), (19, 0.1), (49, 0.1), (9, 0.2), (19, 0.2), (49, 0.2)])
def test_false_alarm_rate_is_at_most_alpha(name, n, alpha):
    assert conformal_rank(n, alpha) <= n
    raw, floored = false_alarm_counts(DISTS[name], n, alpha, seed=1000 * n + int(alpha * 100) + len(name))
    print(f"\n[validity] {name:10s} n={n:3d} alpha={alpha:.2f}  FA(raw tau_alpha)={raw / M:.4f}  "
          f"FA(floored tau)={floored / M:.4f}  bound<={upper_bound(alpha) / M:.4f}")
    assert raw <= upper_bound(alpha)
    assert floored <= raw


@pytest.mark.parametrize("n,alpha", [(9, 0.1), (19, 0.1), (49, 0.2)])
def test_without_ties_the_bound_is_tight(n, alpha):
    """Continuous scores: the exact false-alarm probability is 1 - k/(n+1); the test would notice a conservative
    or a broken threshold, so the simulation above is not vacuous."""
    k = conformal_rank(n, alpha)
    raw, _ = false_alarm_counts(d_continuous, n, alpha, seed=7 + n)
    p = 1 - k / (n + 1)
    lo, hi = binom_lower(M, p), binom_upper(M, p)
    assert lo <= raw <= hi
    assert p <= alpha and alpha - p < 1 / (n + 1)


@pytest.mark.parametrize("n,alpha", [(19, 0.1), (49, 0.1)])
def test_the_check_has_power_a_too_small_rank_violates_it(n, alpha):
    k = conformal_rank(n, alpha)
    raw, _ = false_alarm_counts(d_continuous, n, alpha, seed=11, k=k - 2)
    assert raw > upper_bound(alpha)


def test_real_function_agrees_with_the_vectorised_formula_on_tied_draws():
    rng = np.random.default_rng(5)
    n, alpha = 19, 0.1
    k = conformal_rank(n, alpha)
    fa = 0
    draws = 2000
    for _ in range(draws):
        calib = d_plateau(rng, (n,))
        test = float(d_plateau(rng, ()))
        cal = conformal_threshold(calib.tolist(), alpha)
        assert cal.tau_alpha == np.sort(calib)[k - 1] and cal.guarantee
        fa += test > cal.tau
    assert fa <= binom_upper(draws, alpha)


# ------------------------------------------------------------------------------------------ exact enumeration
@pytest.mark.parametrize("n,alpha", [(4, 0.2), (5, 0.2), (6, 0.3), (6, 0.25), (3, 0.4)])
def test_exact_false_alarm_probability_with_ties_is_at_most_alpha(n, alpha):
    assert conformal_rank(n, alpha) <= n
    exact_raw = exact_floored = 0.0
    tail = {v: float(PROBS[SUPPORT > v].sum()) for v in SUPPORT}
    for idx in itertools.product(range(len(SUPPORT)), repeat=n):
        p = float(np.prod(PROBS[list(idx)]))
        cal = conformal_threshold([float(SUPPORT[i]) for i in idx], alpha)
        exact_raw += p * tail[cal.tau_alpha]
        exact_floored += p * float(PROBS[SUPPORT > cal.tau].sum())
    print(f"\n[exact]    n={n} alpha={alpha}: P(false alarm) raw={exact_raw:.5f} floored={exact_floored:.5f}")
    assert exact_raw <= alpha + 1e-12
    assert exact_floored <= exact_raw + 1e-12


def test_exact_false_alarm_probability_without_guarantee_is_not_claimed():
    # n = 3, alpha = 0.1: k = 4 > n. The function must not pretend: tau = 0, guarantee False.
    cal = conformal_threshold([-0.5, -0.5, -0.5], 0.1)
    assert not cal.guarantee and cal.tau == 0.0 and cal.k is None
