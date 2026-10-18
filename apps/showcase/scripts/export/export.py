"""Showcase export: recorded databases -> scrubbed JSON in data/ and stills in public/media/.

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/export/export.py [--sample] [--sandbox-media frames|trace]
                                                                                      [--out-data DIR] [--out-media DIR]
                                                                                      [--skip-media] [--skip-replay]

Reads the three read-only snapshots (folder from scripts/scan/inputs.local.json), recomputes with the engine (no model
calls), asserts that the recomputation equals what was recorded (SPEC 4.6), scrubs every string, validates every file
against the strict schema, writes the files, runs the deny-scans on the result and stops on any hit.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scan"))

import build as B                                   # noqa: E402
import checks as C                                  # noqa: E402
import schema as S                                  # noqa: E402
from aliases import RUN_SLUGS, build_registry       # noqa: E402
from claims import build_claims                     # noqa: E402
from common import (DATA, MEDIA, SCRATCH, SCHEMA, ExportError, dumps, engine_commit, sha256_file,  # noqa: E402
                    write_json)
from credits import build_credits                   # noqa: E402
from media import check_media_dir, make_media       # noqa: E402
from scrub import Scrubber                          # noqa: E402

SAMPLE_RUNS = ("p1-playground", "vehicle")
# The published site carries no AI-generated clip, nothing taught from one, and nothing derived from them. The registry
# and the checks still see the full set (the recomputation asserts run on everything that was recorded); `_drop_generated`
# removes these from what is written.
DROP_RUNS = ("p2-generated", "run2-identical")
DROP_CONCEPTS = ("p2-generated", "run2")
# Written by other scripts, not by this export: the manifest and the budgets leave them out (cost_vs_rules.json by
# scripts/sync-cost-table.mjs, parity.json by scripts/parity/make-parity.mjs).
NOT_EXPORTED = ("manifest.json", "cost_vs_rules.json", "parity.json")
TABLES = ("events", "clips", "traces", "concepts", "labels", "random_samples", "runs", "run_events", "rules",
          "firings", "cost_ledger")                 # row counts only; never ring_auth / webhook_deliveries


def _source_counts(reg) -> list[dict]:
    out = []
    for key, db in reg.snaps.items():
        rows = {t: int(db.execute(f"select count(*) from {t}").fetchone()[0]) for t in TABLES}
        out.append({"key": key, "rows": rows})
    return out


def _drop_generated(docs: dict) -> dict:
    """Everything that is, or was taught from, an AI-generated clip leaves the published data: the clips (cards, traces,
    media), the runs taught from them with their rules, their backtest rows, their credit entry and their curated slot."""
    gen = {c["alias"] for c in docs["library"] if c["source"] == "generated"}
    if not gen:
        raise ExportError("no generated clip in the library: the drop filter is stale")
    runs = {s: r for s, r in docs["runs"].items() if s not in DROP_RUNS}
    rules = {s: r for s, r in docs["rules"].items() if r["run"] in runs}
    for slug, r in rules.items():
        if gen & set(r["violations"]):
            raise ExportError(f"{slug}: a kept rule is violated by a generated clip")
        r["backtest"] = [b for b in r["backtest"] if b["alias"] not in gen]
    for slug, r in runs.items():
        if any(e["alias"] in gen for e in r["examples"]):
            raise ExportError(f"{slug}: a kept run has a generated example")
    library = []
    for c in docs["library"]:
        if c["alias"] in gen:
            continue
        library.append(dict(c, recorded_labels=[lab for lab in c["recorded_labels"] if lab["concept"] not in DROP_CONCEPTS]))
    clips = docs["curated"]["clips"]
    keep_ix = [i for i, a in enumerate(clips) if a not in gen]
    if keep_ix != list(range(len(keep_ix))):
        raise ExportError("a generated clip is not at the end of the curated list: the Lab's slot numbers would shift")
    curated = {"clips": [clips[i] for i in keep_ix], "default": [docs["curated"]["default"][i] for i in keep_ix]}
    if any(e["alias"] in gen for e in docs["live"]["events"]) or any(p["alias"] in gen for p in docs["calibration"]["random"]):
        raise ExportError("a live event or a random calibration label is a generated clip")
    sketches = [dict(k, from_runs=[r for r in k["from_runs"] if r not in DROP_RUNS]) for k in docs["sketches"]]
    out = dict(docs)
    out.update(
        library=library, traces={a: t for a, t in docs["traces"].items() if a not in gen}, runs=runs, rules=rules,
        curated=curated, sketches=sketches,
        credits=[dict(e, aliases=[a for a in e["aliases"] if a not in gen]) for e in docs["credits"] if e["group"] != "generated"])
    return out


def _published_detail(text: str) -> str:
    """The checks ran on everything recorded; the manifest names only what is published. Drops the runs and rules that
    were taught from AI-generated clips from an assert's detail, and refuses a detail that still mentions them."""
    t = re.sub(r", stills-candidate \d+\w+ of \d+ \(P2\), run2-identical \d+\w+ of \d+ \(Run 2\)", "", text)
    t = re.sub(r", (?:p2-generated|run2-identical) \d+", "", t)
    t = re.sub(r"all \d+ recorded solve_results", "every recorded solve_result", t)
    t = t.replace("package-deployed, run2-identical and stills-candidate each match", "package-deployed matches")
    t = re.sub(r"; (?:run2-identical|stills-candidate) \[[^\]]*\] -> [\d.]+", "", t)
    t = re.sub(r"; (\d+) of (\d+) other one-hole", lambda m: "; every other one-hole" if m.group(1) == m.group(2) else m.group(0), t)
    t = t.replace("the 8 curated clips", "the curated clips")
    if re.search(r"p2-generated|run2|stills|generated", t):
        raise ExportError(f"manifest detail still names a dropped run: {t[:120]}")
    return t


def _sample_filter(w, docs: dict) -> dict:
    """Closure of the sample: the P1 and vehicle runs, their rules, and every clip those reference."""
    runs = {s: docs["runs"][s] for s in SAMPLE_RUNS}
    rules = {s: r for s, r in docs["rules"].items() if r["run"] in SAMPLE_RUNS}
    keep: set[str] = set(docs["curated"]["clips"])
    for r in runs.values():
        keep |= {e["alias"] for e in r["examples"]}
        for ev in r["events"]:
            keep |= set(ev.get("violated_clip_ids", []))
    for r in rules.values():
        keep |= set(r["violations"])
    keep |= {e["alias"] for e in docs["live"]["events"]}
    keep |= {p["alias"] for p in docs["calibration"]["random"]}
    for r in rules.values():
        r["backtest"] = [b for b in r["backtest"] if b["alias"] in keep]
    out = dict(docs)
    out["runs"], out["rules"] = runs, rules
    out["library"] = [c for c in docs["library"] if c["alias"] in keep]
    out["traces"] = {a: t for a, t in docs["traces"].items() if a in keep}
    out["credits"] = [dict(e, aliases=[a for a in e["aliases"] if a in keep]) for e in docs["credits"]
                      if e["group"] == "software" or any(a in keep for a in e["aliases"])]
    return out


def _clear(out_data: Path, out_media: Path) -> None:
    for sub in ("traces", "runs", "rules", "calibration"):
        shutil.rmtree(out_data / sub, ignore_errors=True)
    for sub in ("posters", "sheets"):
        shutil.rmtree(out_media / sub, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sample", action="store_true", help="two runs (P1 and vehicle), their rules and the clips they reference")
    ap.add_argument("--sandbox-media", choices=("frames", "trace"), default="frames")
    ap.add_argument("--out-data", type=Path, default=DATA)
    ap.add_argument("--out-media", type=Path, default=MEDIA)
    ap.add_argument("--skip-media", action="store_true")
    ap.add_argument("--skip-replay", action="store_true", help="skip A3 (the slow engine replay); never for a committed export")
    ap.add_argument("--date", default=None, help="exported_on (default: today, UTC)")
    a = ap.parse_args()
    if a.sandbox_media == "trace" and (a.out_data == DATA or a.out_media == MEDIA):
        raise SystemExit("the trace variant needs explicit --out-data and --out-media")
    exported_on = a.date or date.today().isoformat()

    reg = build_registry()
    scr = Scrubber(reg.build_replacements())
    w = B.World(reg, scr)
    B.build_traces(w)
    B.load_labels(w)
    order = {c: i for i, c in enumerate(B.LIB_ORDER)}
    w.lib_order = sorted(reg.by_alias, key=lambda al: (order[reg.by_alias[al].cls], al))
    for rs in RUN_SLUGS:
        w.examples[rs] = B.run_examples(w, rs)
    credits = build_credits(reg)
    credits_by_key = {e["id"]: e for e in credits}
    for slug in sorted(reg.rules):
        w.rule_docs[slug] = B.build_rule(w, slug)
    for rs in RUN_SLUGS:
        w.run_docs[rs] = B.build_run(w, rs)
    live = B.build_live(w)
    cal = B.build_cal_doc(w)
    curated = B.build_curated(w)
    sketches = B.build_sketches(w)
    library = B.build_library(w, a.sandbox_media, credits_by_key)
    claims = build_claims()

    # ------------------------------------------------------------------ recompute-and-assert
    results: list[tuple[str, str]] = []
    results.append(("A1", C.a1_shared_rows(reg)))
    results.append(("A2", C.a2_example_counts(w)))
    if not a.skip_replay:
        results.append(("A3", C.a3_replay(w)))
    results.append(("A4", C.a4_live(w, live)))
    results.append(("A5", C.a5_calibration(w)))
    results.append(("A6", C.a6_backtest(w)))
    results.append(("A7", C.a7_boxes(w)))
    results.append(("A10", C.a10_calibration_validity(w)))
    results.append(("A11", C.a11_ranks(w)))
    if len(sketches) != 37:
        print(f"note: {len(sketches)} distinct sketches (the spec said 37 at last count)")

    docs = {"library": library, "traces": w.traces_out, "runs": w.run_docs, "rules": w.rule_docs, "live": live,
            "calibration": cal, "curated": curated, "sketches": sketches, "credits": credits, "claims": claims}
    docs = _drop_generated(docs)
    if a.sample:
        docs = _sample_filter(w, docs)
    # A8 (closure) on what will be written
    results.append(("A8", C.a8_closure(w, docs)))

    # ------------------------------------------------------------------ scrub + strict schema
    docs = {k: scr.obj(v, k) for k, v in docs.items()}
    S_lib = [S.ClipCard.model_validate(c) for c in docs["library"]]
    for t in docs["traces"].values():
        S.validate_trace(t)
    for r in docs["runs"].values():
        S.RunDoc.model_validate(r)
    for r in docs["rules"].values():
        S.RuleDoc.model_validate(r).check_ast()
    S.LiveDoc.model_validate(docs["live"])
    S.CalDoc.model_validate(docs["calibration"])
    S.CuratedDoc.model_validate(docs["curated"])
    for s in docs["sketches"]:
        S.Sketch.model_validate(s)
    for e in docs["credits"]:
        S.CreditEntry.model_validate(e)
    S.ClaimsDoc.model_validate(docs["claims"])
    if len({c.alias for c in S_lib}) != len(S_lib):
        raise ExportError("duplicate alias in the library")

    # ------------------------------------------------------------------ write
    out_data, out_media = a.out_data, a.out_media
    _clear(out_data, out_media)
    write_json(out_data / "library.json", docs["library"])
    for alias, t in docs["traces"].items():
        write_json(out_data / "traces" / f"{alias}.json", t)
    for slug, r in docs["runs"].items():
        write_json(out_data / "runs" / f"{slug}.json", r)
    for slug, r in docs["rules"].items():
        write_json(out_data / "rules" / f"{slug}.json", r)
    write_json(out_data / "live.json", docs["live"], indent=1)
    write_json(out_data / "calibration" / "package.json", docs["calibration"], indent=1)
    write_json(out_data / "credits.json", docs["credits"], indent=1)
    write_json(out_data / "claims.json", docs["claims"], indent=1)
    write_json(out_data / "lab" / "curated.json", docs["curated"], indent=1)
    write_json(out_data / "lab" / "sketches.json", docs["sketches"])

    media_log = {}
    if not a.skip_media:
        for card in docs["library"]:
            if card["media"] != "frames":
                continue
            rec = reg.by_alias[card["alias"]]
            media_log[card["alias"]] = make_media(card["alias"], rec.path, card["sheet_times_ms"], out_media)
        stats = check_media_dir(out_media)
    else:
        stats = {"files": 0, "bytes": 0}

    # A9: every media file maps to a library clip with a credits entry that has evidence; sheet times = trace times
    cards = {c["alias"]: c for c in docs["library"]}
    by_key = {e["id"]: e for e in docs["credits"]}
    n_media = 0
    if not a.skip_media:
        for sub in ("posters", "sheets"):
            for p in sorted((out_media / sub).glob("*.webp")):
                card = cards.get(p.stem)
                if card is None or card["media"] != "frames":
                    raise ExportError(f"A9: media file without a frames-mode library clip ({sub}/{p.name})")
                ent = by_key.get(card["credit"])
                if ent is None or not ent["permission"]["evidence"].strip():
                    raise ExportError(f"A9: no credits evidence for {p.name}")
                n_media += 1
        for alias, card in cards.items():
            if card["sheet_times_ms"] != [f["t_ms"] for f in docs["traces"][alias]["frames"]]:
                raise ExportError(f"A9: sheet_times_ms of {alias} differ from the trace")
            if card["media"] == "trace_only" and ((out_media / "posters" / f"{alias}.webp").exists()
                                                  or (out_media / "sheets" / f"{alias}.webp").exists()):
                raise ExportError(f"A9: trace-only clip {alias} has media files")
        results.append(("A9", f"{n_media} media files, each mapped to a library clip with credits evidence; sheet_times_ms equal the "
                              f"trace frame times; {stats['files']} images carry no EXIF/XMP/ICC chunk and fit the byte budgets"))

    # ------------------------------------------------------------------ manifest
    files = []
    for p in sorted(out_data.rglob("*.json")):
        rel = p.relative_to(out_data).as_posix()
        if rel in NOT_EXPORTED or rel.startswith("grid/"):
            continue
        if rel.startswith("lab/") and rel not in ("lab/curated.json", "lab/sketches.json"):
            continue                                  # other streams' lab files are not part of this manifest
        files.append({"path": f"data/{rel}", "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    if out_media.exists():
        for p in sorted(out_media.rglob("*.webp")):
            files.append({"path": f"public/media/{p.relative_to(out_media).as_posix()}", "bytes": p.stat().st_size,
                          "sha256": sha256_file(p)})
    pg = {"package": 0, "vehicle": 0, "bird": 0}
    for c in reg.clips.values():
        if c.cls in ("pg_package", "pg_vehicle", "pg_bird"):
            pg[c.cls.split("_")[1]] += 1
    manifest = {
        "schema": SCHEMA, "exported_on": exported_on, "engine_commit": engine_commit(),
        "sources": _source_counts(reg),
        "asserts": [{"id": i, "ok": True, "detail": _published_detail(d)} for i, d in sorted(results, key=lambda t: int(t[0][1:]))],
        "counts": {"library": len(docs["library"]), "playground": pg},
        "files": files,
    }
    S.Manifest.model_validate(manifest)
    write_json(out_data / "manifest.json", scr.obj(manifest, "manifest"), indent=1)

    # size budgets (SPEC 4.7): data excluding lab/ <= 1.5 MB raw, media <= 25 MB; posters and sheets are checked per file
    data_bytes = sum(p.stat().st_size for p in out_data.rglob("*.json")
                     if p.relative_to(out_data).parts[0] not in ("lab", "grid")
                     and p.relative_to(out_data).as_posix() not in NOT_EXPORTED)
    media_bytes = sum(p.stat().st_size for p in out_media.rglob("*.webp")) if out_media.exists() else 0
    if data_bytes > 1_500_000:
        raise ExportError(f"data/ (excluding lab/) is {data_bytes} bytes; the budget is 1.5 MB")
    if media_bytes > 25_000_000:
        raise ExportError(f"public/media is {media_bytes} bytes; the budget is 25 MB")

    # ------------------------------------------------------------------ deny-scans on the output
    import denyscan
    n, findings = denyscan.scan([out_data] + ([out_media] if out_media.exists() else []), scr.deny)
    if findings:
        for f in findings:
            print("  HIT", f)
        raise ExportError(f"deny-scan found {len(findings)} issue(s) in the output")

    # debug copy of the alias map (outside the repo)
    import json
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "alias-map.json").write_text(json.dumps(reg.build_replacements(), indent=1), encoding="utf-8")

    lab = sum(f["bytes"] for f in files if f["path"].startswith("data/lab/"))
    print(f"export ok: {len(docs['library'])} clips, {len(docs['runs'])} runs, {len(docs['rules'])} rules; "
          f"data {data_bytes / 1024:.0f} KB excluding lab/ (budget 1500 KB; lab {lab / 1024:.0f} KB), "
          f"media {stats['files']} files {media_bytes / 1e6:.2f} MB (budget 25 MB); scan: {n} files clean")
    for i, d in sorted(results, key=lambda t: int(t[0][1:])):
        print(f"  {i}: {d}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExportError as e:
        print(f"EXPORT FAILED: {e}")
        raise SystemExit(2)
