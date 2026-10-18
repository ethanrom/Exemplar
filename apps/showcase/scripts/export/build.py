"""Builders for every exported document (before scrubbing and schema validation).

Everything here reads allow-listed columns from the in-memory snapshots held by the registry and uses the engine
(no model calls) to recompute scores, boxes and calibrations. Original ids are converted to aliases by the
registry; the caller still runs every document through the recursive scrubber.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from aliases import (CONCEPT_DISPLAY, RUN_SLUGS, RUN_TITLES, Registry, ClipRec)
from common import ExportError
from scrub import Scrubber, check_ast

from exemplar.calibrate import calibrate
from exemplar.contracts.dsl_ast import Rule, holes as ast_holes
from exemplar.contracts.labels import Label
from exemplar.contracts.trace import Trace
from exemplar.dsl import parse, prepare, robustness, to_text
from exemplar.synth import Example, InfeasibleBox, hole_box

LIB_ORDER = ("pg_package", "pg_vehicle", "pg_bird", "frollard", "ringtv_fox", "generated", "meva")
CONCEPT_ORDER = ("package", "vehicle", "theft", "p2-generated", "run2")
CURATED = ("pg-pkg-01", "pg-pkg-07", "pg-veh-01", "pg-bird-01", "cc-frollard-00s", "cc-frollard-15s",
           "cc-frollard-35s", "gen-porch-day-32s")
CURATED_DEFAULT = ("pos", "pos", "neg", "neg", "pos", None, "neg", "pos")
LIVE_RULES = ("package-deployed", "vehicle-deployed")
PROPOSER_NOTE = "Claude on Amazon Bedrock via the Strands agent, recorded"
EVENT_KEYS = ("round", "sketch", "error", "result", "holes", "margin", "violated_clip_ids", "rule_ids", "message")
IGNORED_EVENT_KEYS = ("type", "seq", "at_ms")
ASSERT_DETAILS: list[dict] = []


@dataclass
class World:
    reg: Registry
    scr: Scrubber
    traces_out: dict[str, dict] = field(default_factory=dict)       # alias -> scrubbed trace json
    traces_eng: dict[str, Trace] = field(default_factory=dict)      # alias -> engine Trace of the scrubbed json
    traces_orig: dict[str, Trace] = field(default_factory=dict)     # alias -> engine Trace of the original rows
    labels: dict[str, list[dict]] = field(default_factory=dict)     # concept slug -> label rows (aliases)
    random_drawn: dict[str, list[str]] = field(default_factory=dict)
    rule_objs: dict[str, Rule] = field(default_factory=dict)
    rule_docs: dict[str, dict] = field(default_factory=dict)
    run_docs: dict[str, dict] = field(default_factory=dict)
    examples: dict[str, list[dict]] = field(default_factory=dict)   # run slug -> example rows
    eff_tau: dict[str, float] = field(default_factory=dict)         # rule slug -> tau used for `matched`
    lib_order: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------ traces
def build_traces(w: World) -> None:
    for alias in sorted(w.reg.by_alias):
        rec = w.reg.by_alias[alias]
        t = rec.trace
        ctx = t.get("context") or {}
        out: dict[str, Any] = {
            "schema_version": t["schema_version"], "clip_id": rec.alias, "source": t["source"],
            "duration_ms": t["duration_ms"], "status": t["status"], "error": t.get("error"),
            "entities": t["entities"], "frames": t["frames"],
            "context": {k: ctx[k] for k in ("sub_type", "event_kind", "local_hour", "weekday") if ctx.get(k) is not None},
            "summary": t.get("summary", ""),
        }
        p = t.get("perception")
        if p:
            out["perception"] = {k: p.get(k) for k in ("mode", "model_alias", "n_frames", "samples", "tokens_in",
                                                         "tokens_out", "latency_ms")}
        out = w.scr.obj(out, f"trace[{alias}]")
        w.traces_out[alias] = out
        w.traces_eng[alias] = Trace.model_validate(out)
        w.traces_orig[alias] = Trace.model_validate(t)
        if len(out["frames"]) != 16:
            raise ExportError(f"trace of {alias} has {len(out['frames'])} frames (expected 16)")


# ------------------------------------------------------------------------------------------------ labels
def load_labels(w: World) -> None:
    reg = w.reg
    for cslug in CONCEPT_ORDER:
        c = reg.concepts[cslug]
        db = reg.snaps[c["snap"]]
        rows = []
        for r in db.execute("select clip_id,value,provenance,weight,created_at_ms from labels where concept_id=? "
                            "order by created_at_ms, clip_id", (c["orig"],)):
            rows.append({"alias": reg.alias_of(r["clip_id"]), "label": r["value"], "provenance": r["provenance"],
                         "weight": r["weight"], "created_at_ms": r["created_at_ms"]})
        w.labels[cslug] = rows
        w.random_drawn[cslug] = [reg.alias_of(r["clip_id"]) for r in db.execute(
            "select clip_id from random_samples where concept_id=? order by drawn_at_ms, clip_id", (c["orig"],))]


def run_examples(w: World, run_slug: str) -> list[dict]:
    run = w.reg.runs[run_slug]
    started = run["row"]["started_at_ms"]
    rows = [r for r in w.labels[run["concept"]] if r["provenance"] in ("example", "active") and r["created_at_ms"] < started]
    return [{"alias": r["alias"], "label": r["label"], "provenance": r["provenance"], "weight": r["weight"]} for r in rows]


def engine_examples(w: World, run_slug: str) -> list[Example]:
    return [Example(trace=w.traces_eng[e["alias"]], positive=e["label"] == "pos", weight=e["weight"], clip_id=e["alias"])
            for e in w.examples[run_slug]]


# ------------------------------------------------------------------------------------------------ calibration
def calibration_pairs(w: World, concept: str) -> list[tuple[Trace, Label]]:
    pairs = []
    for r in w.labels[concept]:
        if r["provenance"] != "random":
            continue
        pairs.append((w.traces_eng[r["alias"]], Label(concept_id=concept, clip_id=r["alias"], value=r["label"],
                                                      provenance="random", weight=r["weight"])))
    return pairs


# ------------------------------------------------------------------------------------------------ runs
def _norm_event(w: World, run_slug: str, started: int, seq: int, etype: str, payload: dict) -> dict:
    reg = w.reg
    unknown = set(payload) - set(EVENT_KEYS) - set(IGNORED_EVENT_KEYS)
    if unknown:
        raise ExportError(f"{run_slug}: run event carries keys outside the allow-list: {sorted(unknown)}")
    out: dict[str, Any] = {"seq": seq, "t_ms": int(payload["at_ms"]) - started, "type": etype}
    for k in EVENT_KEYS:
        if k not in payload:
            continue
        v = payload[k]
        if k == "violated_clip_ids":
            v = [reg.alias_of(x) for x in v]
        elif k == "rule_ids":
            try:
                v = [reg.rule_slug[x] for x in v]
            except KeyError:
                raise ExportError(f"{run_slug}: candidates event names a rule outside the exported set")
        out[k] = v
    return out


def build_run(w: World, run_slug: str) -> dict:
    reg = w.reg
    run = reg.runs[run_slug]
    db = reg.snaps[run["snap"]]
    row = run["row"]
    started, finished = row["started_at_ms"], row["finished_at_ms"]
    events = []
    for r in db.execute("select seq,type,payload_json from run_events where run_id=? order by seq", (run["orig"],)):
        events.append(_norm_event(w, run_slug, started, r["seq"], r["type"], json.loads(r["payload_json"])))
    # --- proposals by round (what a replay proposer must return)
    rounds: list[dict] = []
    cur: Optional[dict] = None
    seen_in_round: set[str] = set()
    for e in events:
        if e["type"] == "round_started":
            backfill = "back-fill" in (e.get("message") or "")
            key = (e["round"], backfill)
            if cur is None or (cur["round"], cur["backfill"]) != key:
                cur = {"round": e["round"], "backfill": backfill, "texts": []}
                rounds.append(cur)
                seen_in_round = set()
        elif e["type"] in ("sketch_proposed", "typecheck_failed") and cur is not None:
            t = e.get("sketch")
            if t is not None and t not in seen_in_round:
                seen_in_round.add(t)
                cur["texts"].append(t)
    for e in events:
        if e["type"] in ("sketch_proposed", "typecheck_failed") and cur is None:
            raise ExportError(f"{run_slug}: sketch event before the first round")
    msgs = " ".join((e.get("message") or "") for e in events if e["type"] == "round_started")
    note = PROPOSER_NOTE
    if "template library" in msgs.replace("template-library back-fill", ""):
        note += "; some rounds used the template library"
    cands = [e for e in events if e["type"] == "candidates"]
    if len(cands) != 1:
        raise ExportError(f"{run_slug}: expected one candidates event")
    concept = reg.concepts[run["concept"]]
    cname = CONCEPT_DISPLAY.get(run["concept"], concept["row"]["name"])
    doc = {
        "slug": run_slug, "title": RUN_TITLES[run_slug],
        "concept": {"slug": run["concept"], "name": cname, "nl_hint": concept["row"]["nl_hint"] or "",
                    "alpha": concept["row"]["alpha"]},
        "source": run["snap"], "duration_ms": int(finished - started), "proposer_note": note,
        "examples": w.examples[run_slug], "events": events, "proposals_by_round": rounds,
        "candidates": list(cands[0]["rule_ids"]),
    }
    return doc


# ------------------------------------------------------------------------------------------------ rules
def effective_tau(w: World, row: dict, concept: str, rule: Rule) -> float:
    if row["tau"] is not None:
        return float(row["tau"])
    alpha = w.reg.concepts[concept]["row"]["alpha"]
    cal = calibrate(rule, calibration_pairs(w, concept), alpha)
    return float(cal.tau)


def build_rule(w: World, slug: str) -> dict:
    reg = w.reg
    r = reg.rules[slug]
    row = r["row"]
    status = row["status"]
    if status not in ("deployed", "candidate", "retired"):
        raise ExportError(f"{slug}: unexpected rule status {status!r}")
    run_slug = r["run"]
    concept = reg.runs[run_slug]["concept"]
    ast = json.loads(row["ast_json"])
    check_ast(ast)
    rule = Rule.model_validate(ast)
    if ast_holes(rule):
        raise ExportError(f"{slug}: stored rule is not closed")
    if to_text(rule) != row["dsl_text"]:
        raise ExportError(f"{slug}: dsl_text does not round-trip through the printer")
    w.rule_objs[slug] = rule
    holes = {k: float(v) for k, v in json.loads(row["holes_json"]).items()}
    viol = [reg.alias_of(c) for c in json.loads(row["violations_json"])]
    cal = json.loads(row["calibration_json"]) if row["calibration_json"] else None
    selection = None
    if slug in ("package-deployed", "vehicle-deployed"):
        selection = "chosen_by_user_and_deployed"
    elif slug in ("stills-candidate", "run2-identical"):
        selection = "selected_for_display_as_demo_equivalent"
    tau_eff = effective_tau(w, row, concept, rule)
    w.eff_tau[slug] = tau_eff
    doc: dict[str, Any] = {
        "slug": slug, "run": run_slug, "concept": concept, "status": status,
        "recorded_rank": {"run": run_slug, "position": r["rank"], "of": r["of"]},
        "selection": selection, "ast": ast, "sketch_text": row["sketch_text"], "dsl_text": row["dsl_text"],
        "english": row["english"], "holes": holes, "margin": float(row["margin"]), "mdl": float(row["mdl"]),
        "violations": viol, "tau": None if row["tau"] is None else float(row["tau"]), "delta": float(row["delta"]),
        "calibration": cal,
    }
    # engine hole box of the rule's own sketch, on its own run's examples
    sketch = parse(row["sketch_text"])
    if ast_holes(sketch):
        try:
            box = hole_box(sketch, engine_examples(w, run_slug), satisfied=[e["alias"] for e in w.examples[run_slug]
                                                                           if e["alias"] not in viol],
                           margin=float(row["margin"]))
            doc["box"] = {h: [float(lo), float(hi)] for h, (lo, hi) in box.items()}
        except InfeasibleBox:
            pass
    # engine robustness on every library clip (recomputed on the exported traces, cross-checked on the originals)
    bt = []
    for alias in w.lib_order:
        s = float(robustness(rule, prepare(w.traces_eng[alias])))
        s0 = float(robustness(rule, prepare(w.traces_orig[alias])))
        if s != s0:
            raise ExportError(f"{slug}: score on {alias} differs between the original and the exported trace")
        bt.append({"alias": alias, "score": s, "matched": s > tau_eff})
    doc["backtest"] = bt
    return doc


# ------------------------------------------------------------------------------------------------ library
def build_library(w: World, sandbox_media: str, credits_by_key: dict[str, dict]) -> list[dict]:
    reg = w.reg
    by_clip: dict[str, list[dict]] = {}
    for cslug in CONCEPT_ORDER:
        for r in w.labels[cslug]:
            by_clip.setdefault(r["alias"], []).append({"concept": cslug, "label": r["label"], "provenance": r["provenance"]})
    cards = []
    for alias in w.lib_order:
        rec = reg.by_alias[alias]
        pending = credits_by_key[rec.credit]["permission"]["status"] == "pending_user_decision"
        media = "trace_only" if (sandbox_media == "trace" and pending) else "frames"
        card: dict[str, Any] = {
            "alias": alias, "title": rec.title, "source": rec.source, "class": rec.cls,
            "duration_ms": int(rec.clip["duration_ms"]),
        }
        if rec.source == "playground":
            card["recorded_on"] = datetime.fromtimestamp(rec.event["start_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        card["summary"] = w.traces_out[alias]["summary"]
        card["credit"] = rec.credit
        card["media"] = media
        if media == "frames":
            card["poster"] = f"/media/posters/{alias}.webp"
            card["sheet"] = f"/media/sheets/{alias}.webp"
        card["sheet_times_ms"] = [f["t_ms"] for f in w.traces_out[alias]["frames"]]
        if alias in CURATED:
            card["curated"] = CURATED.index(alias)
        card["recorded_labels"] = by_clip.get(alias, [])
        cards.append(card)
    return cards


# ------------------------------------------------------------------------------------------------ live
def build_live(w: World) -> dict:
    reg = w.reg
    db = reg.snaps["recording"]
    dep = {slug: reg.rules[slug]["orig"] for slug in LIVE_RULES}
    by_event: dict[str, dict[str, dict]] = {}
    for r in db.execute("select f.rule_id, f.event_id, f.stage, f.score, f.tau, f.fired, f.witness_json, e.start_ms "
                        "from firings f join events e on e.id = f.event_id"):
        by_event.setdefault(r["event_id"], {})[r["rule_id"]] = dict(r)
    live_ids = [eid for eid, d in by_event.items() if all(o in d for o in dep.values())]
    live_ids.sort(key=lambda e: by_event[e][dep["package-deployed"]]["start_ms"])
    if len(live_ids) != 5:
        raise ExportError(f"expected 5 two-rule live events, found {len(live_ids)}")
    events = []
    for i, eid in enumerate(live_ids, start=1):
        rec = reg.clips[eid]
        decisions = []
        for slug in LIVE_RULES:
            f = by_event[eid][dep[slug]]
            wit = json.loads(f["witness_json"]) if f["witness_json"] else None
            if bool(f["fired"]) != (wit is not None):
                raise ExportError("a fired decision must carry a witness and a dropped one must not")
            decisions.append({"rule": slug, "stage": f["stage"], "score": float(f["score"]), "tau": float(f["tau"]),
                              "fired": bool(f["fired"]), "witness": _norm_witness(w, wit)})
        events.append({"alias": rec.alias, "order": i, "class": rec.cls, "decisions": decisions})
    return {"events": events}


def _norm_witness(w: World, wit: Optional[dict]) -> Optional[dict]:
    if wit is None:
        return None
    reg = w.reg
    out = dict(wit)
    out["clip_id"] = reg.alias_of(wit["clip_id"])
    out["rule_id"] = reg.rule_slug[wit["rule_id"]]
    return out


# ------------------------------------------------------------------------------------------------ calibration
def build_cal_doc(w: World) -> dict:
    reg = w.reg
    rule = w.rule_docs["package-deployed"]
    if rule["calibration"] is None:
        raise ExportError("package-deployed has no calibration")
    random = []
    for r in w.labels["package"]:
        if r["provenance"] != "random":
            continue
        s = float(robustness(w.rule_objs["package-deployed"], prepare(w.traces_eng[r["alias"]])))
        random.append((r["alias"], r["label"], s))
    drawn = w.random_drawn["package"]
    order = {a: i for i, a in enumerate(drawn)}
    random.sort(key=lambda t: order.get(t[0], 10**6))
    return {
        "concept": "package", "alpha": reg.concepts["package"]["row"]["alpha"], "rule": "package-deployed",
        "scope": "stage1_fast_perception",
        "provenance": {"random_labels": len(random), "drawn_via": "random-sample endpoint",
                       "disjoint_from_examples": True, "disjoint_from_curated": True},
        "random": [{"alias": a, "label": l, "score": s} for a, l, s in random],
        "calibration": rule["calibration"],
    }


# ------------------------------------------------------------------------------------------------ lab files
def build_curated(w: World) -> dict:
    default: list[Optional[str]] = []
    package = {r["alias"]: r for r in w.labels["package"] if r["provenance"] in ("example", "active")}
    p2 = {r["alias"]: r for r in w.labels["p2-generated"]}
    for alias in CURATED:
        if alias in package:
            default.append(package[alias]["label"])
        elif alias in p2:
            default.append(p2[alias]["label"])
        else:
            default.append(None)
    if tuple(default) != CURATED_DEFAULT:
        raise ExportError(f"curated defaults differ from the spec table: {default}")
    return {"clips": list(CURATED), "default": default}


def build_sketches(w: World) -> list[dict]:
    """Every distinct sketch_proposed text in the six exported runs, first appearance first (runs in recorded
    chronological order)."""
    reg = w.reg
    order = sorted(RUN_SLUGS, key=lambda s: reg.runs[s]["row"]["started_at_ms"])
    texts: dict[str, dict] = {}
    for slug in order:
        for e in w.run_docs[slug]["events"]:
            if e["type"] != "sketch_proposed":
                continue
            t = e["sketch"]
            if t not in texts:
                texts[t] = {"id": len(texts), "text": t, "holes": ast_holes(parse(t)), "from_runs": []}
            if slug not in texts[t]["from_runs"]:
                texts[t]["from_runs"].append(slug)
    return list(texts.values())
