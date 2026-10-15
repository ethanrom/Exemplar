"""trace_probe: AUC arithmetic and feature counts on fixture traces."""
import pytest

from eval import trace_probe
from fakes import make_trace


def test_auc_hand_values():
    assert trace_probe.auc([3, 4], [1, 2]) == 1.0
    assert trace_probe.auc([1, 2], [3, 4]) == 0.0
    assert trace_probe.auc([1, 2], [1, 2]) == pytest.approx(0.5)
    assert trace_probe.auc([2], [2]) == 0.5
    assert trace_probe.auc([], [1]) != trace_probe.auc([], [1])        # NaN without positives


def test_features_count_facts_and_entities():
    t = make_trace("x", "pos")                                           # 3 frames, in_zone(p1, door) each, one person
    f = trace_probe.FEATURES
    assert f["n_door_zone"](t) == 3 and f["n_person"](t) == 1 and f["n_vehicle"](t) == 0 and f["n_facts"](t) == 3
    assert f["n_enters_leaves"](t) == 0 and f["n_entities"](t) == 1
    assert f["n_door_zone"](make_trace("y", "neg")) == 0
