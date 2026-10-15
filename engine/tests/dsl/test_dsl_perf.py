"""Micro-benchmark: D evaluates ~200 hole points x ~40 clips per sketch, so one (rule, trace) call must be cheap.

Target is <= ~1 ms per call at T = 24 frames and 6 bindings; the asserted bounds are deliberately generous
(CI machines are noisy) -- run with `-s` to see the measured numbers.
"""
from __future__ import annotations

import random
import time

from exemplar.contracts.dsl_ast import fill_holes
from exemplar.contracts.ontology import CONF_VALUE, ZONES
from exemplar.contracts.trace import Entity, Fact, Frame, Trace
from exemplar.dsl import compile_rule, evaluate, evaluate_bool, parse, prepare, robustness, witness

SKETCH = ("exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch) "
          "and not eventually[0, ?b] attr(p, delivery_uniform) when hour in [?h1, 22]")


def big_trace(seed: int = 0, n: int = 24) -> Trace:
    """3 persons x 2 packages = 6 bindings, dense random facts."""
    rnd = random.Random(seed)
    ents = tuple(Entity(id=f"p{i}", type="person", attrs=("hoodie",) if i else ("delivery_uniform",)) for i in range(1, 4)) \
        + tuple(Entity(id=f"k{i}", type="package") for i in range(1, 3))
    frames = []
    for i in range(n):
        facts = []
        for _ in range(8):
            p = rnd.choice(["picks_up", "leaves", "carrying", "in_zone", "near", "enters"])
            who = rnd.choice(["p1", "p2", "p3"])
            if p in ("picks_up", "carrying"):
                args = (who, rnd.choice(["k1", "k2"]))
            elif p == "near":
                args = (who, rnd.choice(["k1", "k2"]))
            else:
                args = (who, rnd.choice(ZONES))
            facts.append(Fact(pred=p, args=args, conf=rnd.choice(list(CONF_VALUE))))
        frames.append(Frame(t_ms=i * 1000 + rnd.randint(0, 400) * (i > 0), facts=tuple(facts)))
    frames = sorted({f.t_ms: f for f in frames}.values(), key=lambda f: f.t_ms)
    from exemplar.contracts.trace import TraceContext
    return Trace(clip_id=f"big{seed}", source="fixture", duration_ms=frames[-1].t_ms + 1000, entities=ents,
                 frames=tuple(frames), context=TraceContext(local_hour=14))


def _per_call_ms(fn, calls: int) -> float:
    fn()                                               # warm caches
    t0 = time.perf_counter()
    for _ in range(calls):
        fn()
    return (time.perf_counter() - t0) / calls * 1e3


def test_hole_point_evaluation_speed(capsys):
    sketch = parse(SKETCH)
    cr = compile_rule(sketch)
    traces = [prepare(big_trace(s)) for s in range(8)]
    assert len(traces[0].bindings(cr.types)) == 6 and traces[0].T >= 20
    rnd = random.Random(1)
    points = [{"a": rnd.choice([0, 0.5, 1, 2]), "b": rnd.choice([2, 4, 8, 16, 23]), "h1": rnd.randint(0, 14)}
              for _ in range(200)]

    def sweep():                                        # one sketch: 200 hole points x 8 clips, compiled path
        for pt in points:
            for tr in traces:
                cr.score(tr, pt)

    t0 = time.perf_counter()
    sweep()
    per_call = (time.perf_counter() - t0) / (len(points) * len(traces)) * 1e3

    wild = [{"a": rnd.uniform(0, 3), "b": rnd.uniform(3, 23), "h1": rnd.randint(0, 14)} for _ in range(100)]
    t0 = time.perf_counter()                            # every window distinct: no mask-cache hits
    for pt in wild:
        for tr in traces:
            cr.score(tr, pt)
    wild_ms = (time.perf_counter() - t0) / (len(wild) * len(traces)) * 1e3

    tr = traces[0]
    pt = points[0]
    api_ms = _per_call_ms(lambda: evaluate(sketch, tr, pt), 300)                    # public helper, lowering per call
    fill_ms = _per_call_ms(lambda: robustness(fill_holes(sketch, pt), tr), 300)     # fill_holes + robustness
    cold = []
    for s in range(20):                                                             # new Trace each time: includes prepare()
        fresh = big_trace(100 + s)
        t0 = time.perf_counter()
        cr.score(fresh, pt)
        cold.append((time.perf_counter() - t0) * 1e3)
    cold_ms = sum(cold) / len(cold)
    closed = fill_holes(sketch, pt)
    bool_ms = _per_call_ms(lambda: evaluate_bool(closed, tr), 50)
    wit_ms = _per_call_ms(lambda: witness(closed, tr), 100)
    msg = (f"per (rule, trace): compiled+prepared {per_call:.3f} ms | distinct windows {wild_ms:.3f} ms | "
           f"evaluate() {api_ms:.3f} ms | "
           f"fill_holes+robustness {fill_ms:.3f} ms | cold (new Trace) {cold_ms:.3f} ms | "
           f"evaluate_bool {bool_ms:.3f} ms | witness {wit_ms:.3f} ms  (T={tr.T}, bindings=6)")
    with capsys.disabled():
        print("\n" + msg)
    assert per_call < 3.0 and wild_ms < 3.0 and api_ms < 5.0 and cold_ms < 10.0
    assert bool_ms < 100 and wit_ms < 20
