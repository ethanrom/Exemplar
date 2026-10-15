"""Self-consistency merge of several perception samples of the same frames (strong mode, `samples=2`)."""
from __future__ import annotations

from collections import Counter
from typing import Sequence

from exemplar.contracts.trace import Entity, Fact, Frame, Trace

_RANK = {"low": 0, "med": 1, "high": 2}


def merge_traces(traces: Sequence[Trace]) -> tuple[Trace, Counter]:
    """Merge k >= 1 samples of the SAME sampled frames into one trace.  Returns (trace, stats).

    Merge rule (documented contract of `perceive(..., samples=k)`):

    * **Facts** are identified by ``(frame index, pred, args)``.  A fact asserted in *all* k samples keeps the
      **lowest** of the k confidences; a fact asserted in only *some* samples is kept at **low** (whatever
      confidence the sample that asserted it gave).  Nothing is dropped, so disagreement shows up as weak
      evidence (signal 0.6, i.e. barely above the 0.5 threshold) rather than as a missing fact.
    * **Entities** are the **union by id**, in order of first appearance; ``attrs`` are unioned (order
      preserved).  Ids are *not* re-aligned across samples: ``p1`` in sample 2 is assumed to be ``p1`` of sample
      1 (models number entities by order of appearance, so this holds for the usual one-or-two-actor scenes).
      If the same id has a different ``type`` in a later sample, the first sample's entity wins and the later
      sample's facts that mention that id are discarded (counted in ``stats["facts_type_conflict"]``).
    * ``summary``, ``context``, ``status`` come from the first sample; ``perception.samples`` becomes k and the
      token counters are summed.

    stats: ``facts_both`` (in every sample), ``facts_partial`` (kept at low), ``facts_type_conflict``.
    """
    if not traces:
        raise ValueError("nothing to merge")
    first = traces[0]
    if len(traces) == 1:
        return first, Counter()
    ts = [f.t_ms for f in first.frames]
    for t in traces[1:]:
        if [f.t_ms for f in t.frames] != ts or t.clip_id != first.clip_id:
            raise ValueError("samples must come from the same sampled frames")
    stats: Counter = Counter()

    ents: dict[str, Entity] = {}
    for t in traces:
        for e in t.entities:
            cur = ents.get(e.id)
            if cur is None:
                ents[e.id] = e
            elif cur.type == e.type:
                merged = tuple(dict.fromkeys(cur.attrs + e.attrs))
                if merged != cur.attrs:
                    ents[e.id] = Entity(id=cur.id, type=cur.type, attrs=merged)
    conflicting = [{e.id for e in t.entities if ents[e.id].type != e.type} for t in traces]

    frames: list[Frame] = []
    for i, t_ms in enumerate(ts):
        seen: dict[tuple[str, tuple[str, ...]], list[str]] = {}
        for si, t in enumerate(traces):
            for f in t.frames[i].facts:
                if conflicting[si] & set(f.args):
                    stats["facts_type_conflict"] += 1
                    continue
                seen.setdefault((f.pred, f.args), []).append(f.conf)
        facts = []
        for (pred, args), confs in seen.items():
            if len(confs) == len(traces):
                conf = min(confs, key=_RANK.__getitem__)
                stats["facts_both"] += 1
            else:
                conf = "low"
                stats["facts_partial"] += 1
            facts.append(Fact(pred=pred, args=args, conf=conf))
        frames.append(Frame(t_ms=t_ms, facts=tuple(facts)))

    used = {a for fr in frames for f in fr.facts for a in f.args}
    meta = first.perception.model_copy(update={
        "samples": len(traces), "tokens_in": sum(t.perception.tokens_in for t in traces),
        "tokens_out": sum(t.perception.tokens_out for t in traces),
        "latency_ms": sum(t.perception.latency_ms for t in traces)}) if first.perception else None
    merged = first.model_copy(update={"entities": tuple(e for e in ents.values() if e.id in used),
                                      "frames": tuple(frames), "perception": meta})
    return Trace.model_validate(merged.model_dump()), stats
