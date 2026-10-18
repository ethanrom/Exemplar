"""F10 `cal` goldens on real data: every closed rule of the grid calibrated on the package concept's random set (the
random-labelled clips of "Package left on the steps", disjoint from the eight curated clips), through the engine's
`calibrate`.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/golden_real.py

Run after `assemble.py`.  Writes the family `cal.real`.
"""
from __future__ import annotations

import dataclasses
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import golden_io as IO       # noqa: E402

ALPHAS = (0.1, 0.05, 0.2)


def main() -> None:
    from exemplar.calibrate.rule import calibrate
    from exemplar.contracts.labels import Label
    from exemplar.dsl import compile_rule, parse, prepare

    lib = G.library()
    by_alias = {c.alias: c for c in lib}
    id_to_alias = {c.clip_id: c.alias for c in lib}
    rec_db = G.open_ro("recording")
    package_concept = G.concept_id(rec_db, G.PACKAGE_CONCEPT_NAME)
    rows = rec_db.execute("select clip_id, value from labels where concept_id = ? and provenance = 'random' order by clip_id",
                          (package_concept,)).fetchall()
    rnd = sorted([(id_to_alias[c], v == "pos") for c, v in rows])
    cur = {c.alias for c in G.curated(lib)}
    assert not (cur & {a for a, _ in rnd}), "the random set must be disjoint from the curated clips"
    labelled = [(by_alias[a].trace, Label(concept_id=package_concept, clip_id=by_alias[a].trace.clip_id,
                                         value="pos" if p else "neg", provenance="random", weight=1.0)) for a, p in rnd]
    closed = json.loads(gzip.open(G.SHOWCASE / "data" / "grid" / "closed.json.gz", "rt", encoding="utf-8").read())["rules"]
    recs = []
    for r in closed:
        rule = parse(r["dsl_text"])
        cr = compile_rule(rule)
        scores = {a: cr.score(prepare(by_alias[a].trace)) for a, _ in rnd}
        for alpha in ALPHAS:
            cal = calibrate(rule, labelled, alpha)
            d = cal.to_api()
            d["tau_alpha"] = None if cal.tau_alpha is None else float(cal.tau_alpha)
            recs.append({"id": f"{r['key']}/{alpha}", "kind": "real",
                         "input": {"dsl_text": r["dsl_text"], "alpha": alpha,
                                   "random": [{"alias": a, "positive": p} for a, p in rnd]},
                         "expect": {"scores": [scores[a] for a, _ in rnd], "calibration": d}})
    # the two deployed rules with their recorded calibration (A5): the DB's calibration_json is the expectation
    for slug, concept in (("package-deployed", package_concept),
                          ("vehicle-deployed", G.concept_id(rec_db, G.VEHICLE_CONCEPT_NAME))):
        dsl_text, cal_json = rec_db.execute("select dsl_text, calibration_json from rules where concept_id = ? and status = 'deployed'",
                                            (concept,)).fetchone()
        rows_c = rec_db.execute("select clip_id, value from labels where concept_id = ? and provenance = 'random' order by clip_id",
                                (concept,)).fetchall()
        rnd_c = sorted([(id_to_alias[c], v == "pos") for c, v in rows_c])
        cal_rec = json.loads(cal_json)
        rule = parse(dsl_text)
        cr = compile_rule(rule)
        recs.append({"id": f"recorded/{slug}", "kind": "recorded",
                     "input": {"dsl_text": dsl_text, "alpha": cal_rec["alpha"],
                               "random": [{"alias": a, "positive": p} for a, p in rnd_c]},
                     "expect": {"scores": [cr.score(prepare(by_alias[a].trace)) for a, _ in rnd_c],
                                "calibration": {**cal_rec, "tau_alpha": None}}})
    p = IO.write_family("cal.real", "golden_real.py: exemplar.calibrate.rule.calibrate on the package random set", None, recs,
                        {"random_labels": len(rnd), "random_positives": sum(1 for _, p in rnd if p)})
    print(p, len(recs), p.stat().st_size, "bytes", "random set", len(rnd))


if __name__ == "__main__":
    main()
