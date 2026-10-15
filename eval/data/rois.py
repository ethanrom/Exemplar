"""One fixed 16:9 crop (ROI) per camera view, at native resolution, written to `eval/data/rois.yaml`.

Why: people are 10-40 px tall in the 1920x1080 frame, so perception on the full frame (resized to 640 px) loses them.
A fixed crop around where the action happens approximates a close-range doorbell field of view.

Rule (documented in README.md; chosen ONCE per camera, never per activity or per clip, from **train-split videos only**):
  1. Take every instance of **every concept activity** (all four concepts) in the camera's train videos; an instance is the
     set of its actors' boxes (every 5th frame) during the activity.
  2. Fix the crop size to `ROI_W` x `ROI_W*9/16` = 960 x 540 (half the frame width, 16:9, even pixels).
  3. Slide it over the frame on a 32 x 18 px grid and keep the positions that maximise the **concept-balanced** number of
     instances that are *in view* (>= 80 % of the instance's box centres inside the crop); each concept carries equal total
     weight so the rare loading/unloading concept steers the position as much as door crossings.
  4. Among the maximisers take the one whose centre is closest to the (concept-weighted) mean position of the instances
     they cover, i.e. centre the crop on the action.

(The originally planned "union of all activity boxes" rule gives nearly the whole frame on wide parking-lot views, e.g.
G424, which defeats the purpose of a close-up crop; see README.md.)

    uv run --project engine python -m eval.data.rois [--no-preview] [--width 960]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import imageio_ffmpeg
import numpy as np

from . import annotations as A
from . import paths
from .config import activity_to_concepts, dump_yaml, load_concepts, load_yaml
from .probe import load_info
from .splits import load_split_map

ROI_W = 960
IN_VIEW = 0.8       # an instance is "in view" if >= 80 % of its box centres are inside the ROI
OUT_OF_VIEW = 0.1   # ... and "out of view" if <= 10 % are; in between it is ambiguous
BOX_STEP = 5
GRID_X, GRID_Y = 32, 18


def roi_size(width: int) -> tuple[int, int]:
    return width, width * 9 // 16


def view_fraction(centers: np.ndarray, roi: tuple[int, int, int, int]) -> float:
    """Fraction of (n, 2) box centres inside roi=(x, y, w, h)."""
    if len(centers) == 0:
        return 0.0
    x, y, w, h = roi
    inside = (centers[:, 0] >= x) & (centers[:, 0] < x + w) & (centers[:, 1] >= y) & (centers[:, 1] < y + h)
    return float(inside.mean())


def centers_of(boxes: np.ndarray) -> np.ndarray:
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 4)
    return np.stack([(boxes[:, 0] + boxes[:, 2]) / 2, (boxes[:, 1] + boxes[:, 3]) / 2], axis=1)


def choose_roi(instances: list[tuple[str, np.ndarray]], frame_w: int, frame_h: int, width: int = ROI_W) -> tuple[int, int, int, int]:
    """instances: (concept id, (n, 2) box centres) per annotated instance. Returns (x, y, w, h) in native pixels."""
    w, h = roi_size(min(width, frame_w // 32 * 32, int(frame_h * 16 / 9) // 32 * 32))
    xs = list(range(0, frame_w - w + 1, GRID_X))
    ys = list(range(0, frame_h - h + 1, GRID_Y))
    if not instances:
        return (frame_w - w) // 2 // 2 * 2, (frame_h - h) // 2 // 2 * 2, w, h
    per_concept: dict[str, int] = {}
    for c, _ in instances:
        per_concept[c] = per_concept.get(c, 0) + 1
    wts = np.array([1.0 / per_concept[c] / len(per_concept) for c, _ in instances])
    scores = np.zeros((len(ys), len(xs)))
    in_view = np.zeros((len(ys), len(xs), len(instances)), dtype=bool)
    for iy, y in enumerate(ys):
        for ix, x in enumerate(xs):
            ins = np.array([view_fraction(ctr, (x, y, w, h)) >= IN_VIEW for _, ctr in instances])
            in_view[iy, ix] = ins
            scores[iy, ix] = float((wts * ins).sum())
    best = scores.max()
    iy, ix = np.nonzero(scores >= best - 1e-9)
    # centre the crop on the action: among the maximisers pick the one whose centre is closest to the weighted mean
    # position of the instances that at least one maximiser covers
    covered = in_view[iy, ix].any(axis=0)
    means = np.array([ctr.mean(axis=0) if len(ctr) else (0.0, 0.0) for _, ctr in instances])
    target = (means[covered] * wts[covered, None]).sum(axis=0) / wts[covered].sum()
    centres = np.stack([np.array(xs)[ix] + w / 2, np.array(ys)[iy] + h / 2], axis=1)
    k = int(np.argmin(((centres - target) ** 2).sum(axis=1)))
    return xs[ix[k]] // 2 * 2, ys[iy[k]] // 2 * 2, w, h


def ensure_geometry(stems_hours: list[tuple[str, str]]) -> None:
    """Fetch the (blob-less sparse clone's) geometry files for these clips on demand."""
    root = paths.annotation_dir()
    need = [(s, h) for s, h in stems_hours if not A.geometry_path(root, s, h).is_file()]
    if not need:
        return
    pats = [f"/annotation/DIVA-phase-2/MEVA/kitware/{A.parse_video_name(s).date}/{h}/{s}.geom.yml" for s, h in need]
    subprocess.run(["git", "-C", str(paths.repo_clone()), "sparse-checkout", "add", *pats], check=True, capture_output=True)


@lru_cache(maxsize=64)
def _video_geometry(stem: str, hour: str) -> A.Geometry:
    return A.load_geometry(A.geometry_path(paths.annotation_dir(), stem, hour))


@lru_cache(maxsize=64)
def _video_activities(stem: str, hour: str) -> list[A.Activity]:
    return A.load_activities(A.activities_path(paths.annotation_dir(), stem, hour))


def video_instances(stem: str, hour: str, act_names: set[str] | None, step: int = BOX_STEP) -> list[tuple[A.Activity, np.ndarray]]:
    """Activity instances of one video (all of them if `act_names` is None) with the (n, 2) centres of their actors' boxes
    (needs the geometry file). Parsed files are cached per process."""
    geo = _video_geometry(stem, hour)
    return [(act, centers_of(np.array(A.activity_boxes(act, geo, step))))
            for act in _video_activities(stem, hour) if act_names is None or act.name in act_names]


def load_rois() -> dict[str, tuple[int, int, int, int]]:
    return {cam: tuple(v["roi"]) for cam, v in load_yaml("rois.yaml")["cameras"].items()}


def grab_frame(video: Path, t_s: float, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-ss", f"{t_s:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", "-y", str(out)],
                   check=True)


def render_preview(cam: str, video: Path, t_s: float, roi: tuple[int, int, int, int], centers: np.ndarray, out: Path) -> None:
    from PIL import Image, ImageDraw

    tmp = out.with_suffix(".raw.jpg")
    grab_frame(video, t_s, tmp)
    im = Image.open(tmp).convert("RGB")
    x, y, w, h = roi
    crop = im.crop((x, y, x + w, y + h)).resize((1280, round(1280 * h / w)), Image.LANCZOS)
    crop.save(out.with_name(out.stem + "_crop.jpg"), quality=88)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for cx, cy in centers[:: max(1, len(centers) // 600)]:
        d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], outline=(255, 255, 0, 255), width=2)
    d.rectangle([x, y, x + w, y + h], outline=(255, 0, 0, 255), width=6)
    d.text((x + 10, y + 10), f"{cam} ROI {w}x{h} @ ({x},{y})", fill=(255, 0, 0, 255))
    Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB").save(out, quality=88)
    tmp.unlink()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--width", type=int, default=ROI_W)
    args = ap.parse_args(argv)

    concepts = load_concepts()
    a2c = activity_to_concepts(concepts)
    act_names = set(a2c)
    videos = load_yaml("videos.yaml")["videos"]
    splits = load_split_map()
    info = load_info()
    ensure_geometry([(v["stem"], v["annotation_hour"]) for v in videos])
    out: dict[str, dict] = {}
    for cam in sorted({v["camera"] for v in videos}):
        cam_videos = [v for v in videos if v["camera"] == cam]
        train = [v for v in cam_videos if splits[v["stem"]] == "train"]
        sizes = [(info[v["stem"]]["width"], info[v["stem"]]["height"]) for v in cam_videos if v["stem"] in info]
        if not sizes:
            raise SystemExit(f"{cam}: no probed videos; run eval.data.download and eval.data.probe first")
        fw, fh = min(s[0] for s in sizes), min(s[1] for s in sizes)
        train_inst = [(a, c) for v in train for a, c in video_instances(v["stem"], v["annotation_hour"], act_names)]
        roi = choose_roi([(a2c[a.name][0], c) for a, c in train_inst if len(c)], fw, fh, args.width)
        fr = np.array([view_fraction(c, roi) for _, c in train_inst])
        # honest held-out coverage: the same ROI applied to the camera's calib/test instances
        held = [(a, c) for v in cam_videos if splits[v["stem"]] != "train" for a, c in video_instances(v["stem"], v["annotation_hour"], act_names)]
        hf = np.array([view_fraction(c, roi) for _, c in held])
        out[cam] = {
            "frame": [fw, fh], "roi": list(roi), "train_videos": [v["stem"] for v in train], "train_instances": len(train_inst),
            "train_in_view": round(float((fr >= IN_VIEW).mean()), 3) if len(fr) else None,
            "heldout_instances": len(held), "heldout_in_view": round(float((hf >= IN_VIEW).mean()), 3) if len(hf) else None,
        }
        print(cam, out[cam])
        if not args.no_preview:
            v0 = train[0]
            vid = paths.videos_dir() / f"{v0['stem']}.r13.avi"
            if vid.is_file():
                inst0 = [(a, c) for a, c in video_instances(v0["stem"], v0["annotation_hour"], act_names) if len(c)]
                inview = [a for a, c in inst0 if view_fraction(c, roi) >= IN_VIEW] or [a for a, _ in inst0]
                t = (inview[len(inview) // 2].start_ms / 1000 + 1.0) if inview else 60.0
                allc = np.concatenate([c for _, c in train_inst if len(c)]) if train_inst else np.zeros((0, 2))
                render_preview(cam, vid, t, roi, allc, paths.roi_previews_dir() / f"{cam}.jpg")
    dump_yaml("rois.yaml", {
        "rule": f"Per camera, from train-split videos only: fixed {args.width}x{args.width * 9 // 16} (16:9) crop at the grid position that maximises "
                f"the concept-balanced count of annotated concept instances in view (>= {int(IN_VIEW * 100)}% of box centres inside); "
                "ties -> centroid of the maximisers.",
        "format": "roi = [x, y, w, h] in native pixels of the 30 fps AVI; frame = [W, H]; *_in_view = share of annotated concept instances in view",
        "in_view_threshold": IN_VIEW, "out_of_view_threshold": OUT_OF_VIEW,
        "cameras": out,
    }, header="# Generated by `python -m eval.data.rois`; committed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
