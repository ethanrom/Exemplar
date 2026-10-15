"""Metric arithmetic for the MEVA evaluation.

Everything here is a pure function of scores and labels, so it is unit-tested without any model or data.

* `conformal_threshold`: tau_alpha is the k-th smallest negative score, k = ceil((n+1)(1-alpha)); fire iff score > tau.
  With fewer than ceil(1/alpha)-1 negatives (k > n) there is no guarantee and the rule fires on score > `fallback`.
* `confusion` / `prf`: precision, recall, F1 and the false-alarm rate at a threshold.
* `clopper_pearson`: exact binomial interval (validity plot, recall CI).
* `usd_per_event`: perception + amortised synthesis (+ expected escalation).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class Threshold:
    tau: float
    guarantee: bool
    k: Optional[int]
    n: int


def conformal_k(n: int, alpha: float) -> int:
    return math.ceil((n + 1) * (1.0 - alpha) - 1e-12)


def conformal_threshold(neg_scores: Sequence[float], alpha: float, *, fallback: float = 0.0) -> Threshold:
    """k-th smallest negative score (1-based).  Too few negatives: tau = `fallback`, guarantee False."""
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    n = len(neg_scores)
    k = conformal_k(n, alpha)
    if n == 0 or k > n:
        return Threshold(tau=fallback, guarantee=False, k=None, n=n)
    return Threshold(tau=sorted(neg_scores)[k - 1], guarantee=True, k=k, n=n)


def fires(score: float, tau: float) -> bool:
    return score > tau


@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n_pos(self) -> int:
        return self.tp + self.fn

    @property
    def n_neg(self) -> int:
        return self.fp + self.tn


def confusion(scores: Sequence[float], positives: Sequence[bool], tau: float) -> Confusion:
    if len(scores) != len(positives):
        raise ValueError("scores and labels differ in length")
    tp = fp = fn = tn = 0
    for s, y in zip(scores, positives):
        f = fires(s, tau)
        if y:
            tp, fn = tp + f, fn + (not f)
        else:
            fp, tn = fp + f, tn + (not f)
    return Confusion(tp, fp, fn, tn)


def prf(c: Confusion) -> dict[str, float]:
    """precision (0 when nothing fires), recall (0 without positives), F1 and false-alarm rate (0 without negatives)."""
    p = c.tp / (c.tp + c.fp) if c.tp + c.fp else 0.0
    r = c.tp / c.n_pos if c.n_pos else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    far = c.fp / c.n_neg if c.n_neg else 0.0
    return {"precision": p, "recall": r, "f1": f1, "false_alarm_rate": far}


def clopper_pearson(x: int, n: int, level: float = 0.95) -> tuple[float, float]:
    """Exact two-sided binomial confidence interval for x successes in n trials."""
    if n <= 0:
        return (0.0, 1.0)
    from scipy.stats import beta
    a = (1.0 - level) / 2.0
    lo = 0.0 if x == 0 else float(beta.ppf(a, x, n - x + 1))
    hi = 1.0 if x == n else float(beta.ppf(1.0 - a, x + 1, n - x))
    return (lo, hi)


def escalated_fraction(scores: Sequence[float], tau: float, delta: float) -> float:
    """Share of events whose score lies inside the escalation band |score - tau| <= delta."""
    if not scores:
        return 0.0
    return sum(abs(s - tau) <= delta + 1e-12 for s in scores) / len(scores)


def percentile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0, 1]); NaN on empty input."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def usd_per_event(perception_usd: Sequence[float], *, synth_usd: float = 0.0, n_events: Optional[int] = None,
                  esc_fraction: float = 0.0, esc_usd: float = 0.0) -> float:
    """Mean perception cost per event + synthesis amortised over `n_events` + expected escalation cost."""
    n = n_events if n_events is not None else len(perception_usd)
    mean_p = sum(perception_usd) / len(perception_usd) if perception_usd else 0.0
    return mean_p + (synth_usd / n if n else 0.0) + esc_fraction * esc_usd


def mean_std(xs: Sequence[float]) -> tuple[float, float]:
    if not xs:
        return (float("nan"), float("nan"))
    m = sum(xs) / len(xs)
    var = sum((x - m) ** 2 for x in xs) / len(xs)
    return (m, math.sqrt(var))
