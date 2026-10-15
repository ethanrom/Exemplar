"""Calibrating a closed rule on random-labelled clips (docs/DSL.md "Label provenance")."""
from __future__ import annotations

import dataclasses
from typing import Sequence, Union

from exemplar.contracts.dsl_ast import Rule
from exemplar.contracts.labels import Label
from exemplar.contracts.trace import Trace
from exemplar.dsl import PreparedTrace, compile_rule, prepare

from .conformal import Calibration, conformal_threshold, recall_ci


class ProvenanceError(ValueError):
    """A label that is not provenance ``random`` reached calibration (it would void the guarantee)."""


def calibrate(rule: Rule, random_labelled: Sequence[tuple[Union[Trace, PreparedTrace], Label]],
              alpha: float) -> Calibration:
    """Score ``rule`` on every (trace, label) pair, take tau from the negatives, recall from the positives.

    Every label must have provenance ``random``: clips the user picked as examples or the active learner
    picked are not exchangeable with deployment events, and ``random`` clips must also have been held out
    from synthesis. The rule must be closed (`UnboundHoleError` otherwise).
    """
    bad = [l.clip_id for _, l in random_labelled if l.provenance != "random"]
    if bad:
        raise ProvenanceError(
            f"calibration accepts only provenance='random' labels; got other provenance for clips {sorted(set(bad))}")
    seen: set[str] = set()
    for tr, lab in random_labelled:
        cid = prepare(tr).trace.clip_id
        if cid != lab.clip_id:
            raise ValueError(f"trace {cid!r} is paired with the label of clip {lab.clip_id!r}")
        if cid in seen:
            raise ValueError(f"clip {cid!r} appears twice in the calibration set")
        seen.add(cid)
    cr = compile_rule(rule)
    pos: list[float] = []
    neg: list[float] = []
    for tr, lab in random_labelled:
        (pos if lab.positive else neg).append(cr.score(prepare(tr)))
    cal = conformal_threshold(neg, alpha)
    recall, ci = recall_ci(pos, cal.tau)
    return dataclasses.replace(cal, n_random_pos=len(pos), recall=recall, recall_ci95=ci)
