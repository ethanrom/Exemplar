"""Invariants of the committed benchmark files (manifest.jsonl, splits.yaml, rois.yaml, frollard.yaml)."""
from collections import Counter, defaultdict

import pytest

from eval.data import annotations as A
from eval.data import paths
from eval.data.config import SPLITS, load_concepts, load_yaml, read_manifest


@pytest.fixture(scope="module")
def manifest():
    try:
        return read_manifest()
    except FileNotFoundError:
        pytest.skip("manifest.jsonl not generated yet")


def test_window_lengths_and_bounds(manifest):
    info = load_yaml("video_info.yaml")["videos"]
    for r in manifest:
        assert 10_000 <= r["dur_ms"] <= 20_000, r["id"]
        assert r["start_ms"] >= 0 and r["start_ms"] + r["dur_ms"] <= info[r["video"]]["duration_ms"], r["id"]
        assert r["label"] in ("pos", "neg") and r["split"] in SPLITS


def test_ids_unique_and_clip_paths(manifest):
    ids = [r["id"] for r in manifest]
    assert len(ids) == len(set(ids))
    for r in manifest:
        assert r["clip"] == f"meva/clips/{r['concept']}/{r['id']}.mp4"


def test_no_video_in_two_splits(manifest):
    seen = defaultdict(set)
    for r in manifest:
        seen[r["video"]].add(r["split"])
    assert all(len(s) == 1 for s in seen.values())
    sp = load_yaml("splits.yaml")["splits"]
    flat = [v for vs in sp.values() for v in vs]
    assert len(flat) == len(set(flat))  # splits.yaml: each video once
    for split, vids in sp.items():
        for v in vids:
            assert seen.get(v, {split}) == {split}


def test_roi_matches_camera_and_every_camera_has_train_video(manifest):
    rois = load_yaml("rois.yaml")["cameras"]
    for r in manifest:
        assert r["roi"] == rois[r["camera"]]["roi"]
    train_cams = {r["camera"] for r in manifest if r["split"] == "train"}
    assert {r["camera"] for r in manifest} <= train_cams


def test_rois_come_from_train_videos_only():
    sp = load_yaml("splits.yaml")["splits"]
    for cam, r in load_yaml("rois.yaml")["cameras"].items():
        assert r["train_videos"], cam
        assert set(r["train_videos"]) <= set(sp["train"]), cam


def test_enough_windows_per_concept(manifest):
    c = Counter((r["concept"], r["label"]) for r in manifest)
    for cid in load_concepts():
        assert c[(cid, "pos")] >= 25, (cid, c[(cid, "pos")])
        assert c[(cid, "neg")] >= 2 * c[(cid, "pos")], cid
    for cid in load_concepts():
        for s in SPLITS:
            assert sum(1 for r in manifest if r["concept"] == cid and r["split"] == s and r["label"] == "pos") >= 3, (cid, s)


def test_positive_events_lie_inside_window(manifest):
    for r in manifest:
        if r["label"] == "pos":
            assert r["events"], r["id"]
            for e in r["events"]:
                assert 0 <= e["start_ms"] < e["end_ms"] <= r["dur_ms"], r["id"]
        else:
            assert r["events"] == [], r["id"]


def test_negatives_overlap_no_in_view_instance(manifest):
    """Re-derives instance view states from the raw annotations (needs the data dir; skipped otherwise)."""
    from eval.data.rois import IN_VIEW, OUT_OF_VIEW, video_instances, view_fraction

    root = paths.annotation_dir()
    concepts = load_concepts()
    videos = {v["stem"]: v for v in load_yaml("videos.yaml")["videos"]}
    cache: dict[str, list] = {}
    for r in manifest:
        if r["label"] != "neg":
            continue
        v = videos[r["video"]]
        geom = A.geometry_path(root, v["stem"], v["annotation_hour"])
        if not geom.is_file():
            pytest.skip("geometry files not available")
        if v["stem"] not in cache:
            cache[v["stem"]] = video_instances(v["stem"], v["annotation_hour"], {a for c in concepts.values() for a in c.activities})
        own = set(concepts[r["concept"]].activities)
        for act, ctr in cache[v["stem"]]:
            if act.name in own and A.overlaps(r["start_ms"], r["start_ms"] + r["dur_ms"], act.start_ms - 1000, act.end_ms + 1000):
                assert view_fraction(ctr, tuple(r["roi"])) <= OUT_OF_VIEW, (r["id"], act)
    assert IN_VIEW > OUT_OF_VIEW


def test_frollard_windows():
    ann = load_yaml("frollard.yaml")
    ev = ann["events"]
    assert ev["theft"]["start_ms"] == ev["picks_up"]["start_ms"] and ev["theft"]["end_ms"] == ev["leaves_with_box"]["end_ms"]
    wins = ann["windows"]
    assert 15_000 <= wins[0]["dur_ms"] <= 20_000
    assert [b["start_ms"] - a["start_ms"] for a, b in zip(wins, wins[1:])] == [ann["window"]["stride_ms"]] * (len(wins) - 1)
    for w in wins:
        inside = w["start_ms"] <= ev["theft"]["start_ms"] and ev["theft"]["end_ms"] <= w["start_ms"] + w["dur_ms"]
        assert (w["label"] == "pos") == inside or w["label"] == "excluded"
        assert w["start_ms"] + w["dur_ms"] <= ann["video"]["duration_ms"]
    assert sum(w["label"] == "pos" for w in wins) >= 2 and sum(w["label"] == "neg" for w in wins) >= 8


def test_manifest_is_reproducible_from_seed_0(manifest):
    """Rebuilding with the default seed gives exactly the committed manifest (needs the data dir; otherwise skipped)."""
    import json

    from eval.data import windows

    if not paths.annotation_dir().is_dir():
        pytest.skip("annotations not available")
    rows, _ = windows.build(0)
    assert [json.loads(json.dumps(r)) for r in rows] == manifest
