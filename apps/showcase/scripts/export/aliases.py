"""Deterministic in-memory aliases for every original id, plus the registry of what gets exported.

The alias map is built in memory and is never written inside the repo (a debug copy may go to the scratch folder).
Runs, rules and concepts are selected by *content* (names, wording, counts), so no original id appears in this
source file: scripts/ is inside the deny-scan scope.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from common import ExportError, SNAPSHOT_KEYS, load_snapshot, posix

# ------------------------------------------------------------------------------------------- selectors
CONCEPT_NAMES = {            # slug -> (snapshot, concept name)
    "package": ("recording", "Package left on the steps"),
    "vehicle": ("recording", "vehicle enters the lot"),
    "theft": ("recording", "package theft"),
    "p2-generated": ("stills", "stills-teach-32s"),
    "run2": ("heldout", "heldout-teach-b"),
}
# Display names: the stored names of the last two are internal working names, so the export uses these.
CONCEPT_DISPLAY = {
    "p2-generated": "Package left on the steps (taught from AI-generated images)",
    "run2": "Package left on the steps (third recorded run)",
}
RUN_SLUGS = ("p1-playground", "p2-generated", "run2-identical", "vehicle", "theft-a", "theft-b")
RUN_TITLES = {
    "p1-playground": "Taught from Playground recordings",
    "p2-generated": "Taught from AI-generated images",
    "run2-identical": "Third recorded run",
    "vehicle": "Vehicle enters the lot",
    "theft-a": "Package theft, first run",
    "theft-b": "Package theft, second run",
}
RUN_SOURCE = {"p1-playground": "recording", "vehicle": "recording", "theft-a": "recording", "theft-b": "recording",
              "p2-generated": "stills", "run2-identical": "heldout"}
RUN_CONCEPT = {"p1-playground": "package", "vehicle": "vehicle", "theft-a": "theft", "theft-b": "theft",
               "p2-generated": "p2-generated", "run2-identical": "run2"}

UPLOAD_ALIASES = (
    {f"cc-frollard-{o:02d}s" for o in range(0, 85, 5)}
    | {f"cc-ringtv-fox-{o:02d}s" for o in (0, 20, 40)}
    | {f"{g}-{n}s" for g in ("gen-porch-day", "gen-steps-night", "gen-stoop-brick") for n in (20, 32)}
    | {"meva-g336-a", "meva-g336-c", "meva-g339-a", "meva-g424", "meva-g436"})

STILLS_CANDIDATE_ENGLISH = "There is a package k such that (k is on the porch or k is on the steps) continuously for at least 15 s."

FROLLARD_ID = "TfTFu8lGrwk"
FOX_ID = "MJP2iL7xLro"
GEN_STEMS = ("gen-porch-day", "gen-steps-night", "gen-stoop-brick")
GEN_DESCR = {"gen-porch-day": "porch, daytime", "gen-steps-night": "steps, night", "gen-stoop-brick": "brick stoop"}


@dataclass
class ClipRec:
    orig: str
    alias: str
    cls: str                 # pg_package | pg_vehicle | pg_bird | frollard | generated | meva | ringtv_fox
    source: str              # playground | cc_by | generated | meva
    credit: str
    title: str
    db_keys: list[str]
    event: dict[str, Any]    # allow-listed event columns only
    clip: dict[str, Any]     # allow-listed clip columns (+ path, used only to find media)
    trace: dict[str, Any]    # raw trace json (scrubbed later)
    trace_mode: str
    trace_status: str
    path: Path
    window: Optional[tuple[float, float]] = None    # (start_s, length_s) of an upload window
    sourcefile: Optional[str] = None


@dataclass
class Registry:
    snaps: dict[str, Any]
    clips: dict[str, ClipRec] = field(default_factory=dict)             # orig id -> rec
    by_alias: dict[str, ClipRec] = field(default_factory=dict)
    concepts: dict[str, dict] = field(default_factory=dict)             # slug -> {orig, snap, row}
    concept_slug: dict[str, str] = field(default_factory=dict)          # orig -> slug
    runs: dict[str, dict] = field(default_factory=dict)                 # slug -> {orig, snap, row, concept}
    run_slug: dict[str, str] = field(default_factory=dict)
    rules: dict[str, dict] = field(default_factory=dict)                # slug -> {orig, snap, row, run, rank, ...}
    rule_slug: dict[str, str] = field(default_factory=dict)
    excluded_clips: int = 0

    def alias_of(self, orig: str) -> str:
        try:
            return self.clips[orig].alias
        except KeyError:
            raise ExportError(f"clip reference does not resolve to an exported clip (alias closure): kind={_shape(orig)}")

    def build_replacements(self) -> dict[str, str]:
        """Original value -> alias for every id the scrubber may meet in a free-text string."""
        rep: dict[str, str] = {}
        for orig, rec in self.clips.items():
            rep[orig] = rec.alias
        for orig, slug in self.concept_slug.items():
            rep[orig] = slug
        for orig, slug in self.run_slug.items():
            rep[orig] = slug
        for orig, slug in self.rule_slug.items():
            rep[orig] = slug
        return rep


def _shape(s: str) -> str:
    return re.sub(r"[A-Z0-9]", "X", re.sub(r"[a-z]", "x", s))[:12]


# ------------------------------------------------------------------------------------------- helpers
def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]


def parse_source_ref(ref: str | None) -> tuple[str, float, float]:
    """(source name, start_s, length_s) from `youtube:<id>@a+b`, `<file>.mp4@a+b` or `<url>@a+b`."""
    if not ref:
        raise ExportError("upload clip without source_ref")
    m = re.match(r"^(?P<src>.+)@(?P<a>[0-9.]+)\+(?P<b>[0-9.]+)$", ref)
    if not m:
        raise ExportError("unparseable source_ref")
    return m["src"], float(m["a"]), float(m["b"])


def classify_upload(ref: str) -> Optional[tuple[str, str, str, tuple[float, float], str]]:
    """(alias, cls, credit key, window, human title) or None when the window is not part of the export."""
    src, a, b = parse_source_ref(ref)
    if src == f"youtube:{FROLLARD_ID}":
        if b != 20.0 or a % 5 != 0:
            return None
        off = int(round(a))
        return (f"cc-frollard-{off:02d}s", "frollard", "frollard", (a, b),
                f"Doorstep video, {off} to {off + 20} s")
    if src == f"youtube:{FOX_ID}":
        off = int(round(a))
        return (f"cc-ringtv-fox-{off:02d}s", "ringtv_fox", "ringtv-fox", (a, b),
                f"RingTV doorbell video, {off} to {off + 20} s")
    stem = src[:-4] if src.endswith(".mp4") else src
    for g in GEN_STEMS:
        if stem == g and b == 20.0:
            return (f"{g}-20s", "generated", "generated", (a, b), f"AI-generated image, {GEN_DESCR[g]}, 20 s")
        if stem == f"{g}-32s" and b == 32.0:
            return (f"{g}-32s", "generated", "generated", (a, b), f"AI-generated image, {GEN_DESCR[g]}, 32 s")
    m = re.match(r"^meva-(g\d+)-([a-z])$", stem)
    if m and b == 20.0:
        return (f"meva-{m[1]}-{m[2]}", "meva", "meva", (a, b), f"MEVA parking lot {m[1].upper()}, clip {m[2]}")
    m = re.match(r"^vehicle_stop-(G\d+)-", stem)
    if m:
        return (f"meva-{m[1].lower()}", "meva", "meva", (a, b), f"MEVA parking lot {m[1]}")
    return None


def upload_home(alias: str, cls: str) -> str:
    """The snapshot whose run used (and whose trace perceived) this upload window."""
    if cls == "frollard":
        return "recording"
    if cls == "generated":
        return "heldout" if alias.endswith("-20s") else "stills"
    if cls == "meva":
        return "stills" if alias in ("meva-g424", "meva-g436") else "heldout"
    return "heldout"                      # fox


def playground_class(duration_ms: int) -> str:
    if 31000 <= duration_ms <= 32500:
        return "pg_package"
    if 21000 <= duration_ms <= 22000:
        return "pg_vehicle"
    if 39000 <= duration_ms <= 40000:
        return "pg_bird"
    raise ExportError(f"unclassifiable playground duration {duration_ms}")


_PG_PREFIX = {"pg_package": "pg-pkg", "pg_vehicle": "pg-veh", "pg_bird": "pg-bird"}
_ZONE_WORDS = {"steps": "the steps", "porch": "the porch"}


def playground_title(cls: str, n: int, trace: dict) -> str:
    zones = sorted({f["args"][1] for fr in trace.get("frames", []) for f in fr["facts"] if f["pred"] == "in_zone"})
    if cls == "pg_package":
        if "steps" in zones and "porch" in zones:
            what = "box seen on the steps and the porch"
        elif "porch" in zones:
            what = "box on the porch"
        else:
            what = "box on the steps"
    elif cls == "pg_vehicle":
        what = "cars in a parking lot"
    else:
        what = "birds at snowy feeders"
    return f"Playground recording {n:02d}: {what}"


# ------------------------------------------------------------------------------------------- registry
def build_registry() -> Registry:
    snaps = {k: load_snapshot(k) for k in SNAPSHOT_KEYS}
    reg = Registry(snaps=snaps)
    _build_concepts_runs(reg)
    _build_clips(reg)
    _build_rules(reg)
    return reg


def _build_concepts_runs(reg: Registry) -> None:
    for slug, (snap, name) in CONCEPT_NAMES.items():
        rows = _rows(reg.snaps[snap], "select id,name,nl_hint,alpha from concepts where name=?", (name,))
        if len(rows) != 1:
            raise ExportError(f"concept selector for {slug} matched {len(rows)} rows")
        row = rows[0]
        reg.concepts[slug] = {"orig": row["id"], "snap": snap, "row": row}
        reg.concept_slug[row["id"]] = slug
    # the other concepts of the probe databases are never exported but must still resolve to *something* in a
    # free-text scrub; they are not referenced by any exported object, so nothing to alias.

    for run_slug in RUN_SLUGS:
        snap, cslug = RUN_SOURCE[run_slug], RUN_CONCEPT[run_slug]
        cid = reg.concepts[cslug]["orig"]
        runs = _rows(reg.snaps[snap], "select id,concept_id,status,error,started_at_ms,finished_at_ms from runs "
                     "where concept_id=? and status='done' order by started_at_ms", (cid,))
        if run_slug == "theft-a":
            row = runs[0]
        elif run_slug == "theft-b":
            row = runs[1]
        elif run_slug == "p2-generated":
            row = runs[0]                      # the earlier of the concept's two runs
        else:
            if len(runs) != 1:
                raise ExportError(f"run selector for {run_slug} matched {len(runs)} runs")
            row = runs[0]
        reg.runs[run_slug] = {"orig": row["id"], "snap": snap, "row": row, "concept": cslug}
        reg.run_slug[row["id"]] = run_slug


def _build_clips(reg: Registry) -> None:
    """Union of exported clips across the three snapshots. A clip present in several snapshots must be identical (A1)."""
    seen: dict[str, dict] = {}
    for key in SNAPSHOT_KEYS:
        db = reg.snaps[key]
        for r in db.execute("""select e.id eid, e.source, e.kind, e.sub_type, e.start_ms, e.end_ms,
                                      c.id cid, c.duration_ms, c.attribution, c.source_ref, c.path,
                                      t.mode tmode, t.status tstatus, t.trace_json
                               from events e join clips c on c.event_id = e.id
                               join v_primary_trace t on t.clip_id = c.id"""):
            r = dict(r)
            cid = r["cid"]
            if r["eid"] != cid:
                raise ExportError("event id and clip id differ (unexpected)")
            info = None
            if r["source"] != "ring":
                info = classify_upload(r["source_ref"])
                if info is None or info[0] not in UPLOAD_ALIASES:
                    reg.excluded_clips += 1
                    continue
                home = upload_home(info[0], info[1])
                if key != home and info[1] != "frollard":
                    # the same window was perceived again in another snapshot: only the home snapshot's trace is
                    # the one the run that used the clip saw
                    continue
            if cid in seen:
                if seen[cid]["cmp"] != _cmp_row(r):
                    raise ExportError(f"A1: clip rows differ across snapshots ({seen[cid]['keys'][0]} vs {key})")
                seen[cid]["keys"].append(key)
                continue
            seen[cid] = {"cmp": _cmp_row(r), "row": r, "keys": [key], "info": info}
    pg = sorted((v for v in seen.values() if v["row"]["source"] == "ring"), key=lambda v: v["row"]["start_ms"])
    counters = {"pg_package": 0, "pg_vehicle": 0, "pg_bird": 0}
    for v in pg:
        r = v["row"]
        cls = playground_class(r["duration_ms"])
        counters[cls] += 1
        n = counters[cls]
        alias = f"{_PG_PREFIX[cls]}-{n:02d}"
        trace = json.loads(r["trace_json"])
        credit = "playground-frollard" if cls == "pg_package" else "playground-sandbox"
        _add_clip(reg, r, v["keys"], alias, cls, "playground", credit, playground_title(cls, n, trace), None)
    for v in sorted((v for v in seen.values() if v["row"]["source"] != "ring"), key=lambda v: v["info"][0]):
        r = v["row"]
        alias, cls, credit, window, title = v["info"]
        source = {"frollard": "cc_by", "ringtv_fox": "cc_by", "generated": "generated", "meva": "meva"}[cls]
        _add_clip(reg, r, v["keys"], alias, cls, source, credit, title, window)
    if counters != {"pg_package": 20, "pg_vehicle": 6, "pg_bird": 7}:
        raise ExportError(f"A6: playground classes are {counters}, expected 20/6/7")
    missing = UPLOAD_ALIASES - set(reg.by_alias)
    if missing:
        raise ExportError(f"expected upload windows missing from the snapshots: {sorted(missing)}")


def _cmp_row(r: dict) -> tuple:
    return (r["source"], r["kind"], r["sub_type"], r["start_ms"], r["end_ms"], r["duration_ms"], r["attribution"],
            r["source_ref"], r["tmode"], r["tstatus"], r["trace_json"])


def _add_clip(reg, r, keys, alias, cls, source, credit, title, window):
    path = Path(r["path"]) if r["path"] else None
    if path is None or not path.is_file():
        raise ExportError(f"media file for {alias} is not readable")
    rec = ClipRec(
        orig=r["cid"], alias=alias, cls=cls, source=source, credit=credit, title=title, db_keys=list(keys),
        event={k: r[k] for k in ("source", "kind", "sub_type", "start_ms", "end_ms")},
        clip={k: r[k] for k in ("duration_ms", "attribution", "source_ref")},
        trace=json.loads(r["trace_json"]), trace_mode=r["tmode"], trace_status=r["tstatus"], path=path, window=window,
        sourcefile=None)
    if alias in reg.by_alias:
        raise ExportError(f"duplicate alias {alias}")
    reg.clips[r["cid"]] = rec
    reg.by_alias[alias] = rec


def _build_rules(reg: Registry) -> None:
    """Rules of every exported run, ranked by the run's recorded `candidates` event."""
    for run_slug, run in reg.runs.items():
        db = reg.snaps[run["snap"]]
        ev = _rows(db, "select payload_json from run_events where run_id=? and type='candidates' order by seq",
                   (run["orig"],))
        if len(ev) != 1:
            raise ExportError(f"{run_slug}: expected one candidates event, found {len(ev)}")
        ids = json.loads(ev[0]["payload_json"])["rule_ids"]
        run["candidates_orig"] = ids
        own = _rows(db, "select id from rules where run_id=?", (run["orig"],))
        own_ids = {x["id"] for x in own}
        run["own_rule_ids"] = own_ids
        for pos, rid in enumerate(ids, start=1):
            row = _rows(db, """select id,concept_id,run_id,sketch_text,dsl_text,ast_json,english,holes_json,margin,mdl,
                               violations_json,status,tau,delta,calibration_json from rules where id=?""", (rid,))
            if len(row) != 1:
                raise ExportError(f"{run_slug}: candidate rule missing from the snapshot")
            row = row[0]
            if rid in own_ids:
                reg.rules.setdefault(rid, {"orig": rid, "snap": run["snap"], "row": row, "run": run_slug,
                                           "rank": pos, "of": len(ids)})
        if own_ids - set(ids):
            raise ExportError(f"{run_slug}: a rule of the run is missing from its candidates event")
    # slugs
    by_orig = reg.rules
    package_deployed = next(r for r in by_orig.values() if r["run"] == "p1-playground" and r["row"]["status"] == "deployed")
    vehicle_deployed = next(r for r in by_orig.values() if r["run"] == "vehicle" and r["row"]["status"] == "deployed")
    stills_cand = [r for r in by_orig.values() if r["run"] == "p2-generated" and r["row"]["english"] == STILLS_CANDIDATE_ENGLISH]
    run2_same = [r for r in by_orig.values() if r["run"] == "run2-identical" and r["row"]["dsl_text"] == package_deployed["row"]["dsl_text"]]
    if len(stills_cand) != 1 or len(run2_same) != 1:
        raise ExportError("stills-candidate / run2-identical selectors did not match exactly one rule")
    special = {package_deployed["orig"]: "package-deployed", vehicle_deployed["orig"]: "vehicle-deployed",
               stills_cand[0]["orig"]: "stills-candidate", run2_same[0]["orig"]: "run2-identical"}
    retired = sorted((r for r in by_orig.values() if r["run"] == "theft-a" and r["row"]["status"] == "retired"),
                     key=lambda r: r["rank"])
    for i, r in enumerate(retired, start=1):
        special[r["orig"]] = f"theft-retired-{i}"
    for orig, r in by_orig.items():
        slug = special.get(orig) or f"{r['run']}-c{r['rank']}"
        r["slug"] = slug
        reg.rule_slug[orig] = slug
    # re-key by slug
    reg.rules = {r["slug"]: r for r in by_orig.values()}
    if len(reg.rules) != len(by_orig):
        raise ExportError("rule slug collision")
