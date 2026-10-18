"""Generate the DSL golden files (SPEC section 6.2 families F1-F5) from the engine.

Outputs (apps/showcase/lib/dsl/test/golden/):
    dsl.random.jsonl.gz   F1  Hypothesis rule/trace pairs: robustness, witness, texts, round trip, holes, rho
    dsl.real.jsonl.gz     F2  every recorded rule and filled recorded sketch x every recorded trace
    dsl.sweep.jsonl.gz    F3  d-sweeps of holds_for / always / eventually / then on recorded traces
    dsl.edge.jsonl.gz     F4  hand-written boundary and edge cases
    dsl.text.jsonl.gz     F5  recorded and fuzzed DSL texts: parse / typecheck / print / English / errors
    dsl.tables.json.gz        shared trace and rule tables referenced by F2 and F3

Every value comes from the engine (engine/exemplar/dsl). Recorded data are read from the database snapshots
(read-only, in memory) and aliased: no Ring event, device, clip, rule, run or concept id and no path is written.
The generator scans its own output for publication shapes and original values before it finishes.

Run:  PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/goldens/gen_dsl_goldens.py [--only F1,F4]
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import sys
import time
from collections import Counter

import gold_common as gc
from gold_common import GOLDEN_DIR, dumps

import numpy as np
from hypothesis import HealthCheck, Phase, given, seed, settings

import dsl_strategies as S  # engine/tests/dsl/dsl_strategies.py (path added by gold_common)
from exemplar.contracts.dsl_ast import DeviceEq, Rule, fill_holes, holes as ast_holes
from exemplar.contracts.trace import Trace
from exemplar.dsl import (DSLSyntaxError, evaluate, normalize, parse, rho, robustness, to_english, to_text, typecheck,
                          witness)

SEED_F1 = 20261018
SEED_F2 = 20261019
SEED_F5 = 20261020
DEVICE_ALIAS = {".".join(["ava1", "ring", "device", "ABC"]): "dev3"}   # the strategies' device literal looks like a Ring id


# =========================================================================== conversions
def rule_dump(rule: Rule) -> dict:
    return rule.model_dump(mode="json")


def trace_dump(tr: Trace, clip_id: str, device_alias: dict | None = None) -> dict:
    """Scrubbed Trace JSON: only what the evaluator reads (no summary, error, perception, started_at_ms)."""
    d = tr.model_dump(mode="json")
    ctx = d["context"]
    dev = ctx["device_id"]
    if dev is not None and device_alias is not None:
        dev = device_alias.setdefault(dev, f"dev-{len(device_alias) + 1}")
    return {"schema_version": 1, "clip_id": clip_id, "source": d["source"], "duration_ms": d["duration_ms"],
            "status": d["status"], "entities": d["entities"], "frames": d["frames"],
            "context": {"sub_type": ctx["sub_type"], "event_kind": ctx["event_kind"], "local_hour": ctx["local_hour"],
                        "weekday": ctx["weekday"], "device_id": dev}}


def load_trace(d: dict) -> Trace:
    return Trace.model_validate(d)


def alias_device_rule(rule: Rule) -> Rule:
    """Replace the strategies' Ring-device-shaped literal with a plain alias (semantically a pure rename)."""
    d = rule_dump(rule)
    for c in d["when"]:
        if c["op"] == "device_eq" and c["value"] in DEVICE_ALIAS:
            c["value"] = DEVICE_ALIAS[c["value"]]
    return Rule.model_validate(d)


def full_expect(rule: Rule, trace: Trace, holes: dict | None = None) -> dict:
    """All outputs for one (rule, trace[, holes]) pair."""
    out: dict = {"typecheck": typecheck(rule), "to_text": to_text(rule), "to_english": to_english(rule)}
    out["roundtrip"] = parse(to_text(rule)) == rule
    if holes is None:
        out["robustness"] = robustness(rule, trace)
        out["witness"] = witness(rule, trace)
    else:
        out["robustness"] = evaluate(rule, trace, holes)
        out["witness"] = witness(rule, trace, holes)
        filled = fill_holes(rule, holes)
        out["filled_text"] = to_text(filled)
        out["filled_english"] = to_english(filled)
    return out


def meta(family: str, generator: str, seed_: int | None, **extra) -> dict:
    m = {"family": family, "generator": generator, "engine_commit": gc.engine_commit(), "seed": seed_}
    m.update(extra)
    return m


# =========================================================================== recorded data
class Recorded:
    """Traces, rules and sketches from the three snapshots, aliased and de-duplicated by content."""

    def __init__(self) -> None:
        traces: dict[tuple[str, str], Trace] = {}      # (snapshot, clip id) -> Trace
        rules: dict[str, dict] = {}
        texts: list[str] = []
        sketch_holes: dict[str, list[dict]] = {}      # sketch text -> recorded hole solutions
        tc_failed: list[str] = []
        labelled: set[tuple[str, str]] = set()
        fired: set[tuple[str, str]] = set()
        for name in gc.DB_NAMES:
            db = gc.open_snapshot(name)
            for clip_id, tj in db.execute("select clip_id, trace_json from v_primary_trace order by clip_id"):
                traces[(name, clip_id)] = Trace.model_validate_json(tj)
            for (cid,) in db.execute("select distinct clip_id from labels"):
                labelled.add((name, cid))
            for (eid,) in db.execute("select distinct event_id from firings"):
                fired.add((name, eid))
            for rid, sk, dsl, astj, hj, st in db.execute(
                    "select id, sketch_text, dsl_text, ast_json, holes_json, status from rules order by rowid"):
                rules.setdefault(rid, {"sketch": sk, "dsl": dsl, "ast": json.loads(astj), "holes": json.loads(hj),
                                       "status": st})
                texts.extend([sk, dsl])
            for (pj,) in db.execute("select payload_json from run_events order by rowid"):
                p = json.loads(pj)
                if "sketch" in p:
                    texts.append(p["sketch"])
                    if p.get("type") == "solve_result" and p.get("result") == "sat":
                        sketch_holes.setdefault(p["sketch"], []).append(p.get("holes") or {})
                    if p.get("type") == "typecheck_failed":
                        tc_failed.append(p["sketch"])
            db.close()
        self.raw_rules = rules
        self.texts = list(dict.fromkeys(texts))                # first-appearance order, de-duplicated
        self.sketch_holes = sketch_holes
        self.typecheck_failed = list(dict.fromkeys(tc_failed))

        # content-ordered aliases: independent of the original ids
        self.device_alias: dict[str, str] = {}
        by_content: dict[str, dict] = {}                       # identical scrubbed traces collapse to one entry
        key_of: dict[tuple[str, str], str] = {}
        for key, tr in sorted(traces.items()):
            d = trace_dump(tr, "x", self.device_alias)
            k = dumps({f: d[f] for f in ("duration_ms", "status", "entities", "frames", "context")})
            by_content.setdefault(k, d)
            key_of[key] = k
        order = sorted(by_content)                             # content order: independent of the original ids
        self.alias_of = {k: f"tr-{i + 1:03d}" for i, k in enumerate(order)}
        self.trace_table: dict[str, dict] = {}
        self.trace_objs: dict[str, Trace] = {}
        for k in order:
            a = self.alias_of[k]
            d = dict(by_content[k])
            d["clip_id"] = a
            self.trace_table[a] = d
            self.trace_objs[a] = load_trace(d)
        # the repository's own fixture traces (public, no ids)
        fx_dir = gc.ENGINE / "tests" / "fixtures" / "traces"
        for p in sorted(fx_dir.glob("*.json")):
            tr = Trace.model_validate_json(p.read_text(encoding="utf-8"))
            a = f"fx-{p.stem}"
            d = trace_dump(tr, a, self.device_alias)
            self.trace_table[a] = d
            self.trace_objs[a] = load_trace(d)
        self.labelled_alias = sorted({self.alias_of[key_of[c]] for c in labelled if c in key_of})
        self.fired_alias = sorted({self.alias_of[key_of[c]] for c in fired if c in key_of})


# =========================================================================== F1
def draw(strategy, n: int, seed_: int) -> list:
    out: list = []

    @seed(seed_)
    @settings(max_examples=n, database=None, deadline=None, phases=[Phase.generate],
              suppress_health_check=list(HealthCheck))
    @given(strategy)
    def run(x):
        out.append(x)

    run()
    return out


def hole_values(rule: Rule, trace: Trace, rng: random.Random) -> dict:
    ts = [f.t_ms for f in trace.frames]
    gaps = sorted({(ts[j] - ts[i]) / 1000 for i in range(len(ts)) for j in range(i, len(ts))})[:200] or [0.0]
    grid = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.5, 20.0, 40.0]
    hours = [-1.5, -0.5, 0, 0.5, 1, 1.5, 2.5, 3.5, 5, 5.5, 6, 6.5, 12, 12.5, 21.5, 22, 22.5, 23, 23.5]
    vals = {}
    for h in ast_holes(rule):
        vals[h] = rng.choice(hours) if h.startswith("h") else rng.choice(grid + gaps)
    return vals


def family_f1(rec: Recorded, count_rule: int, count_holes: int, count_rho: int) -> tuple[dict, list[dict]]:
    rows: list[dict] = []
    seen: set[str] = set()
    rng = random.Random(SEED_F1)

    def add(kind: str, rule: Rule, tr: Trace, holes: dict | None = None) -> None:
        trd = trace_dump(tr, "hyp")
        key = dumps([kind, rule_dump(rule), trd, holes])
        if key in seen:
            return
        seen.add(key)
        inp = {"rule": rule_dump(rule), "trace": trd}
        if holes is not None:
            inp["holes"] = holes
        rows.append({"id": f"f1.{kind}.{len(rows):05d}", "input": inp, "expect": full_expect(rule, tr, holes)})

    for rule, tr in draw(S.rule_and_trace(), count_rule + 300, SEED_F1):
        add("rule", alias_device_rule(rule), tr)
    for rule, tr in draw(S.rule_and_trace(holes=True), count_holes + 300, SEED_F1 + 1):
        rule = alias_device_rule(rule)
        if not ast_holes(rule):
            add("rule", rule, tr)
            continue
        add("holes", rule, tr, hole_values(rule, tr, rng))
    nr = 0
    for phi, tr, binding in draw(S.formula_and_trace(), count_rho + 100, SEED_F1 + 2):
        trd = trace_dump(tr, "hyp")
        series = [float(x) for x in rho(phi, tr, binding)]
        inp = {"phi": phi.model_dump(mode="json"), "trace": trd, "binding": binding}
        key = dumps(inp)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"id": f"f1.rho.{nr:05d}", "input": inp, "expect": {"rho": series, "text": to_text(phi),
                                                                         "english": to_english(phi)}})
        nr += 1
    import hypothesis
    return meta("dsl.random", "hypothesis dsl_strategies.rule_and_trace / formula_and_trace, @seed",
                SEED_F1, hypothesis_version=hypothesis.__version__), rows


# =========================================================================== F2
def sketch_fills(rec: Recorded, rng: random.Random, per_sketch: int) -> list[tuple[Rule, dict]]:
    """Closed rules from every recorded sketch: the recorded solutions plus seeded grid points."""
    out: list[tuple[Rule, dict]] = []
    grid = [x / 2 for x in range(0, 81)]
    for text in rec.texts:
        try:
            sk = parse(text)
        except DSLSyntaxError:
            continue
        names = ast_holes(sk)
        if not names or typecheck(sk):
            continue
        sols = [s for s in rec.sketch_holes.get(text, []) if set(s) == set(names)]
        points = list(sols[:2])
        while len(points) < per_sketch:
            points.append({h: (float(rng.randint(0, 23)) if h.startswith("h") else rng.choice(grid)) for h in names})
        for p in points:
            out.append((fill_holes(sk, p), p))
    return out


def family_f2(rec: Recorded, per_sketch: int) -> tuple[dict, list[dict], dict]:
    rng = random.Random(SEED_F2)
    closed: dict[str, tuple[Rule, str]] = {}                 # canonical ast json -> (rule, kind)
    for rid in sorted(rec.raw_rules, key=lambda r: (rec.raw_rules[r]["dsl"], dumps(rec.raw_rules[r]["ast"]))):
        r = Rule.model_validate(rec.raw_rules[rid]["ast"])
        closed.setdefault(dumps(rule_dump(r)), (r, "recorded"))
    for r, _p in sketch_fills(rec, rng, per_sketch):
        closed.setdefault(dumps(rule_dump(r)), (r, "sketch-fill"))
    # a few hand-chosen shapes that the recorded sketches never use but the Lab and the monitor can
    for t in ["exists p: Person: eventually[0, 5] rings_bell(p)",
              "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)",
              "exists v: Vehicle: holds_for >= 120 in_zone(v, dock)", "exists k: Package: always[0, 24] in_zone(k, steps)"]:
        r = parse(t)
        closed.setdefault(dumps(rule_dump(r)), (r, "fixture-rule"))
    ordered = sorted(closed.items(), key=lambda kv: (to_text(kv[1][0]), kv[0]))
    rule_table = {f"rule-{i + 1:04d}": {"ast": rule_dump(r), "kind": kind} for i, (_k, (r, kind)) in enumerate(ordered)}
    rule_objs = {a: Rule.model_validate(v["ast"]) for a, v in rule_table.items()}

    rows: list[dict] = []
    n_wit = 0
    trace_aliases = sorted(rec.trace_objs)
    for ra, r in rule_objs.items():
        cr_text = to_text(r)
        for ta in trace_aliases:
            tr = rec.trace_objs[ta]
            sc = robustness(r, tr)
            exp: dict = {"score": sc}
            # witnesses wherever the score carries information, plus a thin sample of the -C plateau
            if sc != -0.5 or (len(rows) % 4 == 0):
                exp["witness"] = witness(r, tr)
                n_wit += 1
            rows.append({"id": f"f2.{ra}.{ta}", "input": {"rule": ra, "trace": ta}, "expect": exp})
    m = meta("dsl.real", "recorded rules and filled recorded sketches x recorded traces (database snapshots, aliased)",
             SEED_F2, rules=len(rule_objs), traces=len(trace_aliases), witnesses=n_wit)
    return m, rows, rule_table


# =========================================================================== F3
VAR_OF = {"person": "Person", "vehicle": "Vehicle", "package": "Package", "animal": "Animal", "object": "Object"}


def top_facts(tr_json: dict, k: int = 2) -> list[tuple[str, tuple[str, ...]]]:
    cnt: Counter = Counter()
    for fr in tr_json["frames"]:
        for f in fr["facts"]:
            cnt[(f["pred"], tuple(f["args"]))] += 1
    ranked = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
    return [key for key, _n in ranked[:k]]


def sweep_template(tr_json: dict, op: str) -> str | None:
    facts = top_facts(tr_json, 2)
    if not facts or (op == "then" and len(facts) < 2):
        return None
    ent_type = {e["id"]: e["type"] for e in tr_json["entities"]}
    names: dict[str, str] = {}
    decls: list[str] = []

    def atom(pred: str, args: tuple[str, ...]) -> str:
        out = []
        for a in args:
            if a in ent_type:
                if a not in names:
                    names[a] = f"v{len(names) + 1}"
                    decls.append(f"{names[a]}: {VAR_OF[ent_type[a]]}")
                out.append(names[a])
            else:
                out.append(a)
        return f"{pred}({', '.join(out)})"

    a1 = atom(*facts[0])
    if op == "then":
        a2 = atom(*facts[1])
        body = f"{a1} then[0, ?d] {a2}"
    elif op == "holds_for":
        body = f"holds_for >= ?d {a1}"
    else:
        body = f"{op}[0, ?d] {a1}"
    if not decls:
        return None
    return f"exists {', '.join(decls)}: {body}"


def family_f3(rec: Recorded, n_traces: int) -> tuple[dict, list[dict]]:
    cands = [a for a in sorted(rec.trace_objs) if a.startswith("tr-") and len(rec.trace_table[a]["frames"]) >= 8
             and any(fr["facts"] for fr in rec.trace_table[a]["frames"])]
    prefer = [a for a in cands if a in set(rec.labelled_alias) | set(rec.fired_alias)] or cands
    step = max(1, len(prefer) // n_traces)
    chosen = prefer[::step][:n_traces]
    sketches: dict[str, str] = {}
    rows: list[dict] = []
    grid = [x / 2 for x in range(0, 81)]
    for ta in chosen:
        trj = rec.trace_table[ta]
        tr = rec.trace_objs[ta]
        ts = [f["t_ms"] for f in trj["frames"]]
        gaps = sorted({(ts[j] - ts[i]) / 1000 for i in range(len(ts)) for j in range(i + 1, len(ts))})
        gap_pts = [g for g in gaps if g <= 40.0 and g not in set(grid)][:12]
        for op in ("holds_for", "always", "eventually", "then"):
            text = sweep_template(trj, op)
            if text is None:
                continue
            sk = parse(text)
            assert typecheck(sk) == [], (text, typecheck(sk))
            sid = f"sk-{len(sketches) + 1:03d}"
            sketches[sid] = text
            for d in grid + gap_pts:
                holes = {"d": d}
                rows.append({"id": f"f3.{sid}.{ta}.{len(rows):05d}",
                             "input": {"sketch": sid, "trace": ta, "holes": holes},
                             "expect": {"score": evaluate(sk, tr, holes), "witness": witness(sk, tr, holes)}})
    m = meta("dsl.sweep", "d sweep 0-40 s in 0.5 s steps plus observed frame gaps; templates from each trace's most "
             "frequent facts", None, traces=chosen, sketches=sketches)
    return m, rows


# =========================================================================== F4
def T(frames, entities=None, ctx=None, status="ok", dur=None, name="edge"):
    """Compact trace builder. frames: [(t_ms, [(pred, [args], conf), ...]), ...]; entities: [(id, type, [attrs])]."""
    ents = [{"id": i, "type": t, "attrs": a} for i, t, a in (entities or [])]
    frs = [{"t_ms": t, "facts": [{"pred": p, "args": a, "conf": c} for p, a, c in fs]} for t, fs in frames]
    last = frames[-1][0] if frames else 0
    return {"schema_version": 1, "clip_id": name, "source": "fixture", "duration_ms": dur if dur is not None else last + 1000,
            "status": status, "entities": ents, "frames": frs,
            "context": {"sub_type": None, "event_kind": None, "local_hour": None, "weekday": None, "device_id": None, **(ctx or {})}}


def edge_cases() -> list[tuple[str, str, dict | None, dict]]:
    P = [("p1", "person", [])]
    K = [("k1", "package", [])]
    PK = [("p1", "person", []), ("k1", "package", [])]
    z = lambda ent, zone, c="high": ("in_zone", [ent, zone], c)
    cases: list[tuple[str, str, dict | None, dict]] = []

    def add(name, text, trace, holes=None):
        cases.append((name, text, holes, trace))

    # --- integer-millisecond boundaries (docs/DSL.md "Time is integer milliseconds")
    t_gap = T([(0, [z("k1", "steps")]), (1100, [z("k1", "steps")])], K)
    add("holds_for d=1.1 at an exact 1100 ms gap", "exists k: Package: holds_for >= 1.1 in_zone(k, steps)", t_gap)
    add("holds_for d just above the gap", "exists k: Package: holds_for >= 1.1000000000000003 in_zone(k, steps)", t_gap)
    add("holds_for d just below the gap", "exists k: Package: holds_for >= 1.0999999999999999 in_zone(k, steps)", t_gap)
    t_f = T([(100, [("picks_up", ["p1", "k1"], "high")]), (300, [("leaves", ["p1", "porch"], "high")])], PK)
    add("then[0.2, 0.2] over frames 100 and 300 ms",
        "exists p: Person, k: Package: picks_up(p, k) then[0.2, 0.2] leaves(p, porch)", t_f)
    add("then[0.2, 0.2] with sketch hole at 0.2",
        "exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)", t_f, {"b": 0.2})
    add("then window just below the gap", "exists p: Person, k: Package: picks_up(p, k) then[0, 0.19999999999999998] leaves(p, porch)", t_f)
    add("eventually[0.3, 0.3] on a 300 ms gap", "exists p: Person: eventually[0.3, 0.3] present(p)",
        T([(0, [("present", ["p1"], "high")]), (300, [("present", ["p1"], "med")])], P))
    t_ms = T([(0, [z("k1", "steps")]), (1, [z("k1", "steps")]), (2, [z("k1", "steps", "low")])], K)
    add("1 ms spacing, holds_for 0.002", "exists k: Package: holds_for >= 0.002 in_zone(k, steps)", t_ms)
    add("1 ms spacing, holds_for 0.003 exceeds the clip", "exists k: Package: holds_for >= 0.003 in_zone(k, steps)", t_ms)
    # --- holds_for corners
    t3 = T([(0, [z("k1", "steps")]), (6000, [z("k1", "steps", "med")]), (12000, [z("k1", "steps")])], K)
    add("holds_for d=0 is the best single frame", "exists k: Package: holds_for >= 0 in_zone(k, steps)", t3)
    add("holds_for d equals the clip length (equality allowed)", "exists k: Package: holds_for >= 12 in_zone(k, steps)", t3)
    add("holds_for d beyond the clip", "exists k: Package: holds_for >= 12.5 in_zone(k, steps)", t3)
    add("holds_for with spacing larger than d needs one true frame", "exists k: Package: holds_for >= 5 in_zone(k, steps)", t3)
    add("holds_for window covers a weak middle frame", "exists k: Package: holds_for >= 6 in_zone(k, steps)", t3)
    add("single frame holds_for 0", "exists k: Package: holds_for >= 0 in_zone(k, steps)", T([(500, [z("k1", "steps")])], K))
    add("single frame holds_for 1", "exists k: Package: holds_for >= 1 in_zone(k, steps)", T([(500, [z("k1", "steps")])], K))
    add("holds_for with a hole", "exists k: Package: holds_for >= ?d in_zone(k, steps)", t3, {"d": 6.0})
    # --- empty windows
    add("eventually over an empty window", "exists p: Person: eventually[5, 6] present(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [])], P))
    add("always over an empty window is -C, not vacuous truth", "exists p: Person: always[5, 6] present(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [])], P))
    add("not always over an empty window is +C", "exists p: Person: not always[5, 6] present(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [])], P))
    add("always window clipped to the clip", "exists p: Person: always[0, 1000] present(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [("present", ["p1"], "med")])], P))
    add("then with an empty right window", "exists p: Person: present(p) then[10, 20] present(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [("present", ["p1"], "high")])], P))
    # --- failed / empty traces, bindings
    add("perception_failed trace", "exists p: Person: present(p)", T([], P, status="perception_failed"))
    add("ok status but no frames", "exists p: Person: present(p)", T([], P))
    add("no entity of the declared type", "exists v: Vehicle: present(v)",
        T([(0, [("present", ["p1"], "high")])], P))
    add("two Person variables with one person (distinct entities)", "exists a: Person, b: Person: near(a, b)",
        T([(0, [("present", ["p1"], "high")])], P))
    add("two Person variables, two people, first binding wins ties",
        "exists a: Person, b: Person: present(a) and present(b)",
        T([(0, [("present", ["p1"], "high"), ("present", ["p2"], "high")])], [("p1", "person", []), ("p2", "person", [])]))
    add("Carryable matches object", "exists p: Person, c: Carryable: carrying(p, c)",
        T([(0, [("carrying", ["p1", "o1"], "high")])], [("p1", "person", []), ("o1", "object", [])]))
    add("Entity variable binds any type", "exists e: Entity: in_zone(e, yard)",
        T([(0, [("in_zone", ["a1", "yard"], "med")])], [("a1", "animal", [])]))
    add("argmax picks the first of two equal bindings", "exists p: Person: in_zone(p, door)",
        T([(0, [("in_zone", ["p1", "door"], "high"), ("in_zone", ["p2", "door"], "high")])],
          [("p1", "person", []), ("p2", "person", [])]))
    add("later binding is stronger", "exists p: Person: in_zone(p, door)",
        T([(0, [("in_zone", ["p1", "door"], "low"), ("in_zone", ["p2", "door"], "high")])],
          [("p1", "person", []), ("p2", "person", [])]))
    # --- context atoms
    add("hour in range", "exists p: Person: present(p) when hour in [6, 22]",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 12}))
    add("hour wraps past midnight (23 in [22, 6])", "exists p: Person: present(p) when hour in [22, 6]",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 23}))
    add("hour wraps past midnight (3 in [22, 6])", "exists p: Person: present(p) when hour in [22, 6]",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 3}))
    add("hour wraps past midnight (12 not in [22, 6])", "exists p: Person: present(p) when hour in [22, 6]",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 12}))
    add("hour bounds are inclusive", "exists p: Person: present(p) when hour in [6, 22]",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 22}))
    add("missing hour makes the atom false", "exists p: Person: present(p) when hour in [0, 23]",
        T([(0, [("present", ["p1"], "high")])], P))
    add("hour hole rounds half to even (2.5 -> 2)", "exists p: Person: present(p) when hour in [?h, 23]",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 2}), {"h": 2.5})
    add("hour hole rounds half to even (3.5 -> 4)", "exists p: Person: present(p) when hour in [?h, 23]",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 3}), {"h": 3.5})
    add("subtype equality", "exists p: Person: present(p) when subtype = human",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"sub_type": "human"}))
    add("subtype mismatch pins the score at -C", "exists p: Person: present(p) when subtype = vehicle",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"sub_type": "human"}))
    add("missing subtype is false", "exists p: Person: present(p) when subtype = human",
        T([(0, [("present", ["p1"], "high")])], P))
    add("device equality", "exists p: Person: present(p) when device = dev-x",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"device_id": "dev-x"}))
    add("device mismatch", "exists p: Person: present(p) when device = dev-y",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"device_id": "dev-x"}))
    add("all context atoms combine with and", "exists p: Person: present(p) when hour in [0, 23] and subtype = human and device = dev-x",
        T([(0, [("present", ["p1"], "high")])], P, ctx={"local_hour": 5, "sub_type": "human", "device_id": "dev-x"}))
    # --- signals
    add("duplicate facts in one frame take the max", "exists p: Person: present(p)",
        T([(0, [("present", ["p1"], "low"), ("present", ["p1"], "high"), ("present", ["p1"], "med")])], P))
    add("present(e) is implied by any fact on e", "exists p: Person: present(p)",
        T([(0, [("rings_bell", ["p1"], "med")])], P))
    add("attr from clip-level labels (med floor)", "exists p: Person: attr(p, hoodie)",
        T([(0, [])], [("p1", "person", ["hoodie"])]))
    add("attr label also asserted high in a frame", "exists p: Person: attr(p, hoodie)",
        T([(0, [("attr", ["p1", "hoodie"], "high")])], [("p1", "person", ["hoodie"])]))
    add("absent attr label", "exists p: Person: attr(p, hi_vis)", T([(0, [])], [("p1", "person", ["hoodie"])]))
    add("near is not mirrored by the evaluator", "exists p: Person, k: Package: near(k, p)",
        T([(0, [("near", ["p1", "k1"], "high")])], PK))
    # --- connectives and spans
    add("not of an absent fact", "exists p: Person: not rings_bell(p)", T([(0, [])], P))
    add("not eventually (point span)", "exists p: Person: present(p) and not eventually[0, 5] rings_bell(p)",
        T([(0, [("present", ["p1"], "high")]), (2000, [])], P))
    add("not of a disjunction", "exists p: Person: not (present(p) or rings_bell(p))", T([(0, [])], P))
    add("double negation", "exists p: Person: not not present(p)", T([(0, [("present", ["p1"], "high")])], P))
    add("or tie goes to the first branch", "exists p: Person: present(p) or facing_camera(p)",
        T([(0, [("present", ["p1"], "high"), ("facing_camera", ["p1"], "high")])], P))
    add("or best branch is the second", "exists p: Person: present(p) or facing_camera(p)",
        T([(0, [("present", ["p1"], "low"), ("facing_camera", ["p1"], "high")])], P))
    add("and root span is the hull of its evidence", "exists p: Person: present(p) and eventually[0, 1] rings_bell(p)",
        T([(0, [("present", ["p1"], "high")]), (500, []), (1500, [("rings_bell", ["p1"], "high")])], P))
    add("holds_for inside and", "exists k: Package: holds_for >= 2 in_zone(k, steps) and present(k)",
        T([(0, [z("k1", "steps")]), (1000, [z("k1", "steps")]), (2000, [z("k1", "steps")])], K))
    add("left-nested then chain", "exists p: Person: present(p) then[0, 1] rings_bell(p) then[0, 2] facing_camera(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [("rings_bell", ["p1"], "high")]),
           (3000, [("facing_camera", ["p1"], "high")])], P))
    add("right-nested then", "exists p: Person: present(p) then[0, 1] (rings_bell(p) then[0, 2] facing_camera(p))",
        T([(0, [("present", ["p1"], "high")]), (1000, [("rings_bell", ["p1"], "high")]),
           (3000, [("facing_camera", ["p1"], "high")])], P))
    add("then inside eventually", "exists p: Person: eventually[0, 5] (present(p) then[0, 1] rings_bell(p))",
        T([(0, [("present", ["p1"], "high")]), (500, [("rings_bell", ["p1"], "med")])], P))
    add("always inside holds_for", "exists p: Person: holds_for >= 1 always[0, 1] present(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [("present", ["p1"], "high")]), (2000, [("present", ["p1"], "high")])], P))
    add("window span clipped at the last frame", "exists p: Person: eventually[0, 1000] present(p)",
        T([(0, [("present", ["p1"], "high")]), (2000, [])], P))
    add("window span start clipped", "exists p: Person: eventually[900, 1000] rings_bell(p)",
        T([(0, [("present", ["p1"], "high")]), (1000, [("rings_bell", ["p1"], "high")])], P))
    # --- number printing
    add("bounds with many decimals", "exists p: Person: eventually[0, 0.3333333] present(p)",
        T([(0, [("present", ["p1"], "high")])], P))
    add("tiny bound prints in exponent form", "exists p: Person: eventually[0, 1e-7] present(p)",
        T([(0, [("present", ["p1"], "high")])], P))
    add("large bound", "exists p: Person: eventually[0, 123456789.125] present(p)",
        T([(0, [("present", ["p1"], "high")])], P))
    add("bound that is a tie at the third decimal (0.0625)", "exists p: Person: eventually[0, 0.0625] present(p)",
        T([(0, [("present", ["p1"], "high")])], P))
    add("bound 0.1875", "exists p: Person: eventually[0.1875, 5] present(p)", T([(0, [("present", ["p1"], "high")])], P))
    add("bound 1e21 prints as an integer", "exists p: Person: eventually[0, 1e21] present(p)", T([(0, [("present", ["p1"], "high")])], P))
    add("fractional holes print in English", "exists p: Person, k: Package: picks_up(p, k) then[?a, ?b] leaves(p, porch)", T(
        [(0, [("picks_up", ["p1", "k1"], "high")]), (2500, [("leaves", ["p1", "porch"], "high")])], PK), {"a": 1.25, "b": 7.0625})
    return cases


def family_f4() -> tuple[dict, list[dict]]:
    rows = []
    for i, (name, text, holes, trd) in enumerate(edge_cases()):
        tr = load_trace(trd)
        rule = parse(text)
        exp = full_expect(rule, tr, holes)
        inp: dict = {"text": text, "rule": rule_dump(rule), "trace": trd, "name": name}
        if holes is not None:
            inp["holes"] = holes
        exp["parse"] = rule_dump(rule)
        rows.append({"id": f"f4.{i:03d}", "input": inp, "expect": exp})
    return meta("dsl.edge", "hand-written boundary and edge cases, outputs from the engine", None), rows


# =========================================================================== F5
VOCAB = ["exists", "when", "and", "or", "then", "not", "eventually", "always", "holds_for", ">=", ">", "hour", "in", "subtype",
         "device", "=", "(", ")", "[", "]", ",", ":", "?", "?x", "?b", "0", "5", "-1", "1e3", "5.", ".5", "0x10", "1_0",
         "Person", "Package", "person", "porch", "steps", "present", "present(p)", "p", "k", "q", "22", "6.5", "\n", "\t",
         "\r", "\x0c", "\x0b", "é", "\U0001f600", " ", "@", "#", "'", "\"", ";", "{", "}", "|", "\\", "$"]
BASE_TEXTS_EXTRA = [
    "exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)",
    "exists v: Vehicle: holds_for >= 120 in_zone(v, dock) when hour in [6, 22]",
    "exists p: Person: eventually[0, 30] in_zone(p, door) and not eventually[0, 30] rings_bell(p)",
    "exists p: Person, k: Carryable: (carrying(p, k) or near(p, k)) then[?a, ?b] leaves(p, porch) when subtype = human and device = dev3",
    "exists k: Package: always[0, ?d] in_zone(k, steps) and not eventually[0, ?d] present(k)",
    "exists p: Person, k: Package: picks_up(p, k) then[0, 10] carrying(p, k) and not attr(p, delivery_uniform)",
    "exists v: Vehicle: holds_for >= 120 in_zone(v, dock)", "exists k: Package: always[0, 24] in_zone(k, steps)",
    "exists p: Person: eventually[0, 5] rings_bell(p)",
    "exists p: Person: not (present(p))", "exists p: Person: not(present(p) or rings_bell(p))",
    "exists p: Person: present(p) and not (rings_bell(p))",
    "exists p: Person: present(p) and (facing_camera(p) and rings_bell(p)) and near(p, p)",
    "exists p: Person: (present(p) or rings_bell(p)) or (facing_camera(p) or near(p, p))",
    "exists p: Person: present(p) or rings_bell(p) and facing_camera(p)",
    "exists p: Person: present(p) and rings_bell(p) then[0, 1] facing_camera(p)",
    "exists p: Person: present(p) then[0, 1] rings_bell(p) then[0, 2] facing_camera(p)",
    "exists p: Person: present(p) then[0, 1] (rings_bell(p) then[0, 2] facing_camera(p))",
    "exists p: Person: eventually[0.5, 1e1] present(p) when hour in [6, 22]",
    "exists p: Person: present(p) when subtype = package_delivery and device = dev3-x_1 and hour in [?h1, 5]",
    "exists p: Person,\n   k: Package:" "\n picks_up(p,k)\n then[0,?b]\n leaves(p,porch)",
    "exists p: Person: holds_for >= 2.50 (present(p) or rings_bell(p))",
    "exists e: Entity, p: Person: near(e, p) and attr(e, hoodie)",
    "exists a: Animal, o: Object, e: Entity: near(a, o) and present(e)",
    "exists v: Vehicle: present(v) when hour in [22, 6]",
    "exists p: Person: present()", "exists p: Person: attr(p, p)",
]
ILL_TYPED = [
    "exists p: Person: rings_doorbell(p)", "exists p: Person: rings_bell(p, p)", "exists p: Person: in_zone(p)",
    "exists p: Person: present()", "exists p: Entity: rings_bell(p)", "exists p: Person, k: Package: picks_up(k, p)",
    "exists p: Person, k: Vehicle: carrying(p, k)", "exists p: Carryable: rings_bell(p)",
    "exists p: Person: in_zone(p, garage)", "exists p: Person: in_zone(p, p)", "exists p: Person: in_zone(porch, porch)",
    "exists p: Person, k: Package: attr(p, k) and present(k)", "exists p: Person: attr(p, delivery_uniform) and near(p, q)",
    "exists p: Person, p: Package: present(p)", "exists p: Person, k: Package: present(p)", "exists door: Person: present(door)",
    "exists p: Person: eventually[5, 2] present(p)", "exists p: Person: present(p) then[0, 5] present(p) then[3, 1] present(p)",
    "exists p: Person: eventually[?a, 1] present(p) and always[2, ?b] present(p)", "exists p: Person: present(p) when hour in [6, 24]",
    "exists p: Person: present(p) when hour in [6, 22] and hour in [22, 6]", "exists p: Person: present(p) when device = bad!id",
    "exists p: Person: attr(p, Bad_Label)", "exists p: Person: attr(p, 9lives)",
    "exists p: Person, q: Person: present(p)", "exists p: Person: Present(p)",
]
SYNTAX_ERRORS = [
    "", "   ", "exists", "exists p", "exists p:", "exists p Person: present(p)", "exists p: Person present(p)",
    "exists p: Person: present(p", "exists p: Person: present(p))", "exists p: Person: present(p) then present(p)",
    "exists p: Person: eventually[0 5] present(p)", "exists p: Person: eventually[0, 5 present(p)",
    "exists p: Person: eventually present(p)", "exists p: Person: Present(p)", "exists p: Person: present(p) when hour in [6.5, 7]",
    "exists p: Person: present(p) when hour in [6, 7.5]", "exists p: Person: present(p) when subtype = foo",
    "exists p: Person: present(p) when subtype = Human", "exists p: Person: present(p) and",
    "exists p: Person: holds_for > 5 present(p)", "exists p: Person: holds_for >= present(p)",
    "exists p: Person:" "\n  present(p)\n  and 5", "exists p: Person: present(p) when hour in [6, 7] and",
    "exists p: Person: present(p) @", "exists p: Person: present(p) when device = ", "exists p: Person: present(p) when device = @",
    "exists p: Person: present(p) when device", "exists p: Person: not", "exists p: Person: not not",
    "exists p: Person: nothing", "exists p: Person: nothing(p)", "exists p: Person: not(p)", "exists p: Person: not (p)",
    "exists p: Person: present(and)", "exists p: Person: present(p, )", "exists p: Person: present(,)",
    "exists p: Person, : present(p)", "exists p: Person, k: Thing: present(p)", "exists P: Person: present(P)",
    "exists p: Person: present(p) when", "exists p: Person: present(p) when hour", "exists p: Person: present(p) when hour in",
    "exists p: Person: present(p) when hour in [", "exists p: Person: present(p) when hour in [6", "exists p: Person: present(p) when hour in [6,",
    "exists p: Person: present(p) then[0, 1]", "exists p: Person: present(p) then[0, 1] ", "exists p: Person: present(p) then[-1, 1] present(p)",
    "exists p: Person: eventually[0, 1] eventually[0, 1]", "exists p: Person: always[0, ?] present(p)", "exists p: Person: always[0, ?B] present(p)",
    "exists p: Person: eventually[1e, 2] present(p)", "exists p: Person: eventually[1e+, 2] present(p)", "exists p: Person: eventually[1.2.3, 2] present(p)",
    "exists p: Person: present(p)\r\n  and\r\n", "exists p: Person: present(p) and present(p)",
    "exists p: Person: present(p) \U0001f600", "exists p: Person: \U0001f600present(p)", "éxists p: Person: present(p)",
    "exists p: Person: present(p)\x0b", "exists p: Person: present(p) when subtype = human and and",
    "(exists p: Person: present(p))", "exists p: Person: ((present(p))", "exists p: Person: (present(p)))",
    "exists p: Person: present(p) or or present(p)", "exists p: Person: present(p) when subtype = human device = dev",
    "exists p: Person: present(p); present(p)", "exists p: Person: present(p) when hour in [6,7] when hour in [1,2]",
    "exists p: Person: present(p) // comment", "exists p: Person: eventually[0, 5]", "exists p: Person: holds_for >= 5",
    "exists p: Person: holds_for >= ?d", "exists p: Person: constructor(p)", "exists p: Person: __proto__(p)", "exists p: Person: toString(p)",
    "exists constructor: Person: present(constructor)", "exists p: Person: present(constructor)",
    "exists p: Person: present(p) when subtype = constructor", "exists p: Person: in_zone(p, constructor)",
]


def tokens_of(s: str) -> list[str]:
    import re
    return re.findall(r"\s+|\?[a-z0-9_]*|[A-Za-z_][A-Za-z0-9_.-]*|\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+|>=|.", s)


def mutate(rng: random.Random, s: str) -> str:
    toks = tokens_of(s)
    k = rng.randrange(8)
    if not toks:
        return rng.choice(VOCAB)
    i = rng.randrange(len(toks))
    if k == 0:
        del toks[i]
    elif k == 1:
        toks.insert(i, toks[i])
    elif k == 2 and len(toks) > 1:
        j = min(i + 1, len(toks) - 1)
        toks[i], toks[j] = toks[j], toks[i]
    elif k == 3:
        toks[i] = rng.choice(VOCAB)
    elif k == 4:
        toks.insert(i, rng.choice(VOCAB))
    elif k == 5:
        return "".join(toks)[:rng.randrange(len(s) + 1)]
    elif k == 6:
        t = toks[i]
        toks[i] = t.swapcase() if t.strip() else rng.choice([" ", "\n", "\t", "  ", "\r\n"])
    else:
        toks[i] = rng.choice(VOCAB) + toks[i]
    return "".join(toks)


def text_expect(text: str) -> dict:
    res: dict = {}
    try:
        rule = parse(text)
    except DSLSyntaxError as e:
        res["parse"] = {"ok": False, "error": {"class": "DSLSyntaxError", "reason": e.message, "line": e.line,
                                               "column": e.column, "context": e.context, "str": str(e)}}
        return res
    except Exception as e:                                   # e.g. OverflowError for an infinite hour bound
        res["parse"] = {"ok": False, "error": {"class": type(e).__name__}}
        return res
    res["parse"] = {"ok": True, "ast": rule_dump(rule)}
    res["typecheck"] = typecheck(rule)
    res["to_text"] = to_text(rule)
    res["to_english"] = to_english(rule)
    try:
        res["roundtrip"] = parse(to_text(rule)) == rule
    except Exception:
        res["roundtrip"] = False
    res["body_text"] = to_text(rule.body)
    res["body_english"] = to_english(rule.body)
    res["vars_text"] = [to_text(v) for v in rule.vars]
    res["vars_english"] = [to_english(v) for v in rule.vars]
    res["when_text"] = [to_text(c) for c in rule.when]
    res["when_english"] = [to_english(c) for c in rule.when]
    return res


def family_f5(rec: Recorded, n_fuzz: int) -> tuple[dict, list[dict]]:
    rng = random.Random(SEED_F5)
    recorded = [t for t in rec.texts if "\n" not in t]
    base = list(dict.fromkeys(recorded + BASE_TEXTS_EXTRA))
    rows: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, text: str) -> None:
        if text in seen:
            return
        seen.add(text)
        exp = text_expect(text)
        try:
            dumps(exp)
        except ValueError:                                   # an infinite bound (1e999) has no strict-JSON form
            return
        rows.append({"id": f"f5.{kind}.{len(rows):04d}", "input": {"text": text, "kind": kind}, "expect": exp})

    for t in rec.texts:
        add("recorded", t)
    for t in rec.typecheck_failed:
        add("recorded-typecheck-failed", t)
    for t in BASE_TEXTS_EXTRA:
        add("example", t)
    for t in ILL_TYPED:
        add("ill-typed", t)
    for t in SYNTAX_ERRORS:
        add("syntax-error", t)
    for t in base:                                           # every prefix at a token boundary (truncation errors)
        toks = tokens_of(t)
        for cut in range(1, len(toks), max(1, len(toks) // 6)):
            add("truncated", "".join(toks[:cut]))
    guard = 0
    while sum(1 for r in rows if r["input"]["kind"] == "fuzz") < n_fuzz and guard < n_fuzz * 20:
        guard += 1
        s = rng.choice(base)
        for _ in range(rng.choice([1, 1, 1, 2, 3])):
            s = mutate(rng, s)
        add("fuzz", s)
    # drop anything the publication scan would flag (random mutations can build odd shapes)
    clean = []
    for r in rows:
        txt = dumps(r)
        if any(rx.search(txt) for rx in gc.SHAPE_RE):
            continue
        clean.append(r)
    import hashlib
    import lark
    from exemplar.contracts.dsl_ast import GRAMMAR
    return meta("dsl.text", "recorded sketch/rule texts, typecheck failures, hand syntax errors, seeded token mutations",
                SEED_F5, grammar_sha256=hashlib.sha256(GRAMMAR.encode("utf-8")).hexdigest(),
                lark_version=lark.__version__), clean


# =========================================================================== main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="F1,F2,F3,F4,F5")
    ap.add_argument("--scan-only", action="store_true", help="only run the publication scan over the written goldens")
    ap.add_argument("--f1", type=int, default=5600, help="closed-rule cases")
    ap.add_argument("--f1-holes", type=int, default=1400)
    ap.add_argument("--f1-rho", type=int, default=800)
    ap.add_argument("--f2-per-sketch", type=int, default=9)
    ap.add_argument("--f3-traces", type=int, default=16)
    ap.add_argument("--f5-fuzz", type=int, default=1500)
    args = ap.parse_args()
    only = {s.strip().upper() for s in args.only.split(",")}
    t0 = time.time()
    if args.scan_only:
        import gzip
        forb = gc.ForbiddenValues()
        for p in sorted(GOLDEN_DIR.glob("dsl.*.gz")):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                gc.scan_text(f.read(), forb, p.name)
        print("publication scan: clean")
        return 0
    rec = Recorded()
    print(f"recorded: {len(rec.trace_table)} traces, {len(rec.raw_rules)} rules, {len(rec.texts)} texts "
          f"({time.time() - t0:.1f}s)")
    forb = gc.ForbiddenValues()
    written: list[tuple[str, int]] = []

    def out(name: str, m: dict, rows: list[dict]) -> None:
        path = GOLDEN_DIR / f"{name}.jsonl.gz"
        n = gc.write_jsonl_gz(path, m, rows)
        written.append((name, n))
        print(f"{name}: {n} cases, {path.stat().st_size / 1024:.0f} KiB ({time.time() - t0:.1f}s)")

    tables: dict | None = None
    if "F1" in only:
        m, rows = family_f1(rec, args.f1, args.f1_holes, args.f1_rho)
        out("dsl.random", m, rows)
    if "F2" in only:
        m, rows, rule_table = family_f2(rec, args.f2_per_sketch)
        out("dsl.real", m, rows)
        tables = {"rules": rule_table}
    if "F3" in only:
        m, rows = family_f3(rec, args.f3_traces)
        out("dsl.sweep", m, rows)
    if "F4" in only:
        m, rows = family_f4()
        out("dsl.edge", m, rows)
    if "F5" in only:
        m, rows = family_f5(rec, args.f5_fuzz)
        out("dsl.text", m, rows)
    if tables is not None or "F3" in only:
        tbl = {"traces": rec.trace_table}
        if tables:
            tbl.update(tables)
        gc.write_json_gz(GOLDEN_DIR / "dsl.tables.json.gz", tbl)

    # publication scan over everything written, decompressed
    import gzip
    for p in sorted(GOLDEN_DIR.glob("dsl.*.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            gc.scan_text(f.read(), forb, p.name)
    print("publication scan: clean;", ", ".join(f"{n}={c}" for n, c in written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
