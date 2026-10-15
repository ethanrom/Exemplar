"""Fetch the selected MEVA videos (`eval/data/videos.yaml`) from the public S3 bucket.

Resumable (`.part` files + ranged GETs), skips videos already present with the right size, verifies the size.

    uv run --project engine python -m eval.data.download [--workers 3] [--only STEM_SUBSTRING]
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import paths, s3
from .config import load_yaml


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", default="", help="download only stems containing this substring")
    args = ap.parse_args(argv)

    vids = [v for v in load_yaml("videos.yaml")["videos"] if args.only in v["stem"]]
    out_dir = paths.videos_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    need = sum(v["size_bytes"] for v in vids if not (out_dir / f"{v['stem']}.r13.avi").is_file())
    print(f"{len(vids)} videos, ~{need / 1e9:.2f} GB still to fetch into {out_dir}", flush=True)

    t0 = time.time()
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(s3.download, v["s3_key"], out_dir / f"{v['stem']}.r13.avi", v["size_bytes"]): v for v in vids}
        for f in as_completed(futs):
            v = futs[f]
            try:
                print(f"  {f.result():10s} {v['stem']} ({v['size_bytes'] / 1e6:.0f} MB) [{time.time() - t0:.0f}s]", flush=True)
            except Exception as e:  # keep going; rerun resumes
                failed += 1
                print(f"  FAILED     {v['stem']}: {e}", flush=True)
    print(f"done in {time.time() - t0:.0f}s, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
