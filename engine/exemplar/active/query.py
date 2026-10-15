"""Query selection: ask about the clip the committee is most split on (PLAN.md §2.4).

    p(u) = sum of member weights whose rule matches u (score > 0)      # "your rules disagree on this one"

* The pick minimises |p(u) - 0.5|.
* **Near-ties** (|p-distance| within `TIE_EPS` = 0.05 of the best) are broken by *diversity*: among the
  near-tied clips take the one whose committee score vector is farthest from every clip already labelled
  (and, for k > 1, from the clips picked earlier in this call). The vector of u is the member scores
  (S_1(u), ..., S_M(u)) of the robustness; the distance is the member-weight-weighted Euclidean distance
  sqrt(sum_i w_i (S_i(u) - S_i(l))^2) and a clip's diversity is its minimum distance to the reference set
  (farthest-point rule). Without any reference clip the closest-to-0.5 clip wins. Remaining ties go to
  the smaller |p - 0.5|, then the clip id, so the choice is deterministic.
* A labelled clip is never returned: ``labelled`` traces and ``exclude`` ids are removed first.
* Members whose weight is below `MIN_WEIGHT` are not evaluated (each is below 1e-7, so M of them move p by under M * 1e-7).
* p of exactly 0 or 1 means the committee is unanimous on every clip; the caller decides whether that is
  worth a question.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Optional, Sequence, Union

import numpy as np

from exemplar.contracts.trace import Trace
from exemplar.dsl import PreparedTrace, compile_rule, prepare

from .committee import Committee

TIE_EPS = 0.05
MIN_WEIGHT = 1e-7


@dataclass(frozen=True)
class Question:
    clip_id: str
    p: float                     # weighted fraction of committee members that match the clip
    committee_size: int

    def to_api(self, *, concept_id: str, event: Optional[dict] = None) -> dict:
        """api.yaml `Question`."""
        out: dict = {"concept_id": concept_id, "clip_id": self.clip_id, "p": float(self.p),
                     "committee_size": int(self.committee_size)}
        if event is not None:
            out["event"] = event
        return out


def committee_scores(committee: Committee, traces: Sequence[Union[Trace, PreparedTrace]]
                     ) -> tuple[np.ndarray, np.ndarray]:
    """(S, w): S[i, j] = robustness of member i on trace j, w = renormalised weights of the evaluated members."""
    kept = [(r, w) for r, w in committee.members if w >= MIN_WEIGHT]
    preps = [prepare(t) for t in traces]
    S = np.empty((len(kept), len(preps)))
    for i, (rule, _) in enumerate(kept):
        cr = compile_rule(rule)
        for j, pt in enumerate(preps):
            S[i, j] = cr.score(pt)
    w = np.array([w for _, w in kept], dtype=np.float64)
    return S, (w / w.sum() if len(w) else w)


def select_query(committee: Committee, unlabelled: Sequence[Union[Trace, PreparedTrace]], *, k: int = 1,
                 labelled: Sequence[Union[Trace, PreparedTrace]] = (), exclude: Collection[str] = ()) -> list[Question]:
    """The ``k`` most informative clips to ask the user about, in the order to ask them (see module docstring).

    ``labelled`` are the clips that already have a label (excluded, and the reference set for diversity);
    ``exclude`` adds more clip ids to skip. Returns [] for an empty committee or nothing left to ask.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    ref_traces = [prepare(t) for t in labelled]
    skip = set(exclude) | {t.trace.clip_id for t in ref_traces}
    cands: list[PreparedTrace] = []
    seen: set[str] = set()
    for t in unlabelled:
        pt = prepare(t)
        cid = pt.trace.clip_id
        if cid not in skip and cid not in seen:
            seen.add(cid)
            cands.append(pt)
    if not committee.members or not cands:
        return []

    S, w = committee_scores(committee, ref_traces + cands)
    S_ref, S_cand = S[:, :len(ref_traces)], S[:, len(ref_traces):]
    p = w @ (S_cand > 0)
    gap = np.abs(p - 0.5)
    ids = [c.trace.clip_id for c in cands]
    refs = [S_ref[:, j] for j in range(S_ref.shape[1])]

    def diversity(j: int) -> float:
        return min(float(np.sqrt((w * (S_cand[:, j] - r) ** 2).sum())) for r in refs)

    remaining = list(range(len(cands)))
    out: list[Question] = []
    while remaining and len(out) < k:
        best_gap = min(gap[j] for j in remaining)
        near = [j for j in remaining if gap[j] <= best_gap + TIE_EPS + 1e-12]
        if refs:
            pick = min(near, key=lambda j: (-round(diversity(j), 12), gap[j], ids[j]))
        else:
            pick = min(near, key=lambda j: (gap[j], ids[j]))
        out.append(Question(clip_id=ids[pick], p=float(p[pick]), committee_size=len(committee.members)))
        refs.append(S_cand[:, pick])
        remaining.remove(pick)
    return out
