"""Demo teach-story windows from the CC BY "Thief stealing our package" clip (the full footage behind the Playground's package clip).

The hand-annotated event times live in `eval/data/frollard.yaml` (read off 0.5 s contact sheets of the clip; see README.md).
This module derives the labelled windows from them and cuts the clips (no crop, 1280 px wide) into
`$EXEMPLAR_DATA_DIR/external/windows/<id>.mp4`.

Labelling rule for the concept "package theft": a window is **positive** iff the whole pickup-and-leave event
(`theft`) lies inside it; a window that overlaps `theft` only partly is **excluded** (ambiguous); every other window is
a **negative** (box on the steps with nobody taking it, a person walking up but not yet taking it, a walk-by,
or an empty scene).

    uv run --project engine python -m eval.data.frollard [--no-cut]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import annotations as A
from . import paths
from .config import dump_yaml, load_yaml
from .cut import cut_clip

CONCEPT = "package_theft"
HEADER = ("# Annotations of external/frollard_thief.mp4 (times in ms from the start of the clip) + windows derived from them by\n"
          "# `python -m eval.data.frollard`. Edit `events`/`window`, then rerun; the `windows` list is regenerated.\n")


def classify(events: dict[str, tuple[int, int]], start_ms: int, dur_ms: int) -> tuple[str, str]:
    """(label, kind) for a window under the package-theft rule. label in pos | neg | excluded."""
    end = start_ms + dur_ms
    t0, t1 = events["theft"]
    if start_ms <= t0 and t1 <= end:
        return "pos", "theft"
    if A.overlaps(start_ms, end, t0, t1):
        return "excluded", "partial_theft"
    w0, w1 = events["walk_by"]
    if A.overlaps(start_ms, end, w0, w1):
        return "neg", "walk_by"
    u0, u1 = events["person_walks_up"]
    if A.overlaps(start_ms, end, u0, u1):
        return "neg", "person_walks_up_no_pickup"
    b0, b1 = events["box_on_steps"]
    if A.overlaps(start_ms, end, b0, b1):
        return "neg", "box_only"
    return "neg", "empty_scene"


def make_windows(ann: dict) -> list[dict]:
    events = {k: (v["start_ms"], v["end_ms"]) for k, v in ann["events"].items()}
    dur, stride, total = ann["window"]["dur_ms"], ann["window"]["stride_ms"], ann["video"]["duration_ms"]
    out = []
    for start in range(0, total - dur + 1, stride):
        label, kind = classify(events, start, dur)
        overlapping = sorted(k for k, (a, b) in events.items() if A.overlaps(start, start + dur, a, b))
        out.append({"id": f"frollard-{start:06d}", "concept": CONCEPT, "label": label, "kind": kind, "start_ms": start, "dur_ms": dur,
                    "events": overlapping})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--no-cut", action="store_true")
    args = ap.parse_args(argv)

    ann = load_yaml("frollard.yaml")
    ann["windows"] = make_windows(ann)
    dump_yaml("frollard.yaml", ann, header=HEADER)
    n = {lab: sum(w["label"] == lab for w in ann["windows"]) for lab in ("pos", "neg", "excluded")}
    print(f"{len(ann['windows'])} windows: {n}")
    if args.no_cut:
        return 0
    src = Path(paths.external_dir() / ann["video"]["file"])
    cut = 0
    for w in ann["windows"]:
        if w["label"] == "excluded":
            continue
        cut += cut_clip(src, paths.windows_dir() / f"{w['id']}.mp4", w["start_ms"], w["dur_ms"], None) == "cut"
    print(f"cut {cut} clips into {paths.windows_dir()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
