"""Query-by-committee over the version space of rule hypotheses.

The CEGIS agent returns a few ranked candidates (sketch + solved holes). Each sketch has numeric holes
(window bounds, durations, hours); the labelled clips constrain them to a feasible region. The committee is
a weighted sample of closed rules from the union of those regions:

1. For each candidate, the feasible hole *box* comes from ``box_fn`` (default `exemplar.synth.hole_box`:
   Z3 min/max per hole with the candidate's satisfied set and margin fixed).
2. ``n_samples`` points are drawn uniformly in the box (seeded; hour holes uniformly over the integers) and
   kept only if the filled rule is consistent with every *satisfied* example under the NumPy evaluator
   (positives score > 0, negatives <= 0). The candidate's own solved point is always tried first.
3. **Fallback** (acceptance below `MIN_ACCEPTANCE` = 5%): the box is a bounding box, so a thin or diagonal
   feasible region is mostly missed by uniform sampling. A second batch of ``n_samples`` points is drawn in
   the box shrunk to `SHRINK` (25%) of its width around the candidate's own holes, and its consistent points
   are added. True Z3 blocking-clause sampling is not implemented; the
   shrunk box trades coverage of the version space for guaranteed non-emptiness around a known solution.
4. **Weights** are proportional to exp(-MDL / T) per candidate (T = ``mdl_temperature``, default 1, i.e.
   plain exp(-MDL)), spread evenly over the candidate's accepted points, then normalised with a stable
   softmax (max subtracted, so MDL values of any size neither overflow nor underflow to a zero sum).
   MDL gaps of a few bits already make the best candidate dominate; raise T to keep the others alive.
   The API layer passes T = 8 (`ApiConfig.committee_mdl_temperature`, the MDL cost of one hole): on the
   "package theft" concept T = 1 gave the top candidate weight 1.000 and no clip split the committee, T = 8
   gives it 0.76 and one clip splits it 15/85.

Everything is deterministic for a given ``seed`` (each candidate draws from its own child stream, so adding a
candidate does not change the samples of the others).

`exemplar.synth` is imported lazily, only when ``box_fn`` is not given.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional, Sequence

import numpy as np

from exemplar.contracts.dsl_ast import Hole, HourIn, Rule, fill_holes
from exemplar.contracts.dsl_ast import holes as ast_holes
from exemplar.dsl import DSLError, compile_rule, parse, prepare

if TYPE_CHECKING:       # not imported at module load
    from exemplar.synth import Candidate, Example

log = logging.getLogger("exemplar.active")

MIN_ACCEPTANCE = 0.05
SHRINK = 0.25

BoxFn = Callable[..., Mapping[str, tuple[float, float]]]


@dataclass(frozen=True)
class Committee:
    """Closed rules with normalised weights (sum to 1), plus per-candidate sampling diagnostics."""

    members: tuple[tuple[Rule, float], ...]
    diagnostics: tuple[dict, ...] = ()

    def __len__(self) -> int:
        return len(self.members)


# ---------------------------------------------------------------------------------------------- helpers
def _sketch_of(cand: "Candidate") -> Rule:
    """The candidate's sketch (with holes): parsed from ``sketch_text``; ``cand.rule`` is the closed rule."""
    text = getattr(cand, "sketch_text", None)
    if text:
        try:
            return parse(text)
        except DSLError as e:                                   # fall back to whatever rule we were given
            log.warning("candidate sketch_text does not parse (%s); using candidate.rule", e)
    return cand.rule


def _hour_holes(sketch: Rule) -> set[str]:
    return {h.name for c in sketch.when if isinstance(c, HourIn) for h in (c.h1, c.h2) if isinstance(h, Hole)}


def _sample(rng: np.random.Generator, names: Sequence[str], box: Mapping[str, tuple[float, float]],
            hours: set[str], n: int) -> list[dict[str, float]]:
    cols: dict[str, np.ndarray] = {}
    for name in names:
        lo, hi = box[name]
        if hi < lo:
            lo, hi = hi, lo
        if name in hours:
            a, b = math.ceil(lo - 1e-9), math.floor(hi + 1e-9)
            if b < a:                                             # no integer inside: take the nearest
                a = b = int(round((lo + hi) / 2))
            cols[name] = rng.integers(a, b + 1, size=n).astype(np.float64)
        else:
            cols[name] = rng.uniform(lo, hi, size=n)
    return [{name: float(cols[name][i]) for name in names} for i in range(n)]


def _consistent(cr, point: Mapping[str, float], examples: Sequence[tuple[str, bool, Any]]) -> bool:
    for _, positive, prep in examples:
        if (cr.score(prep, point) > 0) != positive:
            return False
    return True


def _shrunk(box: Mapping[str, tuple[float, float]], center: Mapping[str, float]) -> dict[str, tuple[float, float]]:
    out = {}
    for name, (lo, hi) in box.items():
        c = min(max(center[name], lo), hi)
        half = (hi - lo) * SHRINK / 2
        out[name] = (max(lo, c - half), min(hi, c + half))
    return out


def _candidate_points(idx: int, cand: "Candidate", sketch: Rule, examples: Sequence[Any], prepared: Sequence[tuple[str, bool, Any]],
                      box_fn: BoxFn, n_samples: int, seed: int, margin: Optional[float]
                      ) -> tuple[list[dict[str, float]], dict]:
    names = ast_holes(sketch)
    violated = set(cand.violated_clip_ids)
    satisfied = [e for e in prepared if e[0] not in violated]
    diag: dict[str, Any] = {"candidate": idx, "mdl": float(cand.mdl), "holes": list(names), "n_satisfied": len(satisfied),
                            "n_sampled": 0, "n_accepted": 0, "acceptance": None, "fallback": False}
    if not names:
        return [{}], diag
    cr = compile_rule(sketch)
    try:
        box = dict(box_fn(sketch, list(examples), satisfied=[e[0] for e in satisfied],
                          margin=float(cand.margin if margin is None else margin)))
    except Exception as e:                                        # a Z3 timeout must not take the question down
        log.warning("hole box failed for candidate %d (%s: %s); committee uses the candidate's own point", idx,
                    type(e).__name__, e)
        diag["box_error"] = f"{type(e).__name__}: {e}"
        box = {}
    own: dict[str, float] = {}
    for name in names:
        lo, hi = box.get(name, (None, None))
        v = cand.holes.get(name)
        if v is None:
            v = 0.0 if lo is None else (lo + hi) / 2
        own[name] = float(v)
        box.setdefault(name, (own[name], own[name]))
    diag["box"] = {k: (float(lo), float(hi)) for k, (lo, hi) in box.items() if k in names}

    rng = np.random.default_rng(np.random.SeedSequence([int(seed), idx]))
    hours = _hour_holes(sketch)
    points: list[dict[str, float]] = []
    own_ok = _consistent(cr, own, satisfied)
    if own_ok:
        points.append(own)

    cand_pts = _sample(rng, names, box, hours, n_samples)
    accepted = [p for p in cand_pts if _consistent(cr, p, satisfied)]
    diag["n_sampled"] = n_samples
    diag["acceptance"] = len(accepted) / n_samples
    if diag["acceptance"] < MIN_ACCEPTANCE:
        diag["fallback"] = True
        near = _sample(rng, names, _shrunk({k: box[k] for k in names}, own), hours, n_samples)
        extra = [p for p in near if _consistent(cr, p, satisfied)]
        diag["fallback_accepted"] = len(extra)
        accepted += extra
        diag["n_sampled"] += n_samples
    points += accepted
    diag["n_accepted"] = len(accepted)
    if not points:                                                # keep the candidate itself, flagged
        diag["inconsistent_candidate"] = True
        points = [own]
    return points, diag


# ---------------------------------------------------------------------------------------------- public
def build_committee(candidates: "Sequence[Candidate]", examples: "Sequence[Example]", *,
                    box_fn: Optional[BoxFn] = None, n_samples: int = 200, seed: int = 0,
                    box_margin: Optional[float] = None, mdl_temperature: float = 1.0) -> Committee:
    """Weighted sample of closed rules consistent with the labelled examples (see the module docstring).

    ``box_margin`` overrides the margin handed to ``box_fn`` (default: each candidate's own margin m*, which
    restricts sampling to the max-margin plateau; pass 0 to sample the whole sign-consistent version space).
    """
    if n_samples < 1:
        raise ValueError("n_samples must be >= 1")
    if mdl_temperature <= 0:
        raise ValueError("mdl_temperature must be > 0")
    if box_fn is None:
        from exemplar.synth import hole_box as box_fn          # lazy import
    prepared = [(ex.clip_id, bool(ex.positive), prepare(ex.trace)) for ex in examples]
    groups: list[tuple[float, list[Rule]]] = []
    diagnostics: list[dict] = []
    for idx, cand in enumerate(candidates):
        mdl = float(cand.mdl)
        if not math.isfinite(mdl):
            raise ValueError(f"candidate {idx} has a non-finite MDL")
        sketch = _sketch_of(cand)
        points, diag = _candidate_points(idx, cand, sketch, examples, prepared, box_fn, n_samples, seed, box_margin)
        rules = [fill_holes(sketch, p) if p else sketch for p in points]
        groups.append((-mdl / mdl_temperature - math.log(len(rules)), rules))
        diagnostics.append(diag)
    if not groups:
        return Committee(members=(), diagnostics=())
    top = max(lw for lw, _ in groups)
    raw = [(rule, math.exp(lw - top)) for lw, rules in groups for rule in rules]
    total = sum(w for _, w in raw)
    return Committee(members=tuple((rule, w / total) for rule, w in raw), diagnostics=tuple(diagnostics))
