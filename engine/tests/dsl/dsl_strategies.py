"""Hypothesis strategies: random valid traces and random well-typed rules over the fixture entity types."""
from __future__ import annotations

from hypothesis import strategies as st

from exemplar.contracts.dsl_ast import (Always, And, Atom, DeviceEq, Eventually, HoldsFor, Hole, HourIn, Not, Or,
                                        Rule, SubtypeEq, Then, VarDecl, children)
from exemplar.contracts.ontology import PREDICATES, SUB_TYPES, VAR_TYPES, ZONES, kind_admits
from exemplar.contracts.trace import Entity, Fact, Frame, Trace, TraceContext
from exemplar.dsl.util import normalize

LABELS = ("hoodie", "hi_vis", "delivery_uniform")
POOL = (("p1", "person"), ("p2", "person"), ("k1", "package"), ("k2", "object"), ("v1", "vehicle"),
        ("a1", "animal"))
VAR_NAMES = ("x", "y", "z")
CONFS = ("low", "med", "high")


# ------------------------------------------------------------------ traces
def _candidate_facts(entities: list[Entity]) -> list[tuple[str, tuple[str, ...]]]:
    out: list[tuple[str, tuple[str, ...]]] = []
    for pred, kinds in PREDICATES.items():
        pools = []
        for k in kinds:
            if k == "Zone":
                pools.append(list(ZONES))
            elif k == "Label":
                pools.append(list(LABELS))
            else:
                pools.append([e.id for e in entities if kind_admits(k, e.type)])
        combos = [()]
        for pool in pools:
            combos = [c + (x,) for c in combos for x in pool]
        out.extend((pred, c) for c in combos)
    return out


@st.composite
def traces(draw, max_frames: int = 24, min_frames: int = 1) -> Trace:
    n_ent = draw(st.integers(1, 5))
    picked = draw(st.lists(st.sampled_from(POOL), min_size=n_ent, max_size=n_ent, unique=True))
    entities = [Entity(id=i, type=t, attrs=tuple(draw(st.lists(st.sampled_from(LABELS), max_size=2, unique=True))))
                for i, t in picked]
    cands = _candidate_facts(entities)
    n = draw(st.integers(min_frames, max_frames))
    gap_pool = st.one_of(st.sampled_from([500, 1000, 1500, 2000, 3000]), st.integers(1, 5000))
    gaps = draw(st.lists(gap_pool, min_size=n, max_size=n))
    t0 = draw(st.sampled_from([0, 0, 250, 1000]))
    ts = [t0]
    for g in gaps[1:]:
        ts.append(ts[-1] + g)
    density = draw(st.sampled_from([1, 2, 4, 8]))
    triples = draw(st.lists(st.tuples(st.integers(0, n - 1), st.integers(0, len(cands) - 1), st.integers(0, 2)),
                            max_size=density * n))
    by_frame: list[list[Fact]] = [[] for _ in range(n)]
    for fi, ci, cf in triples:
        pred, args = cands[ci]
        by_frame[fi].append(Fact(pred=pred, args=args, conf=CONFS[cf]))
    frames = [Frame(t_ms=t, facts=tuple(fs)) for t, fs in zip(ts, by_frame)]
    ctx = TraceContext(
        sub_type=draw(st.one_of(st.none(), st.sampled_from(SUB_TYPES))),
        local_hour=draw(st.one_of(st.none(), st.integers(0, 23))),
        device_id=draw(st.one_of(st.none(), st.sampled_from(["dev1", "dev2"]))))
    return Trace(clip_id="hyp", source="fixture", duration_ms=ts[-1] + draw(st.integers(0, 3000)),
                 entities=tuple(entities), frames=tuple(frames), context=ctx)


# ------------------------------------------------------------------ rules
def _bound_values(trace: Trace | None) -> list[float]:
    vals = [0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 20.0]
    if trace is not None:
        ts = [f.t_ms for f in trace.frames]
        vals += sorted({(ts[j] - ts[i]) / 1000 for i in range(len(ts)) for j in range(i, len(ts))})[:400]
    return vals


def atoms_for(decls: list[tuple[str, str]]) -> st.SearchStrategy:
    """Atoms whose arguments type-check against ``decls`` = [(var name, var type)]."""
    options = []
    for pred, kinds in PREDICATES.items():
        slots = []
        for k in kinds:
            if k == "Zone":
                slots.append(st.sampled_from(ZONES))
            elif k == "Label":
                slots.append(st.sampled_from(LABELS))
            else:
                fits = [n for n, t in decls if set(VAR_TYPES[t]) <= set(VAR_TYPES[k])]
                if not fits:
                    break
                slots.append(st.sampled_from(fits))
        else:
            options.append(st.tuples(*slots).map(lambda a, p=pred: Atom(pred=p, args=tuple(a))))
    return st.one_of(options)


def formulas(decls: list[tuple[str, str]], bounds: list[float], holes: bool = False, max_leaves: int = 6):
    bound = st.sampled_from(bounds)
    if holes:
        bound = st.one_of(bound, st.sampled_from(["a", "b", "d"]).map(lambda n: Hole(name=n)))

    def ordered(pair):
        a, b = pair
        if not isinstance(a, Hole) and not isinstance(b, Hole) and a > b:
            return (b, a)
        return (a, b)

    win = st.tuples(bound, bound).map(ordered)
    return st.recursive(
        atoms_for(decls),
        lambda ch: st.one_of(
            ch.map(lambda c: Not(arg=c)),
            st.lists(ch, min_size=2, max_size=3).map(lambda cs: And(args=tuple(cs))),
            st.lists(ch, min_size=2, max_size=3).map(lambda cs: Or(args=tuple(cs))),
            st.tuples(win, ch).map(lambda x: Eventually(a=x[0][0], b=x[0][1], arg=x[1])),
            st.tuples(win, ch).map(lambda x: Always(a=x[0][0], b=x[0][1], arg=x[1])),
            st.tuples(win, ch, ch).map(lambda x: Then(a=x[0][0], b=x[0][1], left=x[1], right=x[2])),
            st.tuples(bound, ch).map(lambda x: HoldsFor(d=x[0], arg=x[1]))),
        max_leaves=max_leaves).map(normalize)


def _used(n, acc: set[str]) -> set[str]:
    if isinstance(n, Atom):
        acc.update(n.args)
    for c in children(n):
        _used(c, acc)
    return acc


@st.composite
def rules(draw, trace: Trace | None = None, holes: bool = False, context: bool = True, max_leaves: int = 6) -> Rule:
    n = draw(st.integers(1, 3))
    types = draw(st.lists(st.sampled_from(list(VAR_TYPES) + ["Entity", "Person", "Package"]), min_size=n, max_size=n))
    decls = list(zip(VAR_NAMES[:n], types))
    body = draw(formulas(decls, _bound_values(trace), holes=holes, max_leaves=max_leaves))
    used = _used(body, set())
    kept = tuple(VarDecl(name=nm, type=t) for nm, t in decls if nm in used)
    when = ()
    if context and draw(st.integers(0, 2)) == 0:                      # a third of the rules carry context atoms
        hour = st.tuples(st.integers(0, 23), st.integers(0, 23)).map(lambda hh: HourIn(h1=hh[0], h2=hh[1]))
        sub = st.sampled_from(SUB_TYPES).map(lambda v: SubtypeEq(value=v))
        dev = st.sampled_from(["dev1", "dev2", "ava1.ring.device.ABC"]).map(lambda v: DeviceEq(value=v))
        if trace is not None:                                        # mostly satisfiable context
            c = trace.context
            if c.local_hour is not None:
                hour = st.one_of(hour, st.just(HourIn(h1=max(0, c.local_hour - 1), h2=min(23, c.local_hour + 1))),
                                 st.just(HourIn(h1=min(23, c.local_hour + 1), h2=max(0, c.local_hour - 1))))
            if c.sub_type is not None:
                sub = st.one_of(sub, st.just(SubtypeEq(value=c.sub_type)))
            if c.device_id is not None:
                dev = st.one_of(dev, st.just(DeviceEq(value=c.device_id)))
        if holes:
            hour = st.one_of(hour, st.just(HourIn(h1=Hole(name="h1"), h2=Hole(name="h2"))))
        when = tuple(draw(st.lists(st.one_of(hour, sub, dev), max_size=2)))
    return Rule(vars=kept, body=body, when=when)


@st.composite
def rule_and_trace(draw, holes: bool = False, context: bool = True):
    tr = draw(traces())
    return draw(rules(trace=tr, holes=holes, context=context)), tr


@st.composite
def formula_and_trace(draw):
    """A formula over two vars bound to entities of the drawn trace (so atoms are non-trivial)."""
    tr = draw(traces())
    decls = [("x", "Person"), ("y", "Carryable")]
    phi = draw(formulas(decls, _bound_values(tr)))
    ids = [e.id for e in tr.entities]
    persons = [e.id for e in tr.entities if e.type == "person"] or ids
    carry = [e.id for e in tr.entities if e.type in ("package", "object")] or ids
    return phi, tr, {"x": draw(st.sampled_from(persons)), "y": draw(st.sampled_from(carry))}
