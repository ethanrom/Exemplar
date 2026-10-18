"""Merge the JSON summaries written by several `lib/synth/compare/run-parity.ts --out` processes into one report.

    python apps/showcase/scripts/grid/merge_parity.py OUT.json PART1.json PART2.json ...
"""
from __future__ import annotations

import json
import sys


def main() -> None:
    out, parts = sys.argv[1], sys.argv[2:]
    total: dict = {}
    for p in parts:
        d = json.load(open(p, encoding="utf-8"))
        for k, v in d.items():
            if isinstance(v, dict):
                t = total.setdefault(k, {})
                for kk, vv in v.items():
                    t[kk] = t.get(kk, 0) + vv
            elif isinstance(v, list):
                total.setdefault(k, []).extend(v)
            elif k.startswith("max_"):
                total[k] = max(total.get(k, 0), v)
            else:
                total[k] = total.get(k, 0) + v
    total["problems"] = total.get("problems", [])[:100]
    total["avg_slot_ms"] = round(total["ms"] / max(1, total["slots"]), 1)
    total["ms"] = round(total["ms"])
    json.dump(total, open(out, "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v for k, v in total.items() if k != "problems"}, indent=1))
    print("problems:", len(total["problems"]))


if __name__ == "__main__":
    main()
