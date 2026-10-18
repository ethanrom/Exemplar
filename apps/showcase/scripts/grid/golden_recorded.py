"""F6 `synth.recorded` and F9 `cegis.presets` goldens from the real engine.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/golden_recorded.py

F6: every recorded `solve_result` of the six exported runs (examples by alias, the sketch text, the recorded status /
holes / margin / violated set / placement note); the engine is re-run on each and any difference from the recorded
result is reported (the A3 assert).
F9: `run_cegis` with a replay proposer over the recorded proposals of P1, P2 and Run 2, with the engine's own template
proposer for the back-fill round; expects the recorded event stream minus timing and message text, and the final
candidate list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import golden_io as IO       # noqa: E402

from exemplar.agent.cegis import run_cegis                # noqa: E402
from exemplar.dsl import parse                            # noqa: E402
from exemplar.synth import Example, solve_sketch          # noqa: E402

PRESETS = ("p1-playground", "p2-generated", "run2-identical")


def run_examples(db, rid, id_to_alias, by_alias):
    cid, started = db.execute("select concept_id, started_at_ms from runs where id = ?", (rid,)).fetchone()
    labs = db.execute("select clip_id, value, weight from labels where concept_id = ? and provenance in ('example','active') "
                      "and created_at_ms < ? order by created_at_ms, clip_id", (cid, started)).fetchall()
    return [(id_to_alias[c], v == "pos", float(w)) for c, v, w in labs]


def recorded_events(db, rid, id_to_alias):
    out = []
    for seq, typ, pj in db.execute("select seq, type, payload_json from run_events where run_id = ? order by seq", (rid,)):
        p = json.loads(pj)
        if "violated_clip_ids" in p:
            p["violated_clip_ids"] = [id_to_alias[c] for c in p["violated_clip_ids"]]
        out.append((typ, p))
    return out


def proposals_by_round(events, bank_texts):
    """Rebuild the recorded proposals: the visible `sketch_proposed` / `typecheck_failed` texts per round, the
    back-fill round apart.  A round that shows no new sketch but is followed by another round re-proposed sketches that
    were already known; it replays as the first text of the previous round."""
    rounds: list[dict] = []
    cur = None
    for typ, p in events:
        if typ == "round_started":
            msg = p.get("message") or ""
            if msg.startswith("proposer:"):
                cur = {"round": p["round"], "backfill": False, "texts": []}
                rounds.append(cur)
            elif msg.startswith("template-library"):
                cur = {"round": p["round"], "backfill": True, "texts": []}
                rounds.append(cur)
        elif typ in ("sketch_proposed", "typecheck_failed") and cur is not None:
            cur["texts"].append(p["sketch"])
    prev = None
    for r in rounds:
        if not r["texts"] and not r["backfill"] and prev:
            r["texts"] = [prev[0]]
            r["reproposal"] = True
        if r["texts"] and not r["backfill"]:
            prev = r["texts"]
    return rounds


def norm_event(typ, p):
    e = {"type": typ}
    for k in ("round", "sketch", "result", "holes", "margin", "violated_clip_ids", "error"):
        if k in p and p[k] is not None:
            e[k] = p[k]
    if typ == "candidates" or typ == "done":
        e.pop("sketch", None)
    return e


def main() -> None:
    lib = G.library()
    by_alias = {c.alias: c for c in lib}
    dbs = {k: G.open_ro(k) for k in ("recording", "heldout", "stills")}
    # clip id -> alias, per DB (ids are shared across DBs for the same clip)
    id_to_alias: dict[str, str] = {}
    for key, db in dbs.items():
        for c in lib:
            id_to_alias.setdefault(c.clip_id, c.alias)
    # the library took a clip from one DB; ids of the same clip in another DB are identical (A1)
    f6, f9 = [], []
    problems = []
    for slug, key, rid in G.runs():
        db = dbs[key]
        exs = run_examples(db, rid, id_to_alias, by_alias)
        examples = [Example(by_alias[a].trace, pos, w, a) for a, pos, w in exs]
        events = recorded_events(db, rid, id_to_alias)
        placement = {}
        for typ, p in events:
            if typ == "solve_result":
                msg = p.get("message") or ""
                place = msg.split("placement: ", 1)[1] if "placement: " in msg else None
                rec = {"id": f"{slug}/{len(f6)}", "kind": "recorded",
                       "input": {"run": slug, "examples": [{"alias": a, "positive": pos, "weight": w} for a, pos, w in exs],
                                 "sketch": p["sketch"]},
                       "expect": {"status": p["result"], "holes": p.get("holes"), "margin": p.get("margin"),
                                  "violated": p.get("violated_clip_ids", []), "placement": place}}
                res = solve_sketch(parse(p["sketch"]), examples, timeout_s=G.SOLVE_TIMEOUT_S)
                now = {"status": res.status, "holes": dict(res.holes) if res.rule is not None else None,
                       "margin": res.margin if res.rule is not None else None, "violated": list(res.violated)}
                for k in ("status", "holes", "margin"):
                    if now[k] != rec["expect"][k]:
                        problems.append((slug, p["sketch"], k, now[k], rec["expect"][k]))
                if sorted(now["violated"]) != sorted(rec["expect"]["violated"]):
                    problems.append((slug, p["sketch"], "violated", now["violated"], rec["expect"]["violated"]))
                f6.append(rec)
        if slug in PRESETS:
            rounds = proposals_by_round(events, None)
            holder = {"i": 0}
            texts_by_round = {r["round"]: r["texts"] for r in rounds if not r["backfill"]}

            def proposer(ctx, texts_by_round=texts_by_round):
                return list(texts_by_round.get(ctx.round, []))

            emitted: list = []
            cands = run_cegis(examples, nl_hint=None, emit=lambda e: emitted.append(dict(e)), k=6, model=proposer,
                              solve_timeout_s=G.SOLVE_TIMEOUT_S, backfill=True)
            got = [norm_event(e["type"], e) for e in emitted if e["type"] not in ("done",)]
            # The recorded sessions interleave the agent's own tool calls (solve_started right after sketch_proposed),
            # so the event ORDER of a replay differs from the recording.  A3: every recorded solve_result reappears
            # with the same status, holes, margin and violated set, and the final candidate order is the recorded one.
            def results(evs):
                return {e["sketch"]: (e.get("result"), e.get("holes"), e.get("margin"), sorted(e.get("violated_clip_ids", [])))
                        for e in evs if e["type"] == "solve_result"}
            rec_res = results([norm_event(t, p) for t, p in events])
            got_res = results(got)
            if rec_res != got_res:
                problems.append((slug, "solve_results differ", len(rec_res), len(got_res)))
                for sk in rec_res:
                    if rec_res[sk] != got_res.get(sk):
                        problems.append((slug, sk, rec_res[sk], got_res.get(sk)))
            rec_rules = None
            for typ, p in events:
                if typ == "candidates":
                    rec_rules = p.get("rule_ids") or []
            if rec_rules:
                texts = {rid_: dsl for rid_, dsl in db.execute("select id, dsl_text from rules where run_id = ?", (rid,))}
                rec_order = [texts[r] for r in rec_rules]
                if rec_order != [c.dsl_text for c in cands]:
                    problems.append((slug, "candidate order differs", rec_order[:3], [c.dsl_text for c in cands][:3]))
            f9.append({"id": slug, "kind": "cegis",
                       "input": {"run": slug, "k": 6, "max_rounds": 4,
                                 "examples": [{"alias": a, "positive": pos, "weight": w} for a, pos, w in exs],
                                 "rounds": rounds},
                       "expect": {"events": got,
                                  "candidates": [{"sketch_text": c.sketch_text, "dsl_text": c.dsl_text, "holes": c.holes,
                                                  "margin": c.margin, "mdl": c.mdl,
                                                  "violated": list(c.violated_clip_ids)} for c in cands]}})
    p6 = IO.write_family("synth.recorded", "golden_recorded.py: recorded solve_result events of the six exported runs", None, f6)
    p9 = IO.write_family("cegis.presets", "golden_recorded.py: engine run_cegis with a replay proposer", None, f9)
    print(p6, len(f6), p9, len(f9))
    for pr in problems:
        print("PROBLEM", pr)


if __name__ == "__main__":
    main()
