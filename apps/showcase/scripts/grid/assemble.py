"""Phase C of the Lab grid: raw engine results + tie counts -> `data/grid/{grid,closed}.json.gz`, `sketches.json`,
`curated.json` and `grid-report.json`.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/assemble.py [--allow-partial]

grid.json (format "exemplar.lab-grid/1", SPEC 4.5, dictionary-coded to fit the size budget):

  { "format", "provenance": {...}, "clips": [alias x 8], "slots": 6561, "valid_slots": 6050,
    "status_codes": ["sat","unsat","rejected","timeout","grid_fallback","error"],
    "sketches": [ { "id", "holes": [names], "rows": [...], "slot": [...] } x 37 ],
    "top6": [ [sketch ids] | null ] x 6561 }

  slot index = sum(state[i] * 3**i), state 0 not used / 1 yes / 2 no, clip 0 least significant; invalid slots (no yes
  or no no) are null in every array.
  `slot[s]` is an index into `rows`, or null.  A row is  [status, holes, margin, violated, mdl, alternatives, placement,
  model_point]  with trailing nulls dropped:
    status        0 sat, 1 unsat, 2 rejected, 3 timeout, 4 grid_fallback, 5 error
    holes         values in the sketch's hole order (sat / grid_fallback), else null
    margin        optimal margin level (sat), else null
    violated      bitmask over `clips` (bit i = clip i) of the examples the engine's answer gets wrong
    mdl           MDL of the candidate (weighted violations), else null
    alternatives  distinct optimal satisfied sets (sat: at the optimal margin; unsat: at the lowest level); -1 beyond the
                  brute-force budget (40,000 points); null for operational statuses
    placement     the engine's placement note when it was NOT the slack centre (the engine stepped back towards its Z3
                  model point), else null
    model_point   that Z3 model point (values in hole order) for those entries; the TS solver cannot know it, so such
                  entries count as engine-supplied (SPEC 6.3)
  `top6[s]` = the sketch ids of `candidates()[:6]` in engine order after the engine's own de-duplication.

closed.json: every distinct closed rule (sketch + holes) in any top6, with the engine robustness on every library clip.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import golden_io as IO       # noqa: E402
from export_traces import scrubbed   # noqa: E402

RAW = G.work_dir() / "grid-raw.jsonl"
TIES = G.work_dir() / "grid-ties.json"
LOG = G.work_dir() / "solve_all.log"
OUT = G.SHOWCASE / "data" / "grid"
STATUS_NAMES = ["sat", "unsat", "rejected", "timeout", "grid_fallback", "error"]


def wall_time_s() -> tuple[float, list[float]]:
    """Wall time of Phase A from its log: the finished segments, plus the last progress line of an interrupted one."""
    segs: list[float] = []
    last_progress = 0.0
    for line in LOG.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\d+)/(\d+) slots, (\d+) s", line)
        if m:
            last_progress = float(m.group(3))
        m = re.match(r"finished (\d+) slots in (\d+) s", line)
        if m:
            segs.append(float(m.group(2)))
            last_progress = 0.0
        if "slots done" in line and last_progress:       # a resume line follows an interrupted segment
            segs.append(last_progress)
            last_progress = 0.0
    return sum(segs), segs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    import z3
    from exemplar.contracts.dsl_ast import fill_holes
    from exemplar.dsl import compile_rule, parse, prepare, to_english, to_text

    lib = G.library()
    cur = G.curated(lib)
    order = G.canonical_library_order()
    if order is not None:
        if sorted(order) != sorted(c.alias for c in lib):
            raise AssertionError("the exported library and the engine-side library disagree")
        lib = sorted(lib, key=lambda c: order.index(c.alias))      # closed.json scores follow library.json order
    raw_bank = G.sketch_bank()               # the order the raw engine results are in
    bank = G.canonical_bank()                # the order (ids) of the shipped sketches.json
    n_sk = len(bank)
    raw: dict[int, dict] = {}
    for line in RAW.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            raw[r["slot"]] = r
    missing = [s for s in G.VALID_SLOTS if s not in raw]
    if missing and not a.allow_partial:
        raise SystemExit(f"{len(missing)} valid slots are missing from the raw results")
    ties = json.loads(TIES.read_text(encoding="utf-8"))["sketches"]

    # ---- candidates() ranking, replayed from the per-sketch entries (so a reordered bank needs no new solves)
    dsl_cache: dict[tuple, str] = {}

    def dsl_text(raw_id: int, holes) -> str:
        key = (raw_id, tuple(holes or ()))
        t = dsl_cache.get(key)
        if t is None:
            sk = parse(raw_bank[raw_id]["text"])
            t = dsl_cache[key] = to_text(fill_holes(sk, dict(zip(raw_bank[raw_id]["holes"], holes or ()))))
        return t

    def rank(entries_by_raw: list[dict], order: list[int]) -> list[int]:
        """State.candidates()[:6] as raw sketch ids, for sketches submitted in `order` (raw ids)."""
        cands = []
        for pos, rid in enumerate(order):
            e = entries_by_raw[rid]
            if e["status"] in (0, 4) and e.get("holes") is not None and e.get("mdl") is not None:
                cands.append((e["mdl"], -e["margin"], dsl_text(rid, e["holes"]), pos, rid))
        cands.sort(key=lambda c: (c[0], c[1], c[2]))          # stable: ties keep submission order
        seen, out = set(), []
        for c in cands:
            if c[2] not in seen:
                seen.add(c[2])
                out.append(c[4])
        return out[: G.K_TOP]

    raw_order = list(range(len(raw_bank)))
    new_order = [b["raw_id"] for b in bank]
    for slot, r in raw.items():
        if rank(r["entries"], raw_order) != r["top6"]:
            raise AssertionError(f"slot {slot}: the replayed candidate ranking differs from the engine's")

    sketches_out = []
    stats = {"status": {}, "alternatives": {}, "placement_not_centre": 0, "operational": [], "budget_ties": 0}
    for b in bank:
        sid, rid = b["id"], b["raw_id"]
        rows: list[list] = []
        row_ix: dict[str, int] = {}
        slot_idx: list = [None] * G.SLOTS
        for slot, r in raw.items():
            e = r["entries"][rid]
            st = e["status"]
            alt = None
            t = ties[str(rid)].get(str(slot))
            if st == 0:
                alt = t[0] if t else None
            elif st == 1:
                alt = t[1] if t else None
            placement = None
            mp = None
            if e.get("how") is not None and e["how"] != "slack-centre":
                placement, mp = e["how"], e.get("p0")
                stats["placement_not_centre"] += 1
            row = [st, e.get("holes"), e.get("margin"), e.get("violated"), e.get("mdl"), alt, placement, mp]
            while row and row[-1] is None:
                row.pop()
            key = json.dumps(row, separators=(",", ":"))
            ix = row_ix.get(key)
            if ix is None:
                ix = row_ix[key] = len(rows)
                rows.append(row)
            slot_idx[slot] = ix
            stats["status"][STATUS_NAMES[st]] = stats["status"].get(STATUS_NAMES[st], 0) + 1
            if st in (3, 4, 5):
                stats["operational"].append([sid, slot, STATUS_NAMES[st]])
            if alt is not None:
                stats["alternatives"][str(alt)] = stats["alternatives"].get(str(alt), 0) + 1
        sketches_out.append({"id": sid, "holes": b["holes"], "rows": rows, "slot": slot_idx})

    new_id_of_raw = {b["raw_id"]: b["id"] for b in bank}
    top6: list = [None] * G.SLOTS
    for slot, r in raw.items():
        top6[slot] = [new_id_of_raw[x] for x in rank(r["entries"], new_order)]

    # ---- closed rules
    closed_keys: dict[str, dict] = {}
    for slot, r in raw.items():
        for sid in top6[slot]:
            e = r["entries"][bank[sid]["raw_id"]]
            key = f"s{sid}[{','.join(repr(h) for h in e['holes'])}]" if e.get("holes") else f"s{sid}[]"
            if key not in closed_keys:
                closed_keys[key] = {"sketch": sid, "holes": e.get("holes") or [], "mdl": e.get("mdl")}
    preps = [prepare(c.trace) for c in lib]
    closed = []
    for key, c in sorted(closed_keys.items(), key=lambda kv: (kv[1]["sketch"], kv[1]["holes"])):
        b = bank[c["sketch"]]
        rule = fill_holes(parse(b["text"]), dict(zip(b["holes"], c["holes"])))
        cr = compile_rule(rule)
        closed.append({"key": key, "sketch": c["sketch"], "holes": c["holes"], "dsl_text": to_text(rule),
                       "english": to_english(rule), "mdl": c["mdl"], "scores": [cr.score(p) for p in preps]})

    wall, segs = wall_time_s()
    cpu = sum(r["ms"] for r in raw.values()) / 1000
    prov = {
        "engine_commit": G.engine_commit(), "z3_version": z3.get_version_string(), "solve_timeout_s": G.SOLVE_TIMEOUT_S,
        "k": G.K_TOP, "weight": G.WEIGHT, "sketch_bank_sha256": G.sha256_json([{"id": b["id"], "text": b["text"]} for b in bank]),
        "curated": [{"alias": c.alias, "trace_sha256": scrubbed(c.alias, c.trace)["digest"]} for c in cur],
        "generated_on": datetime.date.today().isoformat(), "wall_time_s": round(wall), "wall_time_segments_s": segs,
        "cpu_time_s": round(cpu), "workers": a.workers,
        "note": "solved slot by slot with RunState (no proposer, no rounds, no back-fill); alternatives from synth_support.brute_force semantics",
    }
    grid = {"format": "exemplar.lab-grid/1", "provenance": prov, "clips": [c.alias for c in cur], "slots": G.SLOTS,
            "valid_slots": len(G.VALID_SLOTS), "status_codes": STATUS_NAMES, "sketch_ids": [b["id"] for b in bank],
            "sketches": sketches_out, "top6": top6}
    closed_doc = {"format": "exemplar.lab-closed/1", "clips": [c.alias for c in lib], "rules": closed}
    OUT.mkdir(parents=True, exist_ok=True)

    def write_gz(path: Path, obj) -> int:
        raw_bytes = IO.dumps(obj).encode("utf-8")
        with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0, compresslevel=9) as gz:
            gz.write(raw_bytes)
        return len(raw_bytes)

    raw_grid = write_gz(OUT / "grid.json.gz", grid)
    raw_closed = write_gz(OUT / "closed.json.gz", closed_doc)
    (OUT / "sketches.json").write_text(IO.dumps([{"id": b["id"], "text": b["text"], "holes": b["holes"], "from_runs": b["from_runs"]}
                                                 for b in bank]) + "\n", encoding="utf-8")
    states = G.default_states(cur)
    (OUT / "curated.json").write_text(IO.dumps({"clips": [c.alias for c in cur], "default": states}) + "\n", encoding="utf-8")
    report = {"slots_done": len(raw), "valid_slots": len(G.VALID_SLOTS), "entries": len(raw) * n_sk, "closed_rules": len(closed),
              "grid_raw_bytes": raw_grid, "grid_gz_bytes": (OUT / "grid.json.gz").stat().st_size,
              "closed_raw_bytes": raw_closed, "closed_gz_bytes": (OUT / "closed.json.gz").stat().st_size,
              "status_counts": stats["status"], "alternatives_histogram": stats["alternatives"],
              "placement_not_centre_entries": stats["placement_not_centre"], "operational_entries": stats["operational"],
              "rows_per_sketch": [len(s["rows"]) for s in sketches_out]}
    (OUT / "grid-report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows_per_sketch"}, indent=1))


if __name__ == "__main__":
    main()
