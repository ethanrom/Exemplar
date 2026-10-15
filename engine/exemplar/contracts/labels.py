"""Labels with provenance (see docs/DSL.md, "Label provenance").

A label is per (concept, clip): the same clip can be a positive for "package theft" and a negative
for "loitering". Provenance decides what a label may be used for, and that rule is what keeps the
conformal guarantee honest:

  provenance  | chosen by                       | synthesis | calibration / recall CI
  ------------|---------------------------------|-----------|------------------------
  example     | the user, as a teaching example | yes       | no
  active      | the active learner              | yes       | no  — not exchangeable with deployment
  random      | uniform sample of history       | no        | yes — must be held out from fitting

`random` labels are excluded from synthesis as well: conformal calibration needs scores from data
the rule was not fitted on, otherwise τ_α is biased low and the false-alarm bound is void.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Provenance = Literal["example", "active", "random"]
LabelValue = Literal["pos", "neg"]

WEIGHT_CONFIRMED = 3.0   # the user looked at this clip and chose the label
WEIGHT_BULK = 1.0        # bulk-negative / auto labels


class Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    concept_id: str
    clip_id: str
    value: LabelValue
    provenance: Provenance
    weight: float = Field(default=WEIGHT_CONFIRMED, gt=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def positive(self) -> bool:
        return self.value == "pos"


def for_synthesis(labels: list[Label]) -> list[Label]:
    return [l for l in labels if l.provenance in ("example", "active")]


def for_calibration(labels: list[Label]) -> list[Label]:
    return [l for l in labels if l.provenance == "random"]
