"""Shared helpers of the Lab-grid scripts: read-only DB access, clip aliases (SPEC 4.3), the curated clips (SPEC 4.5),
the recorded sketch bank and the label-combination arithmetic.

Everything here uses the real engine (`exemplar.*`) and never calls a model.  Original ids stay in memory: they are
never printed to a file or written to the repo, only the aliases are.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
WT = HERE.parents[3]                                  # worktree root (apps/showcase/scripts/grid -> 4 levels up)
SHOWCASE = WT / "apps" / "showcase"
ENGINE = WT / "engine"
for p in (ENGINE, ENGINE / "tests" / "synth", ENGINE / "tests" / "dsl"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

def db_dir() -> Path:
    """Folder with the read-only DB snapshots `recording.sqlite3`, `stills.sqlite3` and `heldout.sqlite3`."""
    d = os.environ.get("SHOWCASE_DB_DIR")
    if not d:
        raise SystemExit("set SHOWCASE_DB_DIR to the folder holding recording/stills/heldout .sqlite3")
    return Path(d)


def work_dir() -> Path:
    """Scratch folder for the raw engine results, tie counts and logs (never inside the repo)."""
    d = Path(os.environ.get("SHOWCASE_WORK_DIR") or Path(tempfile.gettempdir()) / "showcase-grid-work")
    d.mkdir(parents=True, exist_ok=True)
    return d

from exemplar.contracts.trace import Trace            # noqa: E402

# ----------------------------------------------------------------------------- constants (SPEC 4.5)
WEIGHT = 3.0
K_TOP = 6
SOLVE_TIMEOUT_S = 60
N_CLIPS = 8
SLOTS = 3 ** N_CLIPS                                  # 6561

CURATED = [   # clip aliases, bit order (SPEC 4.5)
    "pg-pkg-01", "pg-pkg-07", "pg-veh-01", "pg-bird-01", "cc-frollard-00s", "cc-frollard-15s", "cc-frollard-35s",
    "gen-porch-day-32s",
]
EXPECTED_DEFAULT = ["pos", "pos", "neg", "neg", "pos", None, "neg", "pos"]

# concepts by their public name; runs by concept and start time (SPEC 4.1, 4.3)
PACKAGE_CONCEPT_NAME = "Package left on the steps"
P2_CONCEPT_NAME = "stills-teach-32s"
RUN2_CONCEPT_NAME = "heldout-teach-b"
VEHICLE_CONCEPT_NAME = "vehicle enters the lot"
THEFT_CONCEPT_NAME = "package theft"


def open_ro(key: str) -> sqlite3.Connection:
    """Read-only snapshot: the SPEC 0 pattern (`mode=ro` URI, backup into memory)."""
    p = db_dir() / f"{key}.sqlite3"
    src = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:")
    src.backup(db)
    src.close()
    return db


def concept_id(db: sqlite3.Connection, name: str) -> str:
    rows = db.execute("select id from concepts where name = ?", (name,)).fetchall()
    if len(rows) != 1:
        raise AssertionError(f"expected exactly one concept named {name!r}, found {len(rows)}")
    return rows[0][0]


def _runs_of(db: sqlite3.Connection, name: str) -> list[str]:
    cid = concept_id(db, name)
    return [r[0] for r in db.execute("select id from runs where concept_id = ? order by started_at_ms", (cid,))]


_RUNS_CACHE: list[tuple[str, str, str]] = []


def runs() -> list[tuple[str, str, str]]:
    """(slug, DB key, run id) of the six exported runs, in the order their sketches are first seen by `sketch_bank`:
    P1 (the recorded session), P2 (the stills session, its first run), Run 2, the vehicle run and the two theft runs
    (by start time)."""
    if not _RUNS_CACHE:
        rec, sti, hel = open_ro("recording"), open_ro("stills"), open_ro("heldout")
        pk = _runs_of(rec, PACKAGE_CONCEPT_NAME)
        p2 = _runs_of(sti, P2_CONCEPT_NAME)
        r2 = _runs_of(hel, RUN2_CONCEPT_NAME)
        veh = _runs_of(rec, VEHICLE_CONCEPT_NAME)
        theft = _runs_of(rec, THEFT_CONCEPT_NAME)
        assert len(pk) == 1 and len(veh) == 1 and len(r2) == 1 and len(theft) == 2 and len(p2) >= 1, (len(pk), len(veh), len(r2), len(theft), len(p2))
        _RUNS_CACHE.extend([("p1-playground", "recording", pk[0]), ("p2-generated", "stills", p2[0]),
                            ("run2-identical", "heldout", r2[0]), ("vehicle", "recording", veh[0]),
                            ("theft-a", "recording", theft[0]), ("theft-b", "recording", theft[1])])
        for d in (rec, sti, hel):
            d.close()
    return list(_RUNS_CACHE)


# ----------------------------------------------------------------------------- aliases (SPEC 4.3)
def _class_of_duration(ms: int) -> str:
    if 31_000 <= ms <= 32_500:
        return "pkg"
    if 21_000 <= ms <= 22_500:
        return "veh"
    if 38_500 <= ms <= 40_000:
        return "bird"
    raise ValueError(f"unclassifiable Playground duration {ms} ms")


def playground_aliases(db: sqlite3.Connection) -> dict[str, str]:
    """clip id -> `pg-pkg-NN` / `pg-veh-NN` / `pg-bird-NN`, numbered by start_ms within each class; counts 20/6/7."""
    rows = db.execute("select c.id, c.duration_ms, e.start_ms from events e join clips c on c.event_id = e.id "
                      "where e.source = 'ring' order by e.start_ms").fetchall()
    out: dict[str, str] = {}
    n = {"pkg": 0, "veh": 0, "bird": 0}
    for cid, dur, _ in rows:
        cls = _class_of_duration(dur)
        n[cls] += 1
        out[cid] = f"pg-{cls}-{n[cls]:02d}"
    if (n["pkg"], n["veh"], n["bird"]) != (20, 6, 7):
        raise AssertionError(f"Playground class counts {n} != 20/6/7 (A6)")
    return out


def upload_alias(source_ref: str) -> Optional[str]:
    """Alias of an upload window from its source_ref (None: not part of the library)."""
    m = re.fullmatch(r"youtube:TfTFu8lGrwk@(\d+)\.0\+20\.0", source_ref)
    if m:
        return f"cc-frollard-{int(m.group(1)):02d}s"
    m = re.fullmatch(r"youtube:MJP2iL7xLro@(\d+)\.0\+20\.0", source_ref)
    if m:
        return f"cc-ringtv-fox-{int(m.group(1)):02d}s"
    m = re.fullmatch(r"(gen-[a-z]+-[a-z]+)\.mp4@0\.0\+20\.0", source_ref)          # the plain 20 s generated stills
    if m:
        return f"{m.group(1)}-20s"
    m = re.fullmatch(r"(gen-[a-z]+-[a-z]+)-32s\.mp4@0\.0\+32\.0", source_ref)       # the full 32 s window
    if m:
        return f"{m.group(1)}-32s"
    m = re.fullmatch(r"(meva-g\d+-[a-z])\.mp4@0\.0\+20\.0", source_ref)
    if m:
        return m.group(1)
    m = re.fullmatch(r"vehicle_stop-(G\d+)-\d+-\d+-neg\.mp4@.*", source_ref)
    if m:
        return f"meva-{m.group(1).lower()}"
    return None


# ----------------------------------------------------------------------------- the library
@dataclass
class LibClip:
    alias: str
    db: str
    clip_id: str
    trace: Trace          # clip_id is the original id; never written out


def _primary_trace(db: sqlite3.Connection, clip_id: str) -> Trace:
    row = db.execute("select trace_json from v_primary_trace where clip_id = ?", (clip_id,)).fetchone()
    if row is None:
        raise KeyError("no trace")
    return Trace.model_validate_json(row[0])


def library() -> list[LibClip]:
    """Every library clip (SPEC 4.1): the 50 `recording` clips, plus the 20 s generated stills, the MEVA and RingTV fox
    windows of `heldout`, plus the 32 s generated stills and MEVA G424/G436 of `stills`.  Order: Playground
    (pkg, veh, bird), frollard by offset, generated, MEVA, fox."""
    out: dict[str, LibClip] = {}
    rec = open_ro("recording")
    pg = playground_aliases(rec)
    for cid, alias in pg.items():
        out[alias] = LibClip(alias, "recording", cid, _primary_trace(rec, cid))
    for cid, sref in rec.execute("select c.id, c.source_ref from clips c join events e on e.id = c.event_id "
                                 "where e.source = 'upload'").fetchall():
        a = upload_alias(sref)
        if a is None:
            raise AssertionError("unexpected upload window in the recording DB")
        out[a] = LibClip(a, "recording", cid, _primary_trace(rec, cid))
    for key in ("heldout", "stills"):
        db = open_ro(key)
        for cid, sref in db.execute("select c.id, c.source_ref from clips c join events e on e.id = c.event_id "
                                    "where e.source = 'upload' order by e.start_ms").fetchall():
            a = upload_alias(sref)
            if a is None or a in out:
                continue
            if key == "stills" and not (a.startswith("gen-") and a.endswith("-32s") or a in ("meva-g424", "meva-g436")):
                continue
            if key == "heldout" and re.fullmatch(r"cc-frollard-\d+s", a):
                continue
            out[a] = LibClip(a, key, cid, _primary_trace(db, cid))
        db.close()
    rec.close()

    def order(alias: str) -> tuple:
        for i, pre in enumerate(("pg-pkg", "pg-veh", "pg-bird", "cc-frollard", "gen-", "meva-", "cc-ringtv-fox")):
            if alias.startswith(pre):
                return (i, alias)
        raise AssertionError(alias)

    return [out[a] for a in sorted(out, key=order)]


def curated(lib: list[LibClip]) -> list[LibClip]:
    by_alias = {c.alias: c for c in lib}
    out = []
    for alias in CURATED:
        out.append(by_alias[alias])
    return out


def default_states(cur: list[LibClip]) -> list[Optional[str]]:
    """Recorded labels only (provenance example or active): the package concept for clips 0-6, the P2 concept for
    clip 7."""
    out: list[Optional[str]] = []
    dbs = {k: open_ro(k) for k in ("recording", "stills")}
    for i, c in enumerate(cur):
        concept, db = ((concept_id(dbs["stills"], P2_CONCEPT_NAME), dbs["stills"]) if i == 7
                       else (concept_id(dbs["recording"], PACKAGE_CONCEPT_NAME), dbs["recording"]))
        row = db.execute("select value, provenance from labels where concept_id = ? and clip_id = ?",
                         (concept, c.clip_id)).fetchone()
        out.append(row[0] if row and row[1] in ("example", "active") else None)
    if out != EXPECTED_DEFAULT:
        raise AssertionError(f"default states {out} != {EXPECTED_DEFAULT}")
    return out


# ----------------------------------------------------------------------------- the sketch bank
def sketch_bank() -> list[dict]:
    """Every distinct `sketch_proposed` text of the six exported runs in first-appearance order (SPEC 4.4)."""
    from exemplar.contracts.dsl_ast import holes as ast_holes
    from exemplar.dsl import parse
    dbs: dict[str, sqlite3.Connection] = {}
    bank: dict[str, dict] = {}
    for slug, key, rid in runs():
        db = dbs.setdefault(key, open_ro(key))
        for (pj,) in db.execute("select payload_json from run_events where run_id = ? and type = 'sketch_proposed' "
                                "order by seq", (rid,)):
            text = json.loads(pj)["sketch"]
            e = bank.get(text)
            if e is None:
                e = bank[text] = {"id": len(bank), "text": text, "holes": ast_holes(parse(text)), "from_runs": []}
            if slug not in e["from_runs"]:
                e["from_runs"].append(slug)
    return list(bank.values())


def canonical_bank() -> list[dict]:
    """The sketch bank in the order of the data export's `lab/sketches.json` (the file the Lab ships): the same 37 texts as
    `sketch_bank()` (which is the order the raw engine results were computed in), with the export's ids and `from_runs`.
    Order of preference: the merged data tree, the `stream/showcase` branch, this track's committed copy."""
    raw = sketch_bank()
    by_text = {b["text"]: b for b in raw}
    src = None
    p = SHOWCASE / "data" / "lab" / "sketches.json"
    if p.exists():
        src = json.loads(p.read_text(encoding="utf-8"))
    else:
        r = subprocess.run(["git", "-C", str(WT), "show", "stream/showcase:apps/showcase/data/lab/sketches.json"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            src = json.loads(r.stdout)
        elif (SHOWCASE / "data" / "grid" / "sketches.json").exists():
            src = json.loads((SHOWCASE / "data" / "grid" / "sketches.json").read_text(encoding="utf-8"))
    if src is None:
        return [dict(b, raw_id=b["id"]) for b in raw]
    if sorted(x["text"] for x in src) != sorted(by_text):
        raise AssertionError("the exported sketch bank and the recorded runs disagree on the set of sketches")
    out = []
    for i, x in enumerate(src):
        if x["id"] != i:
            raise AssertionError("exported sketch ids must be positions")
        b = by_text[x["text"]]
        out.append({"id": i, "text": x["text"], "holes": b["holes"], "from_runs": x["from_runs"], "raw_id": b["id"]})
    return out


def canonical_library_order() -> Optional[list[str]]:
    """Clip aliases in the order of the data export's `library.json` (None when it is not available)."""
    p = SHOWCASE / "data" / "library.json"
    if p.exists():
        return [c["alias"] for c in json.loads(p.read_text(encoding="utf-8"))]
    r = subprocess.run(["git", "-C", str(WT), "show", "stream/showcase:apps/showcase/data/library.json"],
                       capture_output=True, text=True, encoding="utf-8")
    return [c["alias"] for c in json.loads(r.stdout)] if r.returncode == 0 else None


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def trace_digest(trace_dict: dict) -> str:
    """SHA-256 of the solver-relevant part of a trace (alias-independent): duration, status, entities, frames and the
    two context fields the DSL reads.  Works on an engine `Trace.model_dump(mode='json')` and on a scrubbed exported
    trace alike."""
    ctx = trace_dict.get("context") or {}
    core = {"duration_ms": trace_dict["duration_ms"], "status": trace_dict["status"],
            "entities": trace_dict["entities"], "frames": trace_dict["frames"],
            "context": {"sub_type": ctx.get("sub_type"), "local_hour": ctx.get("local_hour")}}
    return sha256_json(core)


def engine_commit() -> str:
    return subprocess.run(["git", "-C", str(WT), "log", "-1", "--format=%H", "--", "engine"], capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout.strip()


# ----------------------------------------------------------------------------- combinations
def decode_slot(slot: int) -> list[int]:
    """Base-3 digits, clip 0 least significant: 0 not used, 1 yes, 2 no."""
    out = []
    for _ in range(N_CLIPS):
        out.append(slot % 3)
        slot //= 3
    return out


def encode_slot(states: list[int]) -> int:
    return sum(s * 3 ** i for i, s in enumerate(states))


def valid_slot(slot: int) -> bool:
    st = decode_slot(slot)
    return 1 in st and 2 in st


VALID_SLOTS = [s for s in range(SLOTS) if valid_slot(s)]
