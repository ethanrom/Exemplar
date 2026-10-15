"""Conformal false-alarm calibration and recall CI.

    cal = calibrate(rule, [(trace, label), ...], alpha=0.1)     # labels must all be provenance 'random'
    fire = score > cal.tau                                       # P(false alarm) <= alpha when cal.guarantee
"""
from .conformal import (DEFAULT_DELTA, Calibration, conformal_rank, conformal_threshold, escalation_delta,
                        min_negatives, recall_ci)
from .rule import ProvenanceError, calibrate

__all__ = ["Calibration", "ProvenanceError", "DEFAULT_DELTA", "calibrate", "conformal_rank", "conformal_threshold",
           "escalation_delta", "min_negatives", "recall_ci"]
