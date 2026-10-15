"""Build the benchmark windows (`eval/data/manifest.jsonl`) from annotations, ROIs and splits.

Per (concept, video):
  * **Positive** = an annotated, *in-view* instance of one of the concept's activities, padded with seeded random padding to a
    10-20 s window that lies inside the video and contains the whole instance (>= 0.5 s of context on both sides when
    possible).  In view = >= 80 % of the instance's actor-box centres lie inside the camera's ROI (see rois.py); instances
    that are only partly in view, or lie outside the ROI, never become positives.  An instance already fully inside an
    earlier positive window yields no second (near-duplicate) window.
  * **Negative** = a seeded random 10-20 s window that comes no closer than `GUARD_MS` (1 s) to any instance of the concept's
    activities that is in view or ambiguous (instances entirely outside the ROI are invisible to a doorbell-style crop and
    are ignored; they are counted in `own_out_of_view`).  Half of the negatives are *hard*: drawn so that they contain an
    in-view instance of a confuser activity (concepts.yaml); the rest are uniform over the valid start times.
  * Windows of the same concept and video never overlap each other.
  * ~`NEG_RATIO` negatives per positive per concept, spread over videos half uniformly, half in proportion to positives.

Everything is seeded: `random.Random(f"{seed}|{concept}|{video}")`.

    uv run --project engine python -m eval.data.windows [--seed 0]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

from . import annotations as A
from . import paths
from .config import SPLITS, Concept, load_concepts, load_yaml
from .rois import IN_VIEW, OUT_OF_VIEW, ensure_geometry, view_fraction, video_instances
from .splits import load_split_map

MIN_MS, MAX_MS = 10_000, 20_000
GUARD_MS = 1_000
EDGE_MS = 500
NEG_RATIO = 3.5
HARD_FRAC = 0.5
EVAL_DATA = paths.EVAL_DATA


@dataclass(frozen=True)
class Window:
    start_ms: int
    dur_ms: int

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.dur_ms


def _overlap(w: Window, s: int, e: int) -> bool:
    return A.overlaps(w.start_ms, w.end_ms, s, e)


def window_around(s: int, e: int, video_ms: int, rng: random.Random, occupied: list[Window] | tuple[Window, ...] = (),
                  min_ms: int = MIN_MS, max_ms: int = MAX_MS, edge_ms: int = EDGE_MS) -> Window | None:
    """Random `min_ms..max_ms` window inside [0, video_ms] containing [s, e), disjoint from `occupied`. None if impossible."""
    if e <= s or e > video_ms or any(_overlap(o, s, e) for o in occupied):
        return None
    left = max([o.end_ms for o in occupied if o.end_ms <= s], default=0)
    right = min([o.start_ms for o in occupied if o.start_ms >= e], default=video_ms)
    right = min(right, video_ms)
    for margin in (edge_ms, 0):
        d_lo = max(min_ms, e - s + 2 * margin)
        if d_lo > max_ms:
            continue
        for _ in range(8):
            d = rng.randint(d_lo, max_ms)
            lo = max(left, e + margin - d)
            hi = min(s - margin, right - d)
            if lo <= hi:
                return Window(rng.randint(lo, hi), d)
    return None


def place_positives(insts: list[A.Activity], video_ms: int, rng: random.Random, min_ms: int = MIN_MS, max_ms: int = MAX_MS) -> tuple[list[Window], dict[str, int]]:
    """Greedy, time-ordered positive windows for in-view instances. Returns (windows, reasons for skipped instances)."""
    wins: list[Window] = []
    skipped: Counter = Counter()
    for a in sorted(insts, key=lambda a: (a.start_ms, a.act_id)):
        if any(w.start_ms <= a.start_ms and a.end_ms <= w.end_ms for w in wins):
            skipped["covered_by_earlier_window"] += 1
            continue
        if a.end_ms > video_ms:
            skipped["beyond_video_end"] += 1
            continue
        w = window_around(a.start_ms, a.end_ms, video_ms, rng, wins, min_ms, max_ms)
        if w is None:
            skipped["no_room"] += 1
            continue
        wins.append(w)
    return sorted(wins, key=lambda w: w.start_ms), dict(skipped)


def sample_negatives(n: int, video_ms: int, forbidden: list[tuple[int, int]], occupied: list[Window], hard_anchors: list[tuple[int, int]],
                     rng: random.Random, hard_frac: float = HARD_FRAC, guard_ms: int = GUARD_MS, min_ms: int = MIN_MS, max_ms: int = MAX_MS,
                     tries: int = 300) -> list[Window]:
    """Up to `n` valid negative windows. `forbidden` = (start, end) ms spans the window must stay `guard_ms` away from;
    the first ceil(hard_frac * n) are built around a random anchor in `hard_anchors` (confuser instances) when possible."""
    wins: list[Window] = []
    zones = [(s - guard_ms, e + guard_ms) for s, e in forbidden]

    def ok(w: Window) -> bool:
        return (w.start_ms >= 0 and w.end_ms <= video_ms and not any(_overlap(w, a, b) for a, b in zones)
                and not any(A.overlaps(w.start_ms, w.end_ms, o.start_ms, o.end_ms) for o in [*occupied, *wins]))

    n_hard = int(np.ceil(hard_frac * n))
    for i in range(n):
        want_hard = i < n_hard and bool(hard_anchors)
        for _ in range(tries):
            if want_hard:
                s, e = hard_anchors[rng.randrange(len(hard_anchors))]
                w = window_around(s, e, video_ms, rng, [*occupied, *wins], min_ms, max_ms, edge_ms=0)
            else:
                d = rng.randint(min_ms, max_ms)
                if video_ms - d < 0:
                    break
                w = Window(rng.randint(0, video_ms - d), d)
            if w is not None and ok(w):
                wins.append(w)
                break
        else:
            if want_hard:  # fall back to a plain random window for this slot
                for _ in range(tries):
                    d = rng.randint(min_ms, max_ms)
                    w = Window(rng.randint(0, video_ms - d), d)
                    if ok(w):
                        wins.append(w)
                        break
    return sorted(wins, key=lambda w: w.start_ms)


def allocate(total: int, weights: list[float], caps: list[int]) -> list[int]:
    """Largest-remainder allocation of `total` slots by `weights`, never exceeding `caps` (surplus flows to the others)."""
    out = [0] * len(weights)
    left = total
    active = [i for i, c in enumerate(caps) if c > 0]
    while left > 0 and active:
        wsum = sum(weights[i] for i in active) or 1.0
        raw = {i: left * weights[i] / wsum for i in active}
        add = {i: min(int(raw[i]), caps[i] - out[i]) for i in active}
        rest = left - sum(add.values())
        for i in sorted(active, key=lambda i: (-(raw[i] - int(raw[i])), i)):
            if rest <= 0:
                break
            if out[i] + add[i] < caps[i]:
                add[i] += 1
                rest -= 1
        for i in active:
            out[i] += add[i]
        gained = sum(add.values())
        left -= gained
        active = [i for i in active if out[i] < caps[i]]
        if gained == 0:
            break
    return out


def _compact(stem: str) -> str:
    n = A.parse_video_name(stem)
    return f"{n.camera}-{n.date.replace('-', '')}{n.start.replace('-', '')}"


def window_id(concept: str, stem: str, w: Window, label: str) -> str:
    return f"{concept}-{_compact(stem)}-{w.start_ms:06d}-{label}"


def build(seed: int = 0, neg_ratio: float = NEG_RATIO, hard_frac: float = HARD_FRAC) -> tuple[list[dict], dict]:
    concepts = load_concepts()
    a2c: dict[str, list[str]] = defaultdict(list)
    for c in concepts.values():
        for a in c.activities:
            a2c[a].append(c.id)
    videos = load_yaml("videos.yaml")["videos"]
    splits = load_split_map()
    rois = {cam: tuple(v["roi"]) for cam, v in load_yaml("rois.yaml")["cameras"].items()}
    info = load_yaml("video_info.yaml")["videos"]
    ensure_geometry([(v["stem"], v["annotation_hour"]) for v in videos])
    root = paths.annotation_dir()

    # per video: every annotated activity with its view state under the camera ROI
    per_video: dict[str, list[tuple[A.Activity, str]]] = {}
    all_names = {a.name for v in videos for a in A.load_activities(A.activities_path(root, v["stem"], v["annotation_hour"]))}
    for v in videos:
        roi = rois[v["camera"]]
        states = []
        for act, ctr in video_instances(v["stem"], v["annotation_hour"], all_names):
            f = view_fraction(ctr, roi)
            states.append((act, "in_view" if f >= IN_VIEW else "out_of_view" if f <= OUT_OF_VIEW else "partial"))
        per_video[v["stem"]] = states

    manifest: list[dict] = []
    stats: dict = {"skipped": defaultdict(Counter), "positives_raw": Counter(), "out_of_view": Counter(), "partial": Counter()}
    for cid, concept in concepts.items():
        own = set(concept.activities)
        confusers = set(concept.confusers)
        pos_by_video: dict[str, list[Window]] = {}
        for v in videos:
            stem = v["stem"]
            states = per_video[stem]
            vms = info[stem]["duration_ms"]
            rng = random.Random(f"{seed}|{cid}|{stem}")
            in_view = [a for a, st in states if a.name in own and st == "in_view"]
            stats["positives_raw"][cid] += len(in_view)
            stats["out_of_view"][cid] += sum(1 for a, st in states if a.name in own and st == "out_of_view")
            stats["partial"][cid] += sum(1 for a, st in states if a.name in own and st == "partial")
            wins, skipped = place_positives(in_view, vms, rng)
            pos_by_video[stem] = wins
            for k, n in skipped.items():
                stats["skipped"][cid][k] += n
        total_pos = sum(len(w) for w in pos_by_video.values())
        n_total_neg = round(neg_ratio * total_pos)
        caps, weights = [], []
        for v in videos:
            stem = v["stem"]
            vms = info[stem]["duration_ms"]
            used = sum(w.dur_ms for w in pos_by_video[stem])
            caps.append(max(0, int((vms - used) // ((MIN_MS + MAX_MS) / 2 + 2 * GUARD_MS) )))
            weights.append(0.5 * len(pos_by_video[stem]) / max(total_pos, 1) + 0.5 / len(videos))
        quotas = allocate(n_total_neg, weights, caps)
        for v, quota in zip(videos, quotas):
            stem = v["stem"]
            vms = info[stem]["duration_ms"]
            states = per_video[stem]
            forbidden = [(a.start_ms, a.end_ms) for a, st in states if a.name in own and st != "out_of_view"]
            anchors = [(a.start_ms, a.end_ms) for a, st in states if a.name in confusers and st == "in_view" and a.name not in own]
            rng = random.Random(f"{seed}|{cid}|{stem}|neg")
            negs = sample_negatives(quota, vms, forbidden, pos_by_video[stem], anchors, rng, hard_frac)
            for label, wins in (("pos", pos_by_video[stem]), ("neg", negs)):
                for w in wins:
                    manifest.append(_row(cid, concept, v, splits[stem], rois[v["camera"]], states, own, confusers, w, label))
    manifest.sort(key=lambda r: (r["concept"], r["split"], r["video"], r["start_ms"]))
    return manifest, stats


def _row(cid: str, concept: Concept, v: dict, split: str, roi: tuple, states: list[tuple[A.Activity, str]], own: set[str], confusers: set[str],
         w: Window, label: str) -> dict:
    name = A.parse_video_name(v["stem"])
    inside = [(a, st) for a, st in states if A.overlaps(w.start_ms, w.end_ms, a.start_ms, a.end_ms)]
    others = sorted({a.name for a, _ in inside if a.name not in own})
    events = [
        {"activity": a.name, "act_id": a.act_id, "start_ms": max(a.start_ms, w.start_ms) - w.start_ms, "end_ms": min(a.end_ms, w.end_ms) - w.start_ms}
        for a, st in inside if a.name in own and st == "in_view"
    ]
    row = {
        "id": window_id(cid, v["stem"], w, label), "concept": cid, "label": label, "split": split, "video": v["stem"], "camera": v["camera"],
        "date": name.date, "start_ms": w.start_ms, "dur_ms": w.dur_ms, "roi": list(roi), "other_activities": others,
        "hard": (any(a.name in confusers and st == "in_view" and a.name not in own for a, st in inside) if label == "neg" else None),
        "own_out_of_view": sum(1 for a, st in inside if a.name in own and st == "out_of_view"),
        "events": sorted(events, key=lambda e: e["start_ms"]),
        "source_ref": (f"meva:{v['stem']}#act_id=" + ",".join(str(e["act_id"]) for e in events)) if label == "pos" else f"meva:{v['stem']}#random",
        "clip": f"meva/clips/{cid}/{window_id(cid, v['stem'], w, label)}.mp4",
    }
    return row


def write_manifest(rows: list[dict]) -> None:
    with (EVAL_DATA / "manifest.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=False) + "\n")


def stats_markdown(rows: list[dict], stats: dict, seed: int) -> str:
    concepts = load_concepts()
    videos = load_yaml("videos.yaml")["videos"]
    splits = load_split_map()
    rois = load_yaml("rois.yaml")["cameras"]
    out = [f"# Benchmark statistics (seed {seed})", "", "Generated by `python -m eval.data.windows`; do not edit by hand.", ""]
    out += ["## Windows per concept and split", "", "| concept | split | pos | neg | hard neg | neg/pos | total min |", "|---|---|---:|---:|---:|---:|---:|"]
    for cid in concepts:
        tp = tn = th = 0
        for s in SPLITS:
            rr = [r for r in rows if r["concept"] == cid and r["split"] == s]
            p = sum(r["label"] == "pos" for r in rr)
            n = sum(r["label"] == "neg" for r in rr)
            h = sum(bool(r["hard"]) for r in rr)
            mins = sum(r["dur_ms"] for r in rr) / 60000
            out.append(f"| {cid} | {s} | {p} | {n} | {h} | {n / p:.1f} | {mins:.1f} |" if p else f"| {cid} | {s} | {p} | {n} | {h} | - | {mins:.1f} |")
            tp, tn, th = tp + p, tn + n, th + h
        out.append(f"| **{cid}** | **all** | **{tp}** | **{tn}** | **{th}** | **{tn / max(tp, 1):.1f}** | |")
    out += ["", "## Positives by camera", "", "| concept | " + " | ".join(sorted({v['camera'] for v in videos})) + " |",
            "|---|" + "---:|" * len({v['camera'] for v in videos})]
    for cid in concepts:
        cnt = Counter(r["camera"] for r in rows if r["concept"] == cid and r["label"] == "pos")
        out.append(f"| {cid} | " + " | ".join(str(cnt[c]) for c in sorted({v['camera'] for v in videos})) + " |")
    out += ["", "## Annotated instances not turned into positives", "",
            "| concept | in view | positives (windows) | out of ROI view | partly in view | skipped: covered / no room / beyond end |", "|---|---:|---:|---:|---:|---|"]
    for cid in concepts:
        sk = stats["skipped"][cid]
        npos = sum(r["label"] == "pos" for r in rows if r["concept"] == cid)
        out.append(f"| {cid} | {stats['positives_raw'][cid]} | {npos} | {stats['out_of_view'][cid]} | {stats['partial'][cid]} | "
                   f"{sk.get('covered_by_earlier_window', 0)} / {sk.get('no_room', 0)} / {sk.get('beyond_video_end', 0)} |")
    out += ["", "## Videos", "", "| split | video | camera |", "|---|---|---|"]
    for s in SPLITS:
        for v in videos:
            if splits[v["stem"]] == s:
                out.append(f"| {s} | `{v['stem']}` | {v['camera']} |")
    out += ["", "## ROI (native pixels)", "", "| camera | frame | roi x,y,w,h | train instances in view | held-out instances in view |", "|---|---|---|---:|---:|"]
    for cam, r in rois.items():
        out.append(f"| {cam} | {r['frame'][0]}x{r['frame'][1]} | {tuple(r['roi'])} | {r['train_in_view']} | {r['heldout_in_view']} |")
    other = Counter(a for r in rows if r["label"] == "neg" for a in r["other_activities"])
    out += ["", "## Most frequent other activities inside negative windows", "", ", ".join(f"`{a}` ({n})" for a, n in other.most_common(10)), ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--neg-ratio", type=float, default=NEG_RATIO)
    args = ap.parse_args(argv)
    rows, stats = build(args.seed, args.neg_ratio)
    write_manifest(rows)
    (EVAL_DATA / "STATS.md").write_text(stats_markdown(rows, stats, args.seed), encoding="utf-8", newline="\n")
    c = Counter((r["concept"], r["split"], r["label"]) for r in rows)
    print(f"{len(rows)} windows")
    for (cid, s, lab), n in sorted(c.items()):
        print(f"  {cid:22s} {s:6s} {lab} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
