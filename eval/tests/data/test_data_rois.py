import numpy as np
import pytest

from eval.data import rois as R
from eval.data.config import load_yaml


def _inst(concept, cx, cy, n=6, spread=20):
    rng = np.random.default_rng(int(cx * 7 + cy))
    return concept, np.stack([cx + rng.normal(0, spread, n), cy + rng.normal(0, spread, n)], axis=1)


def test_choose_roi_is_16_9_even_inside_frame():
    insts = [_inst("a", 1700, 900), _inst("a", 1750, 950), _inst("b", 100, 100)]
    for fw, fh in ((1920, 1080), (1920, 1072)):
        x, y, w, h = R.choose_roi(insts, fw, fh)
        assert w * 9 == h * 16 and w % 32 == 0 and x % 2 == 0 and y % 2 == 0
        assert 0 <= x and x + w <= fw and 0 <= y and y + h <= fh


def test_choose_roi_covers_a_cluster_of_whole_instances():
    dense = [_inst("a", 1500 + 5 * i, 800) for i in range(10)]
    roi = R.choose_roi(dense, 1920, 1080)
    assert all(R.view_fraction(c, roi) >= R.IN_VIEW for _, c in dense)


def test_choose_roi_balances_concepts():
    # 10 instances of concept a at the left, 10 of concept b at the right but concept b is rare overall
    left = [_inst("a", 300, 300) for _ in range(10)]
    right = [_inst("b", 1700, 800)]
    x, y, w, h = R.choose_roi(left + right, 1920, 1080)
    # both clusters are too far apart for one 960 px crop; the concept-balanced weight of the lone b instance (0.5)
    # equals all of concept a (0.5), so the tie goes to the centroid of the maximisers, never to an empty region
    covered = [R.view_fraction(c, (x, y, w, h)) >= R.IN_VIEW for _, c in left + right]
    assert any(covered)


def test_choose_roi_no_data_is_centred():
    x, y, w, h = R.choose_roi([], 1920, 1080)
    assert (w, h) == (960, 540) and x == 480 and y == 270


def test_view_fraction():
    c = np.array([[10, 10], [500, 500], [2000, 10]])
    assert R.view_fraction(c, (0, 0, 960, 540)) == pytest.approx(2 / 3)
    assert R.view_fraction(np.zeros((0, 2)), (0, 0, 10, 10)) == 0.0


def test_committed_rois_are_valid():
    try:
        cams = load_yaml("rois.yaml")["cameras"]
    except FileNotFoundError:
        pytest.skip("rois.yaml not generated yet")
    assert len(cams) >= 3
    for cam, r in cams.items():
        (fw, fh), (x, y, w, h) = r["frame"], r["roi"]
        assert w * 9 == h * 16, cam
        assert 0 <= x and x + w <= fw and 0 <= y and y + h <= fh, cam
        assert x % 2 == 0 and y % 2 == 0 and w % 2 == 0 and h % 2 == 0, cam
