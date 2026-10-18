"""Recompute-and-assert (SPEC 4.6). Every check raises ExportError on failure; each returns a one-line detail.

The engine does all recomputation (no model calls). Checks run on the *exported* (scrubbed) traces and rules, and
compare with what the databases recorded.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic_core import to_jsonable_python

from aliases import RUN_SLUGS, Registry
from build import CURATED, World, calibration_pairs, engine_examples
from common import ExportError

from exemplar.agent.cegis import run_cegis
from exemplar.calibrate import calibrate
from exemplar.contracts.dsl_ast import holes as ast_holes
from exemplar.dsl import parse, prepare, robustness, to_text, witness as dsl_witness
from exemplar.synth.solve import _grid_in


def fail(msg: str) -> None:
    raise ExportError(msg)


# ------------------------------------------------------------------------------------------------ A1
def a1_shared_rows(reg: Registry) -> str:
    """The recording's rows must be identical in the other two snapshots."""
    rec = reg.snaps["recording"]
    queries = {
        "events": "select id,source,device_id,kind,sub_type,start_ms,end_ms from events",
        "clips": "select id,event_id,path,duration_ms,source_ref,attribution,sha256 from clips",
        "traces": "select clip_id,mode,status,trace_json,cache_key,tokens_in,tokens_out,latency_ms from traces",
        "concepts": "select id,name,nl_hint,alpha from concepts",
        "labels": "select concept_id,clip_id,value,provenance,weight,created_at_ms from labels",
        "random_samples": "select concept_id,clip_id,drawn_at_ms from random_samples",
        "runs": "select id,concept_id,status,error,started_at_ms,finished_at_ms from runs",
        "run_events": "select run_id,seq,type,payload_json,created_at_ms from run_events",
        "rules": "select id,concept_id,run_id,sketch_text,dsl_text,ast_json,english,holes_json,margin,mdl,"
                 "violations_json,status,tau,delta,calibration_json from rules",
        "firings": "select id,rule_id,event_id,stage,score,tau,fired,witness_json from firings",
    }
    total = 0
    for name, sql in queries.items():
        base = {tuple(r) for r in rec.execute(sql)}
        for key in ("heldout", "stills"):
            other = {tuple(r) for r in reg.snaps[key].execute(sql)}
            missing = base - other
            if missing:
                fail(f"A1: {len(missing)} {name} row(s) of the recording differ or are absent in {key}")
        total += len(base)
    return f"{total} shared rows across 10 tables identical in all three snapshots"


# ------------------------------------------------------------------------------------------------ A2
def a2_example_counts(w: World) -> str:
    out = []
    for slug in RUN_SLUGS:
        run = w.reg.runs[slug]
        n = len(w.examples[slug])
        counts = set()
        for e in w.run_docs[slug]["events"]:
            if e["type"] == "differential_check":
                m = re.search(r"on (\d+) examples", e.get("message") or "")
                if m:
                    counts.add(int(m.group(1)))
        if counts != {n}:
            fail(f"A2: {slug}: reconstructed {n} examples, differential_check messages say {sorted(counts)}")
        out.append(f"{slug} {n}")
    if (len(w.examples["p1-playground"]), len(w.examples["p2-generated"]), len(w.examples["run2-identical"])) != (7, 7, 14):
        fail("A2: example counts are not 7/7/14")
    return "reconstructed example counts equal the differential_check counts: " + ", ".join(out)


# ------------------------------------------------------------------------------------------------ A3
class _Replay:
    name = "replay"

    def __init__(self, rounds: list[dict]) -> None:
        self.by_round = {r["round"]: r["texts"] for r in rounds if not r["backfill"]}

    def propose(self, ctx) -> list[str]:
        return list(self.by_round.get(ctx.round, []))


def a3_replay(w: World) -> str:
    notes = []
    n_solves = 0
    for slug in RUN_SLUGS:
        doc = w.run_docs[slug]
        events: list[dict] = []
        examples = engine_examples(w, slug)
        concept = w.reg.concepts[w.reg.runs[slug]["concept"]]
        out = run_cegis(examples, nl_hint=concept["row"]["nl_hint"], emit=events.append, k=6, max_rounds=4,
                        model=_Replay(doc["proposals_by_round"]), solve_timeout_s=10.0, backfill=True)
        rec = {e["sketch"]: e for e in doc["events"] if e["type"] == "solve_result"}
        rep = {e["sketch"]: e for e in events if e["type"] == "solve_result"}
        if set(rec) != set(rep):
            fail(f"A3: {slug}: the replay solved a different set of sketches ({len(rec)} recorded, {len(rep)} replayed)")
        for sk, a in rec.items():
            b = rep[sk]
            for key in ("result", "holes", "margin"):
                if a.get(key) != b.get(key):
                    fail(f"A3: {slug}: solve_result {key} differs for a recorded sketch")
            if list(a.get("violated_clip_ids", [])) != list(b.get("violated_clip_ids", [])):
                fail(f"A3: {slug}: solve_result violated ids differ for a recorded sketch")
        n_solves += len(rec)
        # candidate order
        want = [w.rule_docs[s]["dsl_text"] for s in doc["candidates"]]
        got = [c.dsl_text for c in out]
        if got != want:
            fail(f"A3: {slug}: replayed candidate order differs from the recorded candidates event")
        # back-fill texts
        rec_bf = [t for r in doc["proposals_by_round"] if r["backfill"] for t in r["texts"]]
        rep_bf, in_bf = [], False
        for e in events:
            if e["type"] == "round_started":
                in_bf = "back-fill" in (e.get("message") or "")
            elif in_bf and e["type"] == "sketch_proposed":
                rep_bf.append(e["sketch"])
        if rep_bf != rec_bf:
            fail(f"A3: {slug}: template back-fill texts differ ({len(rep_bf)} replayed, {len(rec_bf)} recorded)")
        notes.append(f"{slug} {len(rec)}")
    return f"engine run_cegis replay reproduced all {n_solves} recorded solve_results, the candidate order and the back-fill texts ({', '.join(notes)})"


# ------------------------------------------------------------------------------------------------ A4
def a4_live(w: World, live: dict) -> str:
    n = 0
    for ev in live["events"]:
        trace = w.traces_eng[ev["alias"]]
        for d in ev["decisions"]:
            rule = w.rule_objs[d["rule"]]
            score = float(robustness(rule, prepare(trace)))
            if score != d["score"]:
                fail(f"A4: score differs for {ev['alias']} / {d['rule']}")
            fired = score > d["tau"]
            if fired != d["fired"]:
                fail(f"A4: fired differs for {ev['alias']} / {d['rule']}")
            if fired:
                wit = to_jsonable_python(dsl_witness(rule, trace))
                wit.update(rule_id=d["rule"], tau=d["tau"], margin=score - d["tau"])
                if wit != d["witness"]:
                    fail(f"A4: witness differs for {ev['alias']} / {d['rule']}")
            elif d["witness"] is not None:
                fail("A4: a dropped decision carries a witness")
            n += 1
    return f"{n} recorded decisions on the 5 live events reproduced exactly (score, fired at tau, witness)"


# ------------------------------------------------------------------------------------------------ A5
def a5_calibration(w: World) -> str:
    for slug, concept in (("package-deployed", "package"), ("vehicle-deployed", "vehicle")):
        alpha = w.reg.concepts[concept]["row"]["alpha"]
        got = calibrate(w.rule_objs[slug], calibration_pairs(w, concept), alpha).to_api()
        want = w.rule_docs[slug]["calibration"]
        if got != want:
            fail(f"A5: recomputed calibration of {slug} differs from calibration_json")
    return "recomputed calibration equals calibration_json for package-deployed and vehicle-deployed"


# ------------------------------------------------------------------------------------------------ A6
def a6_backtest(w: World) -> str:
    out = []
    for slug in ("package-deployed", "run2-identical", "stills-candidate"):
        counts = {"pg_package": [0, 0], "pg_vehicle": [0, 0], "pg_bird": [0, 0]}
        for b in w.rule_docs[slug]["backtest"]:
            cls = w.reg.by_alias[b["alias"]].cls
            if cls in counts:
                counts[cls][1] += 1
                counts[cls][0] += int(b["matched"])
        if counts != {"pg_package": [20, 20], "pg_vehicle": [0, 6], "pg_bird": [0, 7]}:
            fail(f"A6: {slug} backtest on the Playground recordings is {counts}")
        out.append(slug)
    return "package-deployed, run2-identical and stills-candidate each match 20/20 package, 0/6 vehicle, 0/7 bird"


# ------------------------------------------------------------------------------------------------ A7
def a7_boxes(w: World) -> str:
    ok, other_ok, other = [], 0, 0
    for slug, d in w.rule_docs.items():
        sk = parse(d["sketch_text"])
        hs = ast_holes(sk)
        if len(hs) != 1 or "box" not in d or "holds_for" not in d["sketch_text"] or hs[0] not in d["box"]:
            continue
        h = hs[0]
        lo, hi = d["box"][h]
        x = (lo + hi) / 2
        cands = _grid_in(lo, hi)
        snapped = min(cands, key=lambda g: (abs(g - x), g)) if cands else x
        match = snapped == d["holes"].get(h)
        if slug in ("package-deployed", "run2-identical", "stills-candidate"):
            if not match:
                fail(f"A7: {slug}: snapped box centre {snapped} differs from the recorded {d['holes'].get(h)}")
            ok.append(f"{slug} [{lo:g}, {hi:g}] -> {snapped:g}")
        else:
            other += 1
            other_ok += int(match)
    return "; ".join(ok) + f"; {other_ok} of {other} other one-hole holds_for rules also reproduce their recorded d"


# ------------------------------------------------------------------------------------------------ A10
def a10_calibration_validity(w: World) -> str:
    reg = w.reg
    p1_examples = {e["alias"] for e in w.examples["p1-playground"]}
    rand = [r for r in w.labels["package"] if r["provenance"] == "random"]
    rand_ids = {r["alias"] for r in rand}
    if rand_ids & p1_examples:
        fail("A10: the package random set overlaps P1's examples")
    if rand_ids & set(CURATED):
        fail("A10: the package random set overlaps the 8 curated clips")
    for cslug in ("package", "vehicle"):
        drawn = set(w.random_drawn[cslug])
        lab = {r["alias"] for r in w.labels[cslug] if r["provenance"] == "random"}
        if not lab <= drawn:
            fail(f"A10: a random label of {cslug} is not in random_samples")
        run_ex = {e["alias"] for s in RUN_SLUGS if reg.runs[s]["concept"] == cslug for e in w.examples[s]}
        if lab & run_ex:
            fail(f"A10: a random-labelled clip of {cslug} is also one of its run's examples")
        if any(r["provenance"] == "random" and r["alias"] not in drawn for r in w.labels[cslug]):
            fail(f"A10: random label without a random_samples row for {cslug}")
    for cslug in ("theft", "p2-generated", "run2"):
        if any(r["provenance"] == "random" for r in w.labels[cslug]):
            fail(f"A10: unexpected random labels for {cslug}")
    return (f"package random set ({len(rand_ids)} clips) is disjoint from P1's examples and the 8 curated clips; every random "
            "label has provenance random and a random_samples row; no random clip is an example of its concept's run")


# ------------------------------------------------------------------------------------------------ A11
def a11_ranks(w: World) -> str:
    for slug, rd in w.rule_docs.items():
        rr = rd["recorded_rank"]
        cands = w.run_docs[rr["run"]]["candidates"]
        if cands[rr["position"] - 1] != slug or rr["of"] != len(cands):
            fail(f"A11: recorded_rank of {slug} does not match the candidates event of its run")
    want = {"package-deployed": (3, 6), "stills-candidate": (5, 6), "run2-identical": (2, 6)}
    for slug, (pos, of) in want.items():
        rr = w.rule_docs[slug]["recorded_rank"]
        if (rr["position"], rr["of"]) != (pos, of):
            fail(f"A11: {slug} is {rr['position']} of {rr['of']} (documented: {pos} of {of})")
    return "package-deployed 3rd of 6 (P1), stills-candidate 5th of 6 (P2), run2-identical 2nd of 6 (Run 2); every rule's rank equals its position in its run's candidates event"


# ------------------------------------------------------------------------------------------------ A8 (closure)
def a8_closure(w: World, docs: dict[str, Any]) -> str:
    lib = {c["alias"] for c in docs["library"]}
    runs, rules = set(docs["runs"]), set(docs["rules"])
    refs = 0

    def chk(a: str, where: str) -> None:
        nonlocal refs
        refs += 1
        if a not in lib:
            fail(f"A8: unresolved clip alias at {where}")

    for c in docs["library"]:
        chk(c["alias"], "library")
    for slug, r in docs["runs"].items():
        for e in r["examples"]:
            chk(e["alias"], f"runs/{slug}")
        for ev in r["events"]:
            for a in ev.get("violated_clip_ids", []):
                chk(a, f"runs/{slug}.events")
            for s in ev.get("rule_ids", []):
                if s not in rules:
                    fail("A8: unresolved rule slug in a run event")
        for s in r["candidates"]:
            if s not in rules:
                fail("A8: unresolved rule slug in a candidates list")
    for slug, r in docs["rules"].items():
        if r["run"] not in runs:
            fail("A8: rule refers to an unknown run")
        for a in r["violations"]:
            chk(a, f"rules/{slug}.violations")
        for b in r["backtest"]:
            chk(b["alias"], f"rules/{slug}.backtest")
    for ev in docs["live"]["events"]:
        chk(ev["alias"], "live")
        for d in ev["decisions"]:
            if d["rule"] not in rules:
                fail("A8: live decision refers to an unknown rule")
            if d["witness"]:
                chk(d["witness"]["clip_id"], "live.witness")
    for r in docs["calibration"]["random"]:
        chk(r["alias"], "calibration")
    for a in docs["curated"]["clips"]:
        chk(a, "curated")
    for a in docs["traces"]:
        chk(a, "traces")
    for e in docs["credits"]:
        for a in e["aliases"]:
            chk(a, "credits")
    return f"{refs} clip references resolve to library.json; every rule slug and run slug resolves"
