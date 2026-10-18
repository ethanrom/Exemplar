"""F11 `mdl` goldens from the real engine: `exemplar.synth.mdl` on every closed rule of the grid, every sketch of the
bank, and random rules and sketches (with context atoms, hour holes and window holes) from the DSL strategies.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/golden_mdl.py

Run after `assemble.py` (it reads `data/grid/closed.json.gz`).
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import golden_io as IO       # noqa: E402

SEED = 20261018


def main() -> None:
    from hypothesis import HealthCheck, given, seed, settings
    from exemplar.contracts.dsl_ast import DeviceEq
    from exemplar.contracts.dsl_ast import fill_holes
    from exemplar.dsl import parse, to_text
    from exemplar.synth import mdl
    from dsl_strategies import rules

    recs: list[dict] = []

    def add(kind: str, rule, idx: str) -> None:
        text = to_text(rule)
        for v in (0, 1, 3.0, 6.0, 9.0):
            recs.append({"id": f"{kind}/{idx}/{v}", "kind": kind,
                         "input": {"dsl_text": text, "ast": rule.model_dump(mode="json"), "violations": v},
                         "expect": {"mdl": mdl(rule, v)}})

    for b in G.canonical_bank():
        add("sketch", parse(b["text"]), str(b["id"]))
    closed_path = G.SHOWCASE / "data" / "grid" / "closed.json.gz"
    if closed_path.exists():
        for r in json.loads(gzip.open(closed_path, "rt", encoding="utf-8").read())["rules"]:
            add("closed", parse(r["dsl_text"]), r["key"])
    out: list = []

    @settings(max_examples=400, deadline=None, database=None, suppress_health_check=list(HealthCheck))
    @seed(SEED)
    @given(rules(holes=True, context=True, max_leaves=6))
    def run(rule):
        if any(isinstance(c, DeviceEq) for c in rule.when):
            return
        out.append(rule)

    run()
    for i, rule in enumerate(out):
        add("random", rule, str(i))
        holes_ = {h: 1.0 for h in __import__("exemplar.contracts.dsl_ast", fromlist=["holes"]).holes(rule)}
        if holes_:
            add("random_closed", fill_holes(rule, holes_), str(i))
    p = IO.write_family("mdl", "golden_mdl.py: exemplar.synth.mdl", SEED, recs)
    print(p, len(recs), p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
