"""Split-conformal false-alarm calibration and the recall confidence interval (PLAN.md §2.5).

Setting. A rule scores a clip with its STL robustness (`exemplar.dsl.robustness`, in [-C, C], C = 0.5) and
fires when ``score > tau``. Take the scores of ``n`` negatives that were sampled uniformly from history
and never used to fit the rule (provenance ``random``). With

    k = ceil((n + 1) * (1 - alpha))        tau_alpha = the k-th smallest of the n negative scores

a fresh negative from the same distribution (exchangeable with the calibration negatives) satisfies

    P(score > tau_alpha) <= alpha .

Proof sketch: the test score is exchangeable with the n calibration scores, so its rank among all n + 1
(ties broken at random) is uniform on 1..n+1, and ``P(test <= k-th smallest of the calibration scores)
>= k / (n + 1) >= 1 - alpha``. The bound holds with ties because the decision is the *strict* ``>``:
every tied score is "not above" tau, so ties can only lower the false-alarm rate, never raise it. Scores
plateau at exactly -C (no admissible binding, false context), so ties are the normal case, not a corner.

If ``k > n`` there are too few negatives for any threshold to carry the bound; that happens exactly when
``n < ceil(1/alpha) - 1``. Then tau is 0 (fire on ``score > 0``, i.e. whenever the rule holds), the
guarantee flag is off and the message says how many negatives are missing.

Decisions that go beyond the textbook recipe (documented because they are visible in the UI):

* **tau is floored at 0.** Firing at a score <= 0 would alert on clips where the rule does *not* hold
  (when most calibration negatives sit on the -0.5 plateau, tau_alpha = -0.5 would fire on every clip with
  an admissible binding). A larger threshold only lowers the false-alarm rate, so the bound stays valid.
  The raw quantile is kept in ``Calibration.tau_alpha`` for transparency.
* **delta (escalation half-width)** is a heuristic, not part of the guarantee: ``clamp(IQR / 2, 0.05, 0.2)``
  of the negative scores, and 0.1 when fewer than ``DELTA_MIN_N`` negatives are available. The IQR of a
  heavily tied sample is 0, which gives the lower clamp.
* The guarantee is about the decision "fast score > tau". Events re-scored by the strong model near the
  threshold (stage 2) are decided on a different scorer, so the bound is not proved for those; they are
  expected to be *less* error-prone, but that is empirical, not covered by the proof.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Sequence

import numpy as np
from scipy.special import betaincinv      # Beta quantile; lighter to import than scipy.stats

DEFAULT_DELTA = 0.1
DELTA_MIN, DELTA_MAX = 0.05, 0.2
DELTA_MIN_N = 8          # fewer negatives than this: the spread is meaningless, use DEFAULT_DELTA


@dataclass(frozen=True)
class Calibration:
    """api.yaml `Calibration` (+ `tau_alpha`, which is not part of the API payload)."""

    alpha: float
    n_random_neg: int
    n_random_pos: int = 0
    k: Optional[int] = None                    # ceil((n+1)(1-alpha)); None when k > n (no guarantee)
    tau: float = 0.0                           # the decision threshold: fire iff score > tau
    guarantee: bool = False
    message: Optional[str] = None
    delta: float = DEFAULT_DELTA               # escalation band half-width
    recall: Optional[float] = None
    recall_ci95: Optional[tuple[float, float]] = None
    tau_alpha: Optional[float] = None          # the raw conformal quantile (before the floor at 0)

    def to_api(self) -> dict:
        return {
            "alpha": float(self.alpha),
            "n_random_neg": int(self.n_random_neg),
            "n_random_pos": int(self.n_random_pos),
            "k": None if self.k is None else int(self.k),
            "tau": float(self.tau),
            "guarantee": bool(self.guarantee),
            "message": self.message,
            "delta": float(self.delta),
            "recall": None if self.recall is None else float(self.recall),
            "recall_ci95": None if self.recall_ci95 is None else [float(self.recall_ci95[0]), float(self.recall_ci95[1])],
        }


def _alpha(alpha: float) -> Fraction:
    """alpha as an exact rational (the decimal the caller wrote), so ceil() never trips on float noise."""
    a = float(alpha)
    if not (math.isfinite(a) and 0.0 < a < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    return Fraction(repr(a))


def conformal_rank(n: int, alpha: float) -> int:
    """k = ceil((n + 1) * (1 - alpha)), computed exactly."""
    if n < 0:
        raise ValueError("n must be >= 0")
    return math.ceil((n + 1) * (1 - _alpha(alpha)))


def min_negatives(alpha: float) -> int:
    """ceil(1/alpha) - 1: the fewest random negatives for which a threshold with the guarantee exists."""
    return math.ceil(1 / _alpha(alpha)) - 1


def escalation_delta(neg_scores: Sequence[float]) -> float:
    """Half-width of the stage-2 escalation band around tau (see the module docstring)."""
    if len(neg_scores) < DELTA_MIN_N:
        return DEFAULT_DELTA
    q1, q3 = np.percentile(np.asarray(neg_scores, dtype=np.float64), [25, 75])
    return round(float(min(max(0.5 * (q3 - q1), DELTA_MIN), DELTA_MAX)), 3)


def conformal_threshold(neg_scores: Sequence[float], alpha: float) -> Calibration:
    """tau_alpha from the scores of random negatives (PLAN §2.5). Fire iff ``score > tau``.

    Returns a `Calibration` with ``n_random_pos = 0`` and no recall; `calibrate` fills those in.
    """
    scores = sorted(float(s) for s in neg_scores)
    if any(not math.isfinite(s) for s in scores):
        raise ValueError("negative scores must be finite")
    n = len(scores)
    a = float(alpha)
    k = conformal_rank(n, alpha)
    delta = escalation_delta(scores)
    if k > n:
        need = min_negatives(alpha)
        return Calibration(alpha=a, n_random_neg=n, k=None, tau=0.0, guarantee=False, delta=delta, tau_alpha=None,
                           message=f"guarantee needs ≥ {need} random negatives (have {n})")
    tau_alpha = scores[k - 1]
    return Calibration(alpha=a, n_random_neg=n, k=k, tau=max(tau_alpha, 0.0), guarantee=True, delta=delta,
                       tau_alpha=tau_alpha, message=None)


def recall_ci(pos_scores: Sequence[float], tau: float, *, level: float = 0.95
              ) -> tuple[Optional[float], Optional[tuple[float, float]]]:
    """Recall of ``score > tau`` on random-labelled positives with a Clopper-Pearson interval.

    Returns ``(None, None)`` without positives. The interval is exact (beta quantiles), never below 0 or
    above 1, and degenerate-safe: 0 hits give lower bound 0, all hits give upper bound 1.
    """
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1), got {level!r}")
    n = len(pos_scores)
    if n == 0:
        return None, None
    x = sum(1 for s in pos_scores if float(s) > tau)
    a = 1.0 - level
    lo = 0.0 if x == 0 else float(betaincinv(x, n - x + 1, a / 2))
    hi = 1.0 if x == n else float(betaincinv(x + 1, n - x, 1 - a / 2))
    return x / n, (lo, hi)
