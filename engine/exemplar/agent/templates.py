"""Deterministic sketch proposer: a small library of templates over the facts seen in the positive examples.

Used (a) in tests, (b) as the offline fallback when Bedrock is unavailable, and (c) to back-fill diversity when the LLM
proposes fewer than K workable sketches.  No LLM, no randomness: the same examples always give the same sketch order.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..contracts.ontology import PREDICATES
from ..dsl import compile_rule, parse
from ..synth import Example

if TYPE_CHECKING:  # pragma: no cover
    from .cegis import RoundContext

_VAR_BY_TYPE = {"person": "p", "package": "k", "vehicle": "v", "animal": "a", "object": "o"}
_VARTYPE = {"person": "Person", "package": "Package", "vehicle": "Vehicle", "animal": "Animal", "object": "Object"}
_STATE_PREDS = {"in_zone", "near", "present", "carrying", "facing_camera", "attr"}


@dataclass(frozen=True)
class AtomSpec:
    """An atom with entity arguments abstracted to typed variables: pred(p, k) / in_zone(k, steps) / attr(p, hoodie)."""
    pred: str
    args: tuple[str, ...]                     # variable names or literals
    vars: tuple[tuple[str, str], ...]         # ((name, DSL type), ...) used by the atom

    @property
    def text(self) -> str:
        return f"{self.pred}({', '.join(self.args)})"


def _trace(e: Example):
    t = e.trace
    return t.trace if hasattr(t, "trace") else t


def _specs(ex: Example) -> set[AtomSpec]:
    tr = _trace(ex)
    types = {e.id: e.type for e in tr.entities}
    out: set[AtomSpec] = set()

    def abstract(pred: str, args: tuple[str, ...]):
        kinds = PREDICATES.get(pred)
        if kinds is None or len(kinds) != len(args):
            return None
        seen: dict[str, str] = {}
        names: list[str] = []
        used: list[tuple[str, str]] = []
        for kind, a in zip(kinds, args):
            if kind in ("Zone", "Label"):
                names.append(a)
                continue
            t = types.get(a)
            if t is None:
                return None
            if a not in seen:
                base = _VAR_BY_TYPE[t]
                nm = base if base not in {n for n, _ in used} else base + "2"
                seen[a] = nm
                used.append((nm, _VARTYPE[t]))
            names.append(seen[a])
        return AtomSpec(pred, tuple(names), tuple(used))

    for fr in tr.frames:
        for f in fr.facts:
            s = abstract(f.pred, f.args)
            if s is not None:
                out.add(s)
    for e in tr.entities:
        for label in e.attrs:
            s = abstract("attr", (e.id, label))
            if s is not None:
                out.add(s)
    return out


def _rule_text(vars_: list[tuple[str, str]], body: str) -> str:
    decl = ", ".join(f"{n}: {t}" for n, t in vars_)
    return f"exists {decl}: {body}"


def _merge(*specs: AtomSpec) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for s in specs:
        for v in s.vars:
            if v not in out:
                out.append(v)
    return out


def _coverage(spec: AtomSpec, examples: list[Example]) -> tuple[float, float]:
    """(fraction of positives, fraction of negatives) in which the atom is true at some moment."""
    rule = parse(_rule_text(list(spec.vars), f"eventually[0, 1000] {spec.text}"))
    cr = compile_rule(rule)
    pos = [cr.score(e.trace) > 0 for e in examples if e.positive]
    neg = [cr.score(e.trace) > 0 for e in examples if not e.positive]
    return (sum(pos) / len(pos) if pos else 0.0, sum(neg) / len(neg) if neg else 0.0)


def build_templates(examples: list[Example], *, max_atoms: int = 6) -> list[str]:
    """Sketch texts, simplest first."""
    positives = [e for e in examples if e.positive]
    if not positives:
        return []
    cand = sorted(set().union(*(_specs(e) for e in positives)), key=lambda s: s.text)
    scored = []
    for s in cand:
        if s.pred == "present":
            continue
        cp, cn = _coverage(s, examples)
        if cp > 0:
            scored.append((cp - cn, cp, s))
    scored.sort(key=lambda t: (-t[0], -t[1], t[2].text))
    atoms = [s for _, _, s in scored[:max_atoms]]
    # attribute labels that only the negatives' persons carry: "not attr(p, label)" refinements
    pos_labels = {l for e in positives for en in _trace(e).entities for l in en.attrs}
    neg_labels = sorted({l for e in examples if not e.positive for en in _trace(e).entities if en.type == "person"
                         for l in en.attrs} - pos_labels)

    out: list[tuple[int, int, str]] = []                    # (nodes, holes, text)

    def add(vars_: list[tuple[str, str]], body: str, nodes: int, holes: int) -> None:
        out.append((nodes, holes, _rule_text(vars_, body)))

    for a in atoms:
        add(list(a.vars), f"eventually[0, ?b] {a.text}", 2, 1)
        if a.pred in _STATE_PREDS:
            add(list(a.vars), f"holds_for >= ?d {a.text}", 2, 1)
    for a, b in itertools.permutations(atoms, 2):
        if a.pred in ("present",) or b.pred in ("present",):
            continue
        add(_merge(a, b), f"{a.text} then[?a, ?b] {b.text}", 3, 2)
    for a, b in itertools.combinations(atoms, 2):
        add(_merge(a, b), f"eventually[0, ?b] ({a.text} and {b.text})", 4, 1)
        add(_merge(a, b), f"eventually[0, ?b] {a.text} and eventually[0, ?c] {b.text}", 5, 2)
    for label in neg_labels:
        for a in atoms:
            persons = [n for n, t in a.vars if t == "Person"]
            if persons:
                add(list(a.vars), f"eventually[0, ?b] {a.text} and not attr({persons[0]}, {label})", 4, 1)
        for a, b in itertools.permutations(atoms, 2):
            persons = [n for n, t in _merge(a, b) if t == "Person"]
            if persons:
                add(_merge(a, b), f"{a.text} then[?a, ?b] {b.text} and not attr({persons[0]}, {label})", 5, 2)
    seen, texts = set(), []
    for _, _, t in sorted(out, key=lambda x: (x[0], x[1], x[2])):
        if t not in seen:
            seen.add(t)
            texts.append(t)
    return texts


class TemplateProposer:
    """Proposes the next `batch` unseen templates each round (default: K per round)."""

    name = "templates"

    def __init__(self, batch: int | None = None) -> None:
        self.batch = batch
        self._texts: list[str] | None = None

    def propose(self, ctx: "RoundContext") -> list[str]:
        if self._texts is None:
            self._texts = build_templates(ctx.examples)
        n = self.batch or ctx.k
        fresh: list[str] = []
        for t in self._texts:
            rule, _ = ctx.state.parse_sketch(t)
            if rule is None:
                continue
            from ..dsl import to_text
            if to_text(rule) in ctx.state.records:
                continue
            fresh.append(t)
            if len(fresh) >= n:
                break
        return fresh
