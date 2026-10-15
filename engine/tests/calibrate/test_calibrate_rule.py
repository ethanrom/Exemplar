"""calibrate(rule, random_labelled, alpha) on the fixture traces: scoring, provenance, recall, API shape."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from exemplar.calibrate import ProvenanceError, calibrate
from exemplar.contracts.labels import Label
from exemplar.contracts.trace import Trace
from exemplar.dsl import UnboundHoleError, parse, robustness

FIXTURES = Path(__file__).parents[1] / "fixtures" / "traces"
API = Path(__file__).parents[2] / "exemplar" / "contracts" / "api.yaml"

THEFT = parse("exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)")
NEGATIVES = ["delivery_a", "delivery_b", "unattended_package", "vehicle_dwell_dock", "vehicle_passby", "birds_feeder",
             "empty_scene", "perception_failed", "visitor_no_ring", "visitor_rings"]


def load(name: str) -> Trace:
    return Trace.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def lab(name: str, value: str, provenance: str = "random") -> Label:
    return Label(concept_id="theft", clip_id=name, value=value, provenance=provenance)


def pairs(neg=NEGATIVES, pos=("theft_a", "theft_b"), provenance="random"):
    return [(load(n), lab(n, "neg", provenance)) for n in neg] + [(load(n), lab(n, "pos", provenance)) for n in pos]


def test_calibrate_scores_with_the_dsl_evaluator_and_fills_recall():
    cal = calibrate(THEFT, pairs(), 0.1)
    assert (cal.n_random_neg, cal.n_random_pos, cal.k, cal.guarantee, cal.message) == (10, 2, 10, True, None)
    scores = sorted(robustness(THEFT, load(n)) for n in NEGATIVES)
    assert cal.tau_alpha == scores[9] == pytest.approx(-0.45)          # delivery_a / delivery_b sit at -0.45
    assert cal.tau == 0.0                                              # floored: the rule must hold to fire
    assert cal.recall == 1.0 and cal.recall_ci95[1] == 1.0 and 0.15 < cal.recall_ci95[0] < 0.2   # 2/2: 0.158
    assert cal.delta == 0.05                                           # n=10 >= 8, IQR 0.05 -> 0.025 -> clamped to 0.05


def test_calibrate_without_enough_negatives_reports_the_message():
    cal = calibrate(THEFT, pairs(neg=NEGATIVES[:4]), 0.1)
    assert not cal.guarantee and cal.tau == 0.0 and cal.k is None
    assert cal.message == "guarantee needs ≥ 9 random negatives (have 4)"
    assert cal.n_random_neg == 4 and cal.n_random_pos == 2 and cal.recall == 1.0     # recall still reported at tau 0


def test_calibrate_recall_counts_misses():
    cal = calibrate(THEFT, pairs(neg=NEGATIVES[:-1], pos=("theft_a", "visitor_rings")), 0.1)   # a missed positive
    assert cal.recall == 0.5 and cal.recall_ci95[0] < 0.5 < cal.recall_ci95[1]


def test_calibrate_no_positives():
    cal = calibrate(THEFT, pairs(pos=()), 0.1)
    assert cal.n_random_pos == 0 and cal.recall is None and cal.recall_ci95 is None


@pytest.mark.parametrize("bad", ["example", "active"])
def test_calibrate_rejects_non_random_provenance(bad):
    mixed = pairs()
    mixed[3] = (load(NEGATIVES[3]), lab(NEGATIVES[3], "neg", provenance=bad))
    with pytest.raises(ProvenanceError, match=NEGATIVES[3]):
        calibrate(THEFT, mixed, 0.1)
    assert issubclass(ProvenanceError, ValueError)


def test_calibrate_rejects_mispaired_or_duplicate_clips():
    with pytest.raises(ValueError, match="paired"):
        calibrate(THEFT, [(load("delivery_a"), lab("delivery_b", "neg"))], 0.1)
    with pytest.raises(ValueError, match="twice"):
        calibrate(THEFT, [(load("delivery_a"), lab("delivery_a", "neg"))] * 2, 0.1)


def test_calibrate_needs_a_closed_rule():
    sketch = parse("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] carrying(p, k)")
    with pytest.raises(UnboundHoleError):
        calibrate(sketch, pairs(), 0.1)


def test_calibrate_tau_changes_with_negatives_that_match():
    """If random negatives include clips the rule matches (false alarms), tau rises above 0 and recall drops."""
    neg = NEGATIVES + ["theft_b"]                       # theft_b scores 0.30 but is labelled negative here
    cal = calibrate(THEFT, pairs(neg=neg, pos=("theft_a",)), 0.1)
    # n = 11 -> k = ceil(12 * 0.9) = 11 = max score = 0.30
    assert cal.k == 11 and cal.tau == pytest.approx(0.30)
    assert cal.recall == 1.0                            # theft_a scores 0.45 > 0.30


def test_calibration_api_payload_validates():
    spec = yaml.safe_load(API.read_text(encoding="utf-8"))
    v = Draft202012Validator(spec["components"]["schemas"]["Calibration"])
    for cal in (calibrate(THEFT, pairs(), 0.1), calibrate(THEFT, pairs(neg=NEGATIVES[:3], pos=()), 0.1)):
        v.validate(cal.to_api())
