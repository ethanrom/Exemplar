"""Phase 0 spike (PLAN.md §5 Q7): read MEVA KPF activity annotations and cut a clip window around one.

Throwaway — stream G owns the real pipeline (`eval/data/`).

    uv run --project engine python scripts/spikes/meva_cut.py VIDEO.avi ANNOT.activities.yml [--activity person_unloads_vehicle] [--pad 3]
"""
from __future__ import annotations

import argparse
import random
import subprocess
from pathlib import Path

import imageio_ffmpeg
import yaml

FPS = 30  # MEVA drops-123-r13: 30 fps (AVI header)
ROOT = Path(__file__).resolve().parents[2]


def activities(annot: Path) -> list[dict]:
    out = []
    for item in yaml.safe_load(annot.read_text(encoding="utf-8")) or []:
        a = item.get("act")
        if not a:
            continue
        key = next(k for k, v in a.items() if k.startswith("act") and isinstance(v, dict))
        name = next(iter(a[key]))
        span = a["timespan"][0]["tsr0"]
        out.append({"name": name, "id": a.get("id2"), "f0": span[0], "f1": span[1]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("annot", type=Path)
    ap.add_argument("--activity", default="person_unloads_vehicle")
    ap.add_argument("--pad", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    acts = activities(a.annot)
    hits = [x for x in acts if x["name"] == a.activity]
    for x in hits:
        print(f"  {x['name']:32s} frames {x['f0']:5d}-{x['f1']:5d}  ({x['f0'] / FPS:6.1f}s, {(x['f1'] - x['f0']) / FPS:5.1f}s long)")
    if not hits:
        raise SystemExit(f"no {a.activity}")
    x = random.Random(a.seed).choice(hits)
    t0 = max(0.0, x["f0"] / FPS - a.pad)
    dur = min(20.0, (x["f1"] - x["f0"]) / FPS + 2 * a.pad)
    out = ROOT / "data" / "meva" / "clips" / f"{a.video.stem}_{a.activity}_{x['f0']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-ss", f"{t0:.2f}", "-i", str(a.video), "-t", f"{dur:.2f}",
                    "-vf", "scale=1280:-2", "-an", "-c:v", "libx264", "-crf", "23", "-y", str(out)], check=True)
    print(f"cut {out.relative_to(ROOT)}  window {t0:.1f}s +{dur:.1f}s")


if __name__ == "__main__":
    main()
