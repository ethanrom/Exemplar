"""Cut every manifest window into a small H.264 clip: ROI crop -> 1280 px wide -> no audio.

Output: `$EXEMPLAR_DATA_DIR/meva/clips/<concept>/<id>.mp4` (the manifest's `clip` field).  Idempotent (existing non-empty
clips are skipped) and parallel-safe (each worker writes a unique temp file, then renames atomically).

    uv run --project engine python -m eval.data.cut [--workers 4] [--concept vehicle_stop] [--limit N]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import imageio_ffmpeg

from . import paths
from .config import read_manifest

OUT_WIDTH = 1280
CRF = 26


def ffmpeg_cut_args(src: Path, dst: Path, start_ms: int, dur_ms: int, crop: tuple[int, int, int, int] | None, width: int = OUT_WIDTH,
                    crf: int = CRF) -> list[str]:
    vf = ([f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}"] if crop else []) + [f"scale={width}:-2:flags=lanczos"]
    return [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-ss", f"{start_ms / 1000:.3f}", "-i", str(src), "-t", f"{dur_ms / 1000:.3f}",
            "-vf", ",".join(vf), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-y", str(dst)]


def cut_clip(src: Path, dst: Path, start_ms: int, dur_ms: int, crop: tuple[int, int, int, int] | None = None, width: int = OUT_WIDTH) -> str:
    """Returns 'skipped' or 'cut'. Raises on ffmpeg failure."""
    if dst.is_file() and dst.stat().st_size > 0:
        return "skipped"
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.stem}.tmp{os.getpid()}_{time.monotonic_ns()}.mp4")
    try:
        subprocess.run(ffmpeg_cut_args(src, tmp, start_ms, dur_ms, crop, width), check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        os.replace(tmp, dst)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed for {dst.name}: {e.stderr[-400:]}") from e
    finally:
        if tmp.exists():
            tmp.unlink()
    return "cut"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--concept", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    rows = [r for r in read_manifest() if not args.concept or r["concept"] == args.concept]
    if args.limit:
        rows = rows[: args.limit]
    data = paths.data_dir()
    missing = sorted({r["video"] for r in rows if not (paths.videos_dir() / f"{r['video']}.r13.avi").is_file()})
    if missing:
        print(f"missing source videos (run eval.data.download): {missing}", file=sys.stderr)
        return 2
    t0 = time.time()
    done = failed = cut = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(cut_clip, paths.videos_dir() / f"{r['video']}.r13.avi", data / r["clip"], r["start_ms"], r["dur_ms"], tuple(r["roi"])): r
                for r in rows}
        for f in as_completed(futs):
            try:
                cut += f.result() == "cut"
            except Exception as e:
                failed += 1
                print(f"FAILED {futs[f]['id']}: {e}", file=sys.stderr)
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(rows)} [{time.time() - t0:.0f}s]", flush=True)
    size = sum((data / r["clip"]).stat().st_size for r in rows if (data / r["clip"]).is_file())
    print(f"{len(rows)} windows: {cut} cut, {len(rows) - cut - failed} already present, {failed} failed; {size / 1e6:.0f} MB in {time.time() - t0:.0f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
