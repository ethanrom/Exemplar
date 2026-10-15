"""`python -m eval.plots [--results FILE] [--out DIR] [--k K --q Q]`: charts + table from results.json."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from eval.harness.dataset import eval_dir
from eval.harness.results import load_results

from .charts import write_all


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.plots", description=__doc__)
    ap.add_argument("--results", type=Path, default=None, help="default $EXEMPLAR_DATA_DIR/eval/results.json")
    ap.add_argument("--out", type=Path, default=None, help="default $EXEMPLAR_DATA_DIR/eval/plots")
    ap.add_argument("--k", type=int, default=None, help="Exemplar k for the single-config charts (default: largest present)")
    ap.add_argument("--q", type=int, default=None, help="Exemplar q for the single-config charts (default: largest present)")
    a = ap.parse_args(argv)
    doc = load_results(a.results)
    rows = doc.get("rows", [])
    if not rows:
        print("no rows in results.json: run eval.baselines.zero_shot / eval.run first", file=sys.stderr)
        return 2
    paths = write_all(rows, a.out or eval_dir() / "plots", alpha=doc.get("alpha") or 0.1, k=a.k, q=a.q)
    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
