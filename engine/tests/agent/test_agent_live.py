"""Opt-in live validation on the demo concepts (spends Bedrock budget): EXEMPLAR_LIVE=1 uv run pytest tests/agent/test_agent_live.py -s

Runs the real Strands/Bedrock agent on the fixture traces for the three demo concepts (a) package theft, (b) a package sitting
on the steps, (c) a vehicle entering the lot, and on the cached real traces (stream B) when `data/cache/traces` exists.
Prints each candidate (English, DSL, margin, MDL), timings and token spend; if EXEMPLAR_D_REPORT is set, also writes a JSON report.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from exemplar.agent import StrandsProposer, run_cegis
from exemplar.contracts.trace import Trace
from exemplar.dsl import robustness
from exemplar.settings import get_settings
from exemplar.synth import Example
from dsl_helpers import load

pytestmark = pytest.mark.live
IN_PER_M, OUT_PER_M = 2.0, 10.0          # strong model, USD per million tokens (budget tracking only)
REPORT: list[dict] = []


def _real_traces() -> dict[str, Trace]:
    d = get_settings().data_dir / "cache" / "traces"
    out: dict[str, Trace] = {}
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        raw = json.loads(p.read_text(encoding="utf-8"))
        tr = Trace.model_validate(raw.get("trace", raw))
        out[tr.clip_id] = tr
    return out


def _examples(pos, neg, loader, wpos=3.0, wneg=3.0):
    return [Example(loader(c), True, wpos, c) for c in pos] + [Example(loader(c), False, wneg, c) for c in neg]


def _run(name, examples, hint, *, k=4, max_rounds=3):
    events: list[dict] = []
    prop = StrandsProposer()
    t0 = time.perf_counter()
    out = run_cegis(examples, nl_hint=hint, emit=events.append, k=k, max_rounds=max_rounds, model=prop)
    dt = time.perf_counter() - t0
    u = prop.usage
    cost = u["inputTokens"] * IN_PER_M / 1e6 + u["outputTokens"] * OUT_PER_M / 1e6
    solves = [e for e in events if e["type"] == "solve_result"]
    print(f"\n===== {name}: {len(out)} candidates in {dt:.1f} s, {len(solves)} sketches solved, "
          f"tokens {u['inputTokens']}/{u['outputTokens']} (~${cost:.2f}), {u['calls']} agent turns")
    for e in events:
        if e["type"] in ("typecheck_failed",):
            print("   typecheck_failed:", e["sketch"][:90], "->", e["error"][:120])
    for c in out:
        print(f"  [{c.mdl:5.1f} bits, margin {c.margin:.2f}, violated {list(c.violated_clip_ids)}]")
        print("     ", c.english)
        print("     ", c.dsl_text)
    REPORT.append({"name": name, "seconds": dt, "tokens": u, "usd": cost, "n_solved": len(solves),
                   "solve_ms": [int(e["message"].split(" ms")[0]) for e in solves if e.get("message")],
                   "candidates": [{"dsl": c.dsl_text, "english": c.english, "margin": c.margin, "mdl": c.mdl,
                                   "violated": list(c.violated_clip_ids), "sketch": c.sketch_text} for c in out],
                   "rounds": len([e for e in events if e["type"] == "round_started"])})
    if os.environ.get("EXEMPLAR_D_REPORT"):
        Path(os.environ["EXEMPLAR_D_REPORT"]).write_text(json.dumps(REPORT, indent=1), encoding="utf-8")
    return out, examples


def _check(out, examples):
    assert out, "no candidate"
    best = out[0]
    byid = {e.clip_id: e for e in examples}
    for cid in set(byid) - set(best.violated_clip_ids):
        assert (robustness(best.rule, byid[cid].trace) > 0) == byid[cid].positive


def test_a_package_theft_fixtures():
    ex = _examples(["theft_a", "theft_b"], ["delivery_a", "delivery_b", "unattended_package", "visitor_no_ring"], load)
    out, ex = _run("(a) package theft [fixtures]", ex, "someone takes a package that was delivered")
    _check(out, ex)


def test_b_package_on_steps_fixtures():
    ex = _examples(["unattended_package"], ["vehicle_passby", "birds_feeder", "theft_a"], load)
    out, ex = _run("(b) package sitting on the steps [fixtures]", ex, "a package has been sitting on the steps for over 10 seconds")
    _check(out, ex)


def test_c_vehicle_enters_fixtures():
    ex = _examples(["vehicle_passby"], ["unattended_package", "birds_feeder"], load)
    out, ex = _run("(c) vehicle enters the lot [fixtures]", ex, "a vehicle enters the lot or driveway")
    _check(out, ex)


@pytest.fixture(scope="module")
def real():
    r = _real_traces()
    if len(r) < 20:
        pytest.skip("no cached real traces under data/cache/traces")
    return r


def test_a_package_theft_real_traces(real):
    pos = ["frollard-010000", "frollard-015000", "frollard-020000"]
    neg = ["frollard-000000", "frollard-025000", "frollard-055000", "frollard-060000", "frollard-070000",
           "frollard-080000", "live_pg_package"]
    ex = _examples(pos, neg, real.__getitem__)
    out, ex = _run("(a') package theft [real traces: frollard windows + Playground package clip]", ex,
                   "a person picks up a package from the steps and walks away with it")
    _check(out, ex)


def test_b_package_on_steps_real_traces(real):
    pos = ["live_pg_package", "frollard-000000"]
    neg = ["frollard-025000", "frollard-060000", "frollard-015000", "frollard-020000", "frollard-040000"]
    ex = _examples(pos, neg, real.__getitem__)
    out, ex = _run("(b') package sitting on the steps [real traces]", ex,
                   "a package has been sitting on the steps for over 10 seconds")
    _check(out, ex)


def test_meva_door_crossing_noisy(real):
    """A noisy 40-clip concept from stream B's MEVA traces (labels from the clip ids): MaxSMT must tolerate violations."""
    pos = sorted(c for c in real if c.startswith("door_crossing") and c.endswith("-pos"))[:10]
    neg = sorted(c for c in real if c.startswith("door_crossing") and c.endswith("-neg"))[:30]
    if len(pos) < 5:
        pytest.skip("not enough MEVA pos traces")
    ex = _examples(pos, neg, real.__getitem__, wpos=1.0, wneg=1.0)
    out, _ = _run("(m) MEVA door_crossing [real, noisy, 40 clips]", ex, "a person goes through a door of the building", k=3, max_rounds=2)
    assert out
