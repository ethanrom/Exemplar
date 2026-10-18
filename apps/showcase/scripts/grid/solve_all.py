"""Phase A of the Lab grid: every valid slot through the real engine, with a process pool.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/solve_all.py [--workers 8] [--raw PATH]

Results are appended slot by slot to a scratch JSONL (default $SHOWCASE_WORK_DIR/grid-raw.jsonl), so an
interrupted run resumes where it stopped.  `assemble.py` turns the raw file into `data/grid/*.json.gz`.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import slotsolve as S        # noqa: E402

DEFAULT_RAW = G.work_dir() / "grid-raw.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--limit", type=int, default=0, help="only the first N pending slots (smoke test)")
    a = ap.parse_args()

    done: set[int] = set()
    if a.raw.exists():
        with a.raw.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    done.add(json.loads(line)["slot"])
    todo = [s for s in G.VALID_SLOTS if s not in done]
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(done)} slots done, {len(todo)} to go, {a.workers} workers", flush=True)
    a.raw.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    n = 0
    with mp.Pool(a.workers, initializer=S.init) as pool, a.raw.open("a", encoding="utf-8") as out:
        for res in pool.imap_unordered(S.solve_slot, todo, chunksize=2):
            out.write(json.dumps(res, allow_nan=False, separators=(",", ":")) + "\n")
            n += 1
            if n % 100 == 0:
                out.flush()
                el = time.perf_counter() - t0
                print(f"{n}/{len(todo)} slots, {el:.0f} s, eta {el / n * (len(todo) - n):.0f} s", flush=True)
    print(f"finished {n} slots in {time.perf_counter() - t0:.0f} s", flush=True)


if __name__ == "__main__":
    main()
