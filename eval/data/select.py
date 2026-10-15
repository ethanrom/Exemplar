"""Choose the MEVA videos for the benchmark and write `eval/data/videos.yaml`.

Candidates = annotated exterior-EO clips (`list-of-annotated-meva-clips.txt` / presence of `*.activities.yml`)
that exist in the S3 bucket with a plausible 5-minute size.  Each is scored by how many instances of the concept
activities it contains.  Selection is a deterministic greedy coverage problem:

  * pick `n_cameras` cameras, each contributing its `per_camera_min` best videos (at most `max_per_cam_day` per day),
    so that every camera can appear in train, calib and test;
  * then fill up to `n_videos` from the chosen cameras (at most `max_per_camera` each);
  * marginal gain of a video = sum over concepts of the extra instances it adds, capped at `target` per concept and
    normalised by `target`, so scarce concepts (loading/unloading) steer the choice.

    uv run --project engine python -m eval.data.select [--n-videos 21] [--cameras 6] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from . import annotations as A
from . import paths, s3
from .config import EXTERIOR_CAMERAS, activity_to_concepts, dump_yaml, load_concepts

MIN_BYTES = 100_000_000  # shorter/odd clips are skipped
MAX_BYTES = 260_000_000  # keeps the disk budget


@dataclass
class Candidate:
    stem: str
    camera: str
    date: str
    annotation_hour: str
    s3_hour: str
    key: str
    size: int
    counts: dict[str, int] = field(default_factory=dict)  # concept id -> annotated instances

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def build_candidates(concept_ids: list[str], act2concepts: dict[str, list[str]]) -> list[Candidate]:
    root = paths.annotation_dir()
    listing = s3.list_videos()
    out: list[Candidate] = []
    for stem, (date, hour) in sorted(A.index_annotation_files(root).items()):
        name = A.parse_video_name(stem)
        v = listing.get(stem)
        if name.camera not in EXTERIOR_CAMERAS or v is None or not (MIN_BYTES <= v.size <= MAX_BYTES):
            continue
        counts = dict.fromkeys(concept_ids, 0)
        for act in A.load_activities(A.activities_path(root, stem, hour)):
            for cid in act2concepts.get(act.name, ()):
                counts[cid] += 1
        out.append(Candidate(stem, name.camera, date, hour, v.hour, v.key, v.size, counts))
    return out


def gain(cand: Candidate, cover: dict[str, int], target: int) -> float:
    return sum((min(target, cover[c] + n) - min(target, cover[c])) / target for c, n in cand.counts.items())


def choose_videos(cands: list[Candidate], concept_ids: list[str], n_videos: int = 21, n_cameras: int = 6,
                  per_camera_min: int = 3, max_per_camera: int = 5, max_per_cam_day: int = 3, target: int = 60) -> list[Candidate]:
    """Deterministic greedy selection (see module docstring)."""
    cover = dict.fromkeys(concept_ids, 0)
    chosen: list[Candidate] = []
    by_cam: dict[str, list[Candidate]] = {}
    for c in cands:
        by_cam.setdefault(c.camera, []).append(c)

    def pick_best(cam_cands: list[Candidate], k: int, cover_: dict[str, int], taken: list[Candidate]) -> list[Candidate]:
        picked: list[Candidate] = []
        cov = dict(cover_)
        day_n: dict[str, int] = {}
        for t in taken:
            day_n[t.date] = day_n.get(t.date, 0) + 1
        while len(picked) < k:
            pool = [c for c in cam_cands if c not in picked and c not in taken and day_n.get(c.date, 0) < max_per_cam_day]
            if not pool:
                break
            best = max(pool, key=lambda c: (round(gain(c, cov, target), 9), -c.size, c.stem))
            picked.append(best)
            day_n[best.date] = day_n.get(best.date, 0) + 1
            for cid, n in best.counts.items():
                cov[cid] += n
        return picked

    cams_left = sorted(by_cam)
    for _ in range(n_cameras):
        scored = []
        for cam in cams_left:
            picks = pick_best(by_cam[cam], per_camera_min, cover, [])
            if len(picks) < per_camera_min:
                continue
            cov = dict(cover)
            g = 0.0
            for p in picks:
                g += gain(p, cov, target)
                for cid, n in p.counts.items():
                    cov[cid] += n
            scored.append((round(g, 9), cam, picks))
        if not scored:
            break
        g, cam, picks = max(scored, key=lambda s: (s[0], s[1]))
        chosen.extend(picks)
        for p in picks:
            for cid, n in p.counts.items():
                cover[cid] += n
        cams_left.remove(cam)

    cams = sorted({c.camera for c in chosen})
    while len(chosen) < n_videos:
        pool = [c for c in cands if c.camera in cams and c not in chosen
                and sum(x.camera == c.camera for x in chosen) < max_per_camera
                and sum(x.camera == c.camera and x.date == c.date for x in chosen) < max_per_cam_day]
        if not pool:
            break
        best = max(pool, key=lambda c: (round(gain(c, cover, target), 9), -c.size, c.stem))
        chosen.append(best)
        for cid, n in best.counts.items():
            cover[cid] += n
    return sorted(chosen, key=lambda c: (c.camera, c.stem))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n-videos", type=int, default=22)
    ap.add_argument("--cameras", type=int, default=5)
    ap.add_argument("--target", type=int, default=60, help="per-concept instance target for the coverage objective")
    ap.add_argument("--refresh-s3", action="store_true", help="re-list the bucket instead of using the cached listing")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if args.refresh_s3:
        s3.list_videos(refresh=True)
    concepts = load_concepts()
    cids = list(concepts)
    cands = build_candidates(cids, activity_to_concepts(concepts))
    print(f"{len(cands)} candidate videos; instances per concept: " + ", ".join(f"{c}={sum(x.counts[c] for x in cands)}" for c in cids))
    chosen = choose_videos(cands, cids, args.n_videos, args.cameras, target=args.target)
    tot = {c: sum(x.counts[c] for x in chosen) for c in cids}
    print(f"selected {len(chosen)} videos, {sum(x.size for x in chosen) / 1e9:.2f} GB, cameras={sorted({x.camera for x in chosen})}, "
          f"days={sorted({x.date for x in chosen})}")
    print("instances:", tot)
    for x in chosen:
        print(f"  {x.stem:48s} {x.size / 1e6:6.0f} MB  " + " ".join(f"{c[:6]}={x.counts[c]:3d}" for c in cids))
    if args.dry_run:
        return 0
    data = {
        "source": "s3://mevadata-public-01/drops-123-r13/ (anonymous, us-east-1); annotations gitlab.kitware.com/meva/meva-data-repo "
                  "annotation/DIVA-phase-2/MEVA/kitware",
        "params": {"n_videos": args.n_videos, "cameras": args.cameras, "target_per_concept": args.target, "size_bytes_range": [MIN_BYTES, MAX_BYTES]},
        "instances_per_concept": tot,
        "videos": [
            {"stem": x.stem, "camera": x.camera, "date": x.date, "annotation_hour": x.annotation_hour, "s3_key": x.key,
             "size_bytes": x.size, "instances": x.counts}
            for x in chosen
        ],
    }
    dump_yaml("videos.yaml", data, header="# Generated by `python -m eval.data.select`; committed so the benchmark is reproducible.\n")
    print("wrote eval/data/videos.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
