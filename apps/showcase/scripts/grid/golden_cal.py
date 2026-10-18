"""F10 `cal` goldens from the real engine: conformal rank, Clopper-Pearson, thresholds and calibrations.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/golden_cal.py

Real closed-rule x package-random-set calibrations are added by `golden_real.py` once the grid is assembled.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import golden_io as IO       # noqa: E402

from exemplar.calibrate.conformal import conformal_rank, conformal_threshold, min_negatives, recall_ci   # noqa: E402

SEED = 20261018


def api(cal) -> dict:
    d = cal.to_api()
    d["tau_alpha"] = None if cal.tau_alpha is None else float(cal.tau_alpha)
    return d


def records() -> list[dict]:
    rng = random.Random(SEED)
    out: list[dict] = []
    alphas = [round(i / 100, 2) for i in range(1, 51)]
    # (a) k = ceil((n + 1)(1 - alpha)) and the minimum number of negatives, alpha 0.01..0.50 x n 0..300
    for a in alphas:
        out.append({"id": f"rank/{a}", "kind": "rank", "input": {"alpha": a, "n_max": 300},
                    "expect": {"k": [conformal_rank(n, a) for n in range(301)], "min_negatives": min_negatives(a)}})
    # extra alphas that are not multiples of 0.01 (decimal-exactness), including exponent notation
    for a in (0.001, 0.005, 0.025, 0.075, 0.123, 0.333, 0.999, 0.9, 1e-05, 0.00015, 0.2, 0.3, 0.7):
        out.append({"id": f"rank/{a}", "kind": "rank", "input": {"alpha": a, "n_max": 120},
                    "expect": {"k": [conformal_rank(n, a) for n in range(121)], "min_negatives": min_negatives(a)}})
    # (b) Clopper-Pearson for every (x, n), n <= 50
    for n in range(0, 51):
        for x in range(0, n + 1):
            if n == 0:
                continue
            rec, ci = recall_ci([1.0] * x + [-1.0] * (n - x), 0.0)
            out.append({"id": f"cp/{x}/{n}", "kind": "cp", "input": {"x": x, "n": n},
                        "expect": {"recall": rec, "ci": [ci[0], ci[1]]}})
    for n in (60, 75, 100, 150, 200, 300):
        for x in sorted({0, 1, 2, n // 10, n // 4, n // 2, n - n // 4, n - 2, n - 1, n}):
            rec, ci = recall_ci([1.0] * x + [-1.0] * (n - x), 0.0)
            out.append({"id": f"cp/{x}/{n}", "kind": "cp", "input": {"x": x, "n": n},
                        "expect": {"recall": rec, "ci": [ci[0], ci[1]]}})
    # (c) thresholds / calibrations on random score sets, with ties and the -0.5 plateau
    levels = [-0.5, -0.45, -0.3, -0.1, 0.1, 0.3, 0.45, 0.5]
    for i in range(2500):
        n_neg = rng.choice([0, 1, 2, 3, 5, 7, 8, 9, 10, 15, 19, 20, 31, 50, 99, 150, 300])
        n_pos = rng.choice([0, 0, 1, 3, 7, 12, 20, 40])
        mode = rng.random()
        if mode < 0.4:
            neg = [rng.choice(levels) for _ in range(n_neg)]
        elif mode < 0.7:
            neg = [-0.5 if rng.random() < 0.8 else rng.choice(levels) for _ in range(n_neg)]
        else:
            neg = [round(rng.uniform(-0.5, 0.5), rng.choice([2, 3, 6])) for _ in range(n_neg)]
        pos = [rng.choice(levels) if rng.random() < 0.7 else round(rng.uniform(-0.5, 0.5), 3) for _ in range(n_pos)]
        alpha = rng.choice(alphas)
        cal = conformal_threshold(neg, alpha)
        rec, ci = recall_ci(pos, cal.tau)
        import dataclasses
        cal = dataclasses.replace(cal, n_random_pos=len(pos), recall=rec, recall_ci95=ci)
        out.append({"id": f"cal/{i}", "kind": "cal", "input": {"alpha": alpha, "neg": neg, "pos": pos}, "expect": api(cal)})
    return out


def main() -> None:
    recs = records()
    p = IO.write_family("cal", "golden_cal.py: exemplar.calibrate.conformal", SEED, recs)
    print(p, len(recs), p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
