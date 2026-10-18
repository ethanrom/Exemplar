"""Golden files (SPEC 6.2): `<family>.jsonl.gz`, first line a meta record, then `{id, input, expect}` lines."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import gridlib as G

GOLDEN_DIR = G.SHOWCASE / "data" / "grid" / "golden"


def dumps(obj) -> str:
    return json.dumps(obj, allow_nan=False, separators=(",", ":"), ensure_ascii=False)


def write_family(family: str, generator: str, seed, records: list[dict], extra_meta: dict | None = None) -> Path:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    meta = {"family": family, "generator": generator, "engine_commit": G.engine_commit(), "seed": seed,
            "count": len(records), **(extra_meta or {})}
    path = GOLDEN_DIR / f"{family}.jsonl.gz"
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0) as gz:
        gz.write((dumps(meta) + "\n").encode("utf-8"))
        for r in records:
            gz.write((dumps(r) + "\n").encode("utf-8"))
    return path


def read_family(family: str) -> tuple[dict, list[dict]]:
    with gzip.open(GOLDEN_DIR / f"{family}.jsonl.gz", "rt", encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    return lines[0], lines[1:]
