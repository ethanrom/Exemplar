"""Trace: the symbolic output of perception for one clip.

Perception runs once per clip; everything downstream (synthesis, backtest, active learning,
calibration, monitor) reads only `Trace` objects.

Time is **integer milliseconds from clip start** (`Frame.t_ms`). Evaluators must compute window
offsets as `(t_ms[j] - t_ms[i]) / 1000` — one correctly-rounded division — never as a difference
of float seconds. This keeps the Z3 encoder and the NumPy evaluator in agreement when a solved
hole lands exactly on an observed gap (see docs/DSL.md, "Time is integer milliseconds").
"""
from __future__ import annotations

import itertools
from typing import Literal, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ontology import (ABSENT_VALUE, CONF_VALUE, PREDICATES, VAR_TYPES, ZONES, Conf, EntityType,
                       SubType, kind_admits)

MAX_FRAMES = 32          # escalation mode allows 32; fast mode samples ≤ 24
SCHEMA_VERSION = 1


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Entity(_Frozen):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="stable across frames, e.g. p1, v1, k1")
    type: EntityType
    attrs: tuple[str, ...] = ()        # clip-level open-vocab labels, e.g. delivery_uniform, hi_vis


class Fact(_Frozen):
    pred: str
    args: tuple[str, ...]
    conf: Conf


class Frame(_Frozen):
    t_ms: int = Field(ge=0, description="ms from clip start")
    facts: tuple[Fact, ...] = ()


class TraceContext(_Frozen):
    """Context signals. Context atoms in rules read these; all optional."""
    sub_type: Optional[SubType] = None
    event_kind: Optional[Literal["motion", "ding", "on_demand", "live", "upload"]] = None
    local_hour: Optional[int] = Field(default=None, ge=0, le=23)
    weekday: Optional[int] = Field(default=None, ge=0, le=6, description="0 = Monday")
    device_id: Optional[str] = None
    started_at_ms: Optional[int] = Field(default=None, description="epoch ms of clip start")


class PerceptionMeta(_Frozen):
    mode: Literal["fast", "strong", "fixture", "manual"]
    model_alias: Optional[str] = None  # alias only — never a model ID/ARN
    n_frames: int = 0
    samples: int = 1                   # self-consistency samples averaged (strong mode)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    cache_key: Optional[str] = None    # hash of clip identity + window + sampling params + prompt version + mode (never clip bytes)


class Trace(_Frozen):
    schema_version: Literal[1] = SCHEMA_VERSION
    clip_id: str
    source: Literal["ring", "ring_live", "upload", "meva", "fixture"]
    duration_ms: int = Field(ge=0)
    status: Literal["ok", "perception_failed"] = "ok"
    error: Optional[str] = None
    entities: tuple[Entity, ...] = ()
    frames: tuple[Frame, ...] = ()
    context: TraceContext = TraceContext()
    summary: str = ""
    perception: Optional[PerceptionMeta] = None

    # ------------------------------------------------------------------ validation
    @model_validator(mode="after")
    def _check(self) -> "Trace":
        errs = trace_errors(self)
        if errs:
            raise ValueError("; ".join(errs[:10]))
        return self

    # ------------------------------------------------------------------ helpers
    @property
    def t_ms(self) -> np.ndarray:
        return np.array([f.t_ms for f in self.frames], dtype=np.int64)

    def entity(self, eid: str) -> Optional[Entity]:
        return next((e for e in self.entities if e.id == eid), None)

    def signal(self, pred: str, args: tuple[str, ...]) -> np.ndarray:
        """s_pred(args)(t_i) for every frame, as float64.

        - asserted → CONF_VALUE[conf] (max over duplicate assertions in a frame); else ABSENT_VALUE.
        - `present(e)` is also implied by any other fact mentioning `e` in that frame
          (value = max conf of those facts), so perception need not repeat it.
        - `attr(e, L)` with L in `e.attrs` (clip-level) is at least CONF_VALUE["med"] in every frame.
        """
        n = len(self.frames)
        s = np.full(n, ABSENT_VALUE)
        floor = ABSENT_VALUE
        if pred == "attr" and len(args) == 2:
            ent = self.entity(args[0])
            if ent is not None and args[1] in ent.attrs:
                floor = CONF_VALUE["med"]
        for i, fr in enumerate(self.frames):
            for f in fr.facts:
                if f.pred == pred and f.args == args:
                    s[i] = max(s[i], CONF_VALUE[f.conf])
                elif pred == "present" and len(args) == 1 and args[0] in f.args:
                    s[i] = max(s[i], CONF_VALUE[f.conf])
        return np.maximum(s, floor)

    def bindings(self, var_types: tuple[str, ...]) -> list[tuple[str, ...]]:
        """All type-correct assignments of distinct entities to variables of the given DSL types."""
        pools = [[e.id for e in self.entities if e.type in VAR_TYPES[vt]] for vt in var_types]
        return [b for b in itertools.product(*pools) if len(set(b)) == len(b)]


def trace_errors(tr: Trace) -> list[str]:
    """Schema + ontology errors. Empty list means valid. Used for the perception retry message."""
    errs: list[str] = []
    ids = [e.id for e in tr.entities]
    if len(ids) != len(set(ids)):
        errs.append("entity ids must be unique")
    types = {e.id: e.type for e in tr.entities}
    if tr.status == "perception_failed":
        return errs
    if len(tr.frames) > MAX_FRAMES:
        errs.append(f"at most {MAX_FRAMES} frames")
    ts = [f.t_ms for f in tr.frames]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        errs.append("frame times must be strictly increasing")
    if ts and ts[-1] > tr.duration_ms:
        errs.append("frame time beyond duration_ms")
    for i, fr in enumerate(tr.frames):
        for f in fr.facts:
            kinds = PREDICATES.get(f.pred)
            if kinds is None:
                errs.append(f"frame {i}: unknown predicate {f.pred!r}")
                continue
            if len(f.args) != len(kinds):
                errs.append(f"frame {i}: {f.pred} takes {len(kinds)} args, got {len(f.args)}")
                continue
            for k, a in zip(kinds, f.args):
                if k == "Zone":
                    ok = a in ZONES
                elif k == "Label":
                    ok = bool(a)
                else:
                    ok = a in types and kind_admits(k, types[a])
                if not ok:
                    errs.append(f"frame {i}: {f.pred}{f.args}: {a!r} is not a valid {k}")
    return errs
