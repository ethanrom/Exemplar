from collections import Counter

import pytest

from eval.data import splits as S
from eval.data.config import SPLITS


def _videos():
    out = []
    for cam, n in (("G1", 4), ("G2", 3), ("G3", 5), ("G4", 4)):
        for i in range(n):
            out.append({"stem": f"2018-03-0{i + 1}.10-00-00.10-05-00.school.{cam}", "camera": cam,
                        "instances": {"a": (i * 7 + len(cam)) % 5 + 1, "b": (i * 3) % 4}})
    return out


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_no_video_in_two_splits_and_every_video_assigned(seed):
    vids = _videos()
    assign = S.assign_splits(vids, seed, tries=200)
    assert set(assign) == {v["stem"] for v in vids}
    assert set(assign.values()) <= set(SPLITS)  # a dict maps a video to exactly one split


def test_every_camera_has_train_and_heldout_when_possible():
    vids = _videos()
    assign = S.assign_splits(vids, 0, tries=200)
    per_cam = {}
    for v in vids:
        per_cam.setdefault(v["camera"], Counter())[assign[v["stem"]]] += 1
    for cam, c in per_cam.items():
        assert c["train"] >= 1, cam
        assert c["calib"] >= 1 and c["test"] >= 1, cam  # every camera here has >= 3 videos


def test_deterministic_for_a_seed():
    vids = _videos()
    assert S.assign_splits(vids, 5, tries=100) == S.assign_splits(vids, 5, tries=100)


def test_allocate_small_cameras():
    assert S._allocate(1, S.FRACTIONS)["train"] == 1
    a = S._allocate(2, S.FRACTIONS)
    assert sum(a.values()) == 2 and a["train"] >= 1
    assert S._allocate(3, S.FRACTIONS) == {"train": 1, "calib": 1, "test": 1}
