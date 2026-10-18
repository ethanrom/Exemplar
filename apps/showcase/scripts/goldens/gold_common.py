"""Shared helpers for the DSL golden generators: paths, read-only DB snapshots, aliasing, JSON writing and the
publication scans. Everything here is offline: no model calls, no network, no secrets."""
from __future__ import annotations

import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOWCASE = HERE.parents[1]                       # apps/showcase
REPO = HERE.parents[3]                           # repo / worktree root
ENGINE = REPO / "engine"
GOLDEN_DIR = SHOWCASE / "lib" / "dsl" / "test" / "golden"
DB_DIR = Path(os.environ["SHOWCASE_DB_DIR"]) if "SHOWCASE_DB_DIR" in os.environ else (
    Path(REPO.anchor) / "tmp" / "showcase-work" / "db")
DB_NAMES = ("recording", "stills", "heldout")

# the engine's strategy module is imported by path (it is test code, not part of the package)
sys.path.insert(0, str(ENGINE / "tests" / "dsl"))


def engine_commit() -> str:
    """The last commit that touched engine/ (the code the goldens were produced by)."""
    out = subprocess.run(["git", "log", "-1", "--format=%H", "--", "engine"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8", check=True)
    return out.stdout.strip()


def open_snapshot(name: str) -> sqlite3.Connection:
    """In-memory copy of a database snapshot, read through a read-only URI (SPEC section 0)."""
    p = DB_DIR / f"{name}.sqlite3"
    src = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:")
    src.backup(db)
    src.close()
    return db


# --------------------------------------------------------------------------- JSON
_ESC = re.compile(r"\\\\|\\n|\\r|\\t|\\b|\\f")
_ESC_MAP = {"\\n": "\\u000a", "\\r": "\\u000d", "\\t": "\\u0009", "\\b": "\\u0008", "\\f": "\\u000c"}


def dumps(obj) -> str:
    """Strict ASCII JSON. Two choices keep the output clear of the publication scan's shapes: control-character
    escapes are spelled \\u00XX (no string ends up with a colon followed by a backslash, a Windows-path shape),
    and a key is followed by ": " (a key colon directly followed by a 4-digit time value can look like a port)."""
    s = json.dumps(obj, allow_nan=False, separators=(",", ": "), ensure_ascii=True)
    return _ESC.sub(lambda m: _ESC_MAP.get(m.group(0), m.group(0)), s)


def write_jsonl_gz(path: Path, meta: dict, rows: list[dict]) -> int:
    """First line is the meta record, then one {id, input, expect} per line. Deterministic gzip (mtime 0)."""
    meta = dict(meta)
    meta["count"] = len(rows)
    text = "\n".join([dumps(meta)] + [dumps(r) for r in rows]) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(text.encode("utf-8"))
    return len(rows)


def write_json_gz(path: Path, obj) -> None:
    text = dumps(obj) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(text.encode("utf-8"))


# --------------------------------------------------------------------------- scans (publication safety)
# Case-insensitive shape patterns of SPEC section 4.8 (Scan S), applied to the decompressed goldens.
# A "~" splits a literal so that this file does not itself contain what the scan looks for.
_SHAPES_SRC = [r"av~a1\.", r"ri~ng\.(device|history|account)", r"acc~ess_token", r"refr~esh_token", r"\bBea~rer\s",
               r"X-A~mz-", r"Signa~ture=", r"ar~n:aws", r"CLAUDE_A~WS", r"anthro~pic\.", r"clau~de-[0-9]",
               r"-v\d[:]\d", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", r"[A-Za-z][:][\\/]",
               r"kask~ara", r"Sanda~ruwan", r"/Us~ers/", r"local~host", r"127\.0\.0\.1", r"[:]87~87",
               r"\b(cn|ru|run)_[0-9a-f]{10}\b", r"\bup_[0-9a-f]{10}"]
SHAPES = [p.replace("~", "") for p in _SHAPES_SRC]
SHAPE_RE = [re.compile(p, re.I) for p in SHAPES]


class ForbiddenValues:
    """In-memory denylist of original values from the DB snapshots (event/clip/device/rule/run/concept ids and
    local paths). Never written to disk."""

    def __init__(self) -> None:
        vals: set[str] = set()
        for name in DB_NAMES:
            db = open_snapshot(name)
            for table, col in (("events", "id"), ("events", "device_id"), ("clips", "id"), ("clips", "path"),
                               ("clips", "snapshot_path"), ("concepts", "id"), ("rules", "id"), ("runs", "id"),
                               ("traces", "cache_key"), ("traces", "clip_id")):
                try:
                    for (v,) in db.execute(f"select {col} from {table}"):
                        if isinstance(v, str) and len(v) >= 6:
                            vals.add(v)
                            if col == "device_id":              # any 6+ character piece of the opaque part of an id
                                tail = v.rsplit(".", 1)[-1]          # (the Ring id prefix is shape-scanned)
                                vals.update(tail[i:i + 6] for i in range(0, len(tail) - 5))
                            if col == "id" and table == "events":
                                vals.add(v[:27])
                except sqlite3.Error:
                    pass
            db.close()
        vals.discard("")
        self.values = sorted(vals, key=len, reverse=True)

    def hits(self, text: str) -> list[str]:
        return [v for v in self.values if v in text]


def scan_text(text: str, forbidden: ForbiddenValues, label: str) -> None:
    bad = []
    for rx in SHAPE_RE:
        m = rx.search(text)
        if m:
            bad.append(f"shape {rx.pattern!r} at {m.start()}: {text[max(0, m.start() - 30):m.end() + 30]!r}")
    for v in forbidden.hits(text):
        bad.append("original value from a database snapshot (not printed)")
        break
    if bad:
        raise SystemExit(f"publication scan failed for {label}:\n  " + "\n  ".join(bad))
