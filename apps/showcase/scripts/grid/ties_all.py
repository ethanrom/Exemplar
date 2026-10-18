"""Phase B of the Lab grid: tie annotation (`alternatives`) for every sketch x valid slot, written to a scratch JSON.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/ties_all.py [--workers 3] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G      # noqa: E402
import ties as T         # noqa: E402

DEFAULT_OUT = G.work_dir() / "grid-ties.json"


def one(sid: int):
    t = time.perf_counter()
    r = T.ties_for_sketch(sid)
    return sid, r, time.perf_counter() - t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()
    n = len(G.sketch_bank())
    res: dict[int, dict[int, tuple[int, int]]] = {}
    t0 = time.perf_counter()
    order = [4, 18, 34, 16, 17] + [i for i in range(n) if i not in (4, 18, 34, 16, 17)]   # heavy ones first
    with mp.Pool(a.workers) as pool:
        for sid, r, dt in pool.imap_unordered(one, order):
            res[sid] = r
            print(f"sketch {sid}: {len(r)} slots, {dt:.0f} s ({time.perf_counter() - t0:.0f} s total)", flush=True)
    out = {"sketches": {str(s): {str(k): list(v) for k, v in sorted(r.items())} for s, r in sorted(res.items())}}
    a.out.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
