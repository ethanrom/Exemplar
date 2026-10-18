"""Where the read-only inputs live on this machine.

The paths are machine-specific and must never appear in the published tree, so they are read from an untracked file
(`inputs.local.json` next to this module, gitignored) or from the file named by EXEMPLAR_SHOWCASE_INPUTS:

    { "snapshots": "<folder with recording.sqlite3, heldout.sqlite3, stills.sqlite3>",
      "main_checkout": "<main checkout holding data/ and internal/ (read-only media)>",
      "scratch": "<folder outside the repo for caches and debug copies>" }
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def load_inputs() -> dict:
    p = Path(os.environ.get("EXEMPLAR_SHOWCASE_INPUTS") or Path(__file__).with_name("inputs.local.json"))
    if not p.is_file():
        raise SystemExit("inputs.local.json is missing: see the docstring of scripts/scan/inputs.py")
    d = json.loads(p.read_text(encoding="utf-8"))
    for k in ("snapshots", "main_checkout", "scratch"):
        if k not in d:
            raise SystemExit(f"inputs file lacks {k!r}")
    return d
