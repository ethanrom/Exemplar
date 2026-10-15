"""How much do the cached traces say about each concept?  A quick feasibility check before (and next to) the Exemplar run.

    uv run --project engine python -m eval.trace_probe [--splits train calib test]

For every concept this prints, per cheap trace feature (entity counts, `enters`/`leaves`/`near`/carrying facts, door-zone facts, ...), the
ROC AUC of "feature value" as a score for pos vs neg windows (0.5 = no information).  No model call, no rule synthesis: it reads
the perception cache only.  If every feature sits near 0.5 for a concept, no rule over the ontology-v1 facts can do much better and
Exemplar will lose to a pixel-level baseline there; that is a perception / ontology finding, not a synthesis bug.
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable, Optional, Sequence

from exemplar.contracts.trace import Trace

from eval.harness.dataset import concept_ids, load_windows
from eval.harness.traces import load_cached


def _count(pred: Sequence[str]) -> Callable[[Trace], float]:
    return lambda t: float(sum(f.pred in pred for fr in t.frames for f in fr.facts))


FEATURES: dict[str, Callable[[Trace], float]] = {
    "n_enters_leaves": _count(("enters", "leaves")),
    "n_near": _count(("near",)),
    "n_carry_pick_put": _count(("carrying", "picks_up", "puts_down")),
    "n_door_zone": lambda t: float(sum(f.pred == "in_zone" and f.args[1] == "door" for fr in t.frames for f in fr.facts)),
    "n_facts": lambda t: float(sum(len(fr.facts) for fr in t.frames)),
    "n_entities": lambda t: float(len(t.entities)),
    "n_person": lambda t: float(sum(e.type == "person" for e in t.entities)),
    "n_vehicle": lambda t: float(sum(e.type == "vehicle" for e in t.entities)),
}


def auc(pos: Sequence[float], neg: Sequence[float]) -> float:
    """P(score of a random positive > score of a random negative), ties counting half."""
    if not pos or not neg:
        return float("nan")
    return sum((a > b) + 0.5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg))


def probe(concept: str, splits: Sequence[str]) -> tuple[int, dict[str, float]]:
    pairs = [(w.positive, load_cached(w)) for w in load_windows(concepts=[concept], splits=splits)]
    ok = [(p, t) for p, t in pairs if t is not None and t.status == "ok"]
    out = {name: auc([f(t) for p, t in ok if p], [f(t) for p, t in ok if not p]) for name, f in FEATURES.items()}
    return len(ok), out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.trace_probe", description=__doc__.split("\n\n")[0])
    ap.add_argument("--splits", nargs="*", default=["calib", "test"], choices=["train", "calib", "test"])
    a = ap.parse_args(argv)
    names = list(FEATURES)
    print(f"{'concept':<22} {'n':>4} " + " ".join(f"{n[2:]:>15}" for n in names))
    for cid in concept_ids():
        n, aucs = probe(cid, a.splits)
        print(f"{cid:<22} {n:>4} " + " ".join(f"{aucs[k]:>15.2f}" for k in names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
