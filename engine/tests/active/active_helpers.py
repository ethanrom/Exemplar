"""Helpers for the active-learning tests: local stand-ins for synth's `Candidate` / `Example` (same fields),
a brute-force `box_fn`, and tiny synthetic traces."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from exemplar.contracts.dsl_ast import Rule, holes as ast_holes
from exemplar.contracts.trace import Entity, Fact, Frame, Trace
from exemplar.dsl import compile_rule, parse, prepare, to_english, to_text

FIXTURES = Path(__file__).parents[1] / "fixtures" / "traces"

THEN_SKETCH = ("exists p: Person, k: Package: picks_up(p, k) then[0, ?b] carrying(p, k) "
               "and not attr(p, delivery_uniform)")
EVENTUALLY_SKETCH = "exists p: Person, k: Package: eventually[0, ?b] carrying(p, k) and not attr(p, delivery_uniform)"


def load(name: str) -> Trace:
    return Trace.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Example:                      # = exemplar.synth.Example
    trace: Any
    positive: bool
    weight: float
    clip_id: str


@dataclass(frozen=True)
class Candidate:                    # = exemplar.synth.Candidate (the fields E reads)
    sketch_text: str
    dsl_text: str
    english: str
    rule: Rule
    holes: dict
    margin: float
    mdl: float
    violated_clip_ids: tuple = ()


def example(trace: Trace, positive: bool, weight: float = 3.0) -> Example:
    cid = trace.clip_id if hasattr(trace, "clip_id") else trace.trace.clip_id
    return Example(trace=trace, positive=positive, weight=weight, clip_id=cid)


def candidate(sketch_text: str, holes: dict, *, mdl: float = 20.0, margin: float = 0.45, violated=()) -> Candidate:
    from exemplar.contracts.dsl_ast import fill_holes
    closed = fill_holes(parse(sketch_text), holes)
    return Candidate(sketch_text=sketch_text, dsl_text=to_text(closed), english=to_english(closed), rule=closed,
                     holes=dict(holes), margin=margin, mdl=mdl, violated_clip_ids=tuple(violated))


def gap_trace(clip_id: str, gap_s: float, *, attrs=("hoodie",)) -> Trace:
    """A person picks up a package at 4 s and is carrying it `gap_s` later (so `picks_up then[0,b] carrying`
    matches iff b >= gap_s). Frames: 0, 4, 4+gap, 4+gap+4 seconds."""
    t_pick, t_carry = 4000, 4000 + int(round(gap_s * 1000))
    frames = (
        Frame(t_ms=0, facts=(Fact(pred="in_zone", args=("k1", "porch"), conf="high"),)),
        Frame(t_ms=t_pick, facts=(Fact(pred="picks_up", args=("p1", "k1"), conf="high"),)),
        Frame(t_ms=t_carry, facts=(Fact(pred="carrying", args=("p1", "k1"), conf="high"),)),
        Frame(t_ms=t_carry + 4000, facts=()),
    )
    return Trace(clip_id=clip_id, source="fixture", duration_ms=t_carry + 4000,
                 entities=(Entity(id="p1", type="person", attrs=tuple(attrs)), Entity(id="k1", type="package")),
                 frames=frames)


def present_trace(clip_id: str, *types: str) -> Trace:
    """One frame with `present` for one entity of each given type (ids v1, k1, p1 by type)."""
    ids = {"vehicle": "v1", "package": "k1", "person": "p1", "animal": "a1", "object": "o1"}
    ents = tuple(Entity(id=ids[t], type=t) for t in types)
    fr = (Frame(t_ms=0, facts=()), Frame(t_ms=1000, facts=tuple(Fact(pred="present", args=(e.id,), conf="high") for e in ents)))
    return Trace(clip_id=clip_id, source="fixture", duration_ms=2000, entities=ents, frames=fr)


@dataclass
class GridBox:
    """Brute-force stand-in for `exemplar.synth.hole_box`: sweep the single hole on a grid, keep the values for
    which every *satisfied* example is sign-consistent, return the min/max. Records its calls."""
    lo: float = 0.0
    hi: float = 24.0
    step: float = 0.5
    calls: list = field(default_factory=list)

    def __call__(self, sketch: Rule, examples: Sequence[Example], *, satisfied: Sequence[str], margin: float,
                 timeout_s: float = 10.0) -> dict:
        self.calls.append({"satisfied": tuple(satisfied), "margin": margin})
        (name,) = ast_holes(sketch)
        cr = compile_rule(sketch)
        sat = [e for e in examples if e.clip_id in set(satisfied)]
        ok = []
        x = self.lo
        while x <= self.hi + 1e-9:
            if all((cr.score(prepare(e.trace), {name: x}) > 0) == e.positive for e in sat):
                ok.append(x)
            x += self.step
        return {name: (min(ok), max(ok))}
