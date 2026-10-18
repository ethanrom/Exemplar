"""Shared helpers for the showcase export: paths, read-only database snapshots, JSON output.

Databases are opened with the exact pattern of the spec (read-only URI, copy into memory, close the source).
Nothing in this package writes a database, selects ``ring_auth`` / ``webhook_deliveries`` or selects
``events.raw_json``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scan"))
from inputs import load_inputs   # noqa: E402

# --------------------------------------------------------------------------------------------- paths
SHOWCASE = Path(__file__).resolve().parents[2]            # <repo>/apps/showcase
REPO = SHOWCASE.parents[1]                                # worktree root
DATA = SHOWCASE / "data"
MEDIA = SHOWCASE / "public" / "media"

# Read-only inputs (never written); machine-specific paths come from the untracked inputs file.
_INPUTS = load_inputs()
MAIN_CHECKOUT = Path(_INPUTS["main_checkout"])
SNAPSHOT_DIR = Path(_INPUTS["snapshots"])
SCRATCH = Path(_INPUTS["scratch"])                         # caches and debug copies live here, never in the repo

SNAPSHOT_KEYS = ("recording", "heldout", "stills")
SCHEMA = "exemplar.showcase/1"


def snapshot_path(key: str) -> Path:
    return SNAPSHOT_DIR / f"{key}.sqlite3"


def load_snapshot(key: str) -> sqlite3.Connection:
    """The spec's read-only pattern: mode=ro URI, backup into memory, close the source."""
    p = snapshot_path(key)
    src = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
    db = sqlite3.connect(":memory:")
    src.backup(db)
    src.close()
    db.row_factory = sqlite3.Row
    return db


# --------------------------------------------------------------------------------------------- json
def dumps(obj: Any, *, indent: int | None = None) -> str:
    """Deterministic JSON text (UTF-8, no NaN/Infinity, trailing newline)."""
    if indent is None:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    return json.dumps(obj, ensure_ascii=False, indent=indent, allow_nan=False) + "\n"


def write_json(path: Path, obj: Any, *, indent: int | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(obj, indent=indent)
    path.write_text(text, encoding="utf-8", newline="\n")
    return len(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def engine_commit() -> str:
    """Last commit that touched engine/ (stable across commits that only touch the showcase)."""
    out = subprocess.run(["git", "log", "-1", "--format=%H", "--", "engine"], cwd=REPO, capture_output=True,
                         text=True, encoding="utf-8")
    sha = out.stdout.strip()
    if not sha:
        raise RuntimeError("cannot determine the engine commit")
    return sha


def posix(p: str | Path) -> str:
    return str(p).replace("\\", "/")


class ExportError(RuntimeError):
    """The export must stop: an assertion, scrub or schema check failed."""
