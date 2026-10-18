"""F7 `synth.random` goldens from the real engine: random sketches over random small traces, through `solve_sketch`,
`hole_box` and the exhaustive reference `brute_force` (with the alternatives count).

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/golden_random.py [--workers 3] [--per-worker 330]

Instances come from `synth_support.instances` (Hypothesis, one seed per worker).  Instances with a `device_eq` context
atom are dropped (their strategy value would look like a device id to the shape scan); timeouts and grid fallbacks are
dropped (operational, not reproducible).
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import golden_io as IO       # noqa: E402

SEEDS = [20261018, 20261019, 20261020, 20261021, 20261022, 20261023, 20261024, 20261025, 20261026, 20261027]


def _trace_json(tr, clip_id: str) -> dict:
    d = tr.model_dump(mode="json")
    ctx = d.get("context") or {}
    return {"clip_id": clip_id, "duration_ms": d["duration_ms"], "status": d["status"], "entities": d["entities"],
            "frames": d["frames"], "context": {"sub_type": ctx.get("sub_type"), "local_hour": ctx.get("local_hour")}}


def worker(args) -> list[dict]:
    seed_i, n, only_sat = args
    from hypothesis import HealthCheck, given, seed, settings
    import exemplar.synth.solve as S
    from exemplar.contracts.dsl_ast import DeviceEq
    from exemplar.dsl import to_text
    from exemplar.synth import InfeasibleBox, hole_box, solve_sketch
    from synth_support import instances
    import ties as T

    cap: dict = {}
    orig = S._place

    def spy(enc, cr, p0, m_star, sat_idx, timeout_s):
        holes, how = orig(enc, cr, p0, m_star, sat_idx, timeout_s)
        cap["how"] = how
        return holes, how

    S._place = spy
    out: list[dict] = []

    @settings(max_examples=n, deadline=None, database=None, suppress_health_check=list(HealthCheck))
    @seed(SEEDS[seed_i])
    @given(instances(max_frames=6, max_holes=3, n_examples=(2, 4), min_holes=0))
    def run(inst):
        sketch, examples = inst
        if any(isinstance(c, DeviceEq) for c in sketch.when):
            return
        cap.clear()
        res = solve_sketch(sketch, examples, timeout_s=20)
        if res.status not in ("sat", "unsat"):
            return
        if only_sat and not (res.status == "sat" and res.holes):
            return
        rec = {
            "id": f"r{seed_i}/{len(out)}", "kind": "random",
            "input": {"sketch": to_text(sketch),
                      "examples": [{"trace": _trace_json(e.trace, e.clip_id), "positive": e.positive, "weight": e.weight,
                                    "clip_id": e.clip_id} for e in examples]},
            "expect": {"status": res.status,
                       "holes": dict(res.holes) if res.rule is not None else None,
                       "margin": res.margin if res.rule is not None else None,
                       "violated": list(res.violated), "satisfied": list(res.satisfied),
                       "placement": cap.get("how") if res.rule is not None else None, "box": None,
                       "alternatives": T.brute_alternatives(sketch, examples, level0=res.status == "unsat")},
        }
        if res.rule is not None and res.holes:
            try:
                box = hole_box(sketch, examples, satisfied=list(res.satisfied), margin=res.margin)
                rec["expect"]["box"] = {k: [v[0], v[1]] for k, v in box.items()}
            except InfeasibleBox:
                rec["expect"]["box"] = None
        out.append(rec)

    run()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--per-worker", type=int, default=330)
    ap.add_argument("--n-seeds", type=int, default=4)
    ap.add_argument("--only-sat", action="store_true", help="keep only sat results with holes (family synth.random.sat, seeds 6..)")
    a = ap.parse_args()
    with mp.Pool(a.workers) as pool:
        first = 6 if a.only_sat else 0
        parts = pool.map(worker, [(first + i, a.per_worker, a.only_sat) for i in range(a.n_seeds)])
    recs = [r for part in parts for r in part]
    fam = "synth.random.sat" if a.only_sat else "synth.random"
    p = IO.write_family(fam, "golden_random.py: Hypothesis synth_support.instances -> solve_sketch / hole_box / brute_force",
                        SEEDS[(6 if a.only_sat else 0):][: a.n_seeds], recs)
    print(p, len(recs), p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
