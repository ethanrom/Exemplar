"""Solver-relevant, scrubbed traces of the library by alias (for the TS tests and the grid header digests).

    PYTHONUTF8=1 uv run --project engine python apps/showcase/scripts/grid/export_traces.py

Keeps duration_ms, status, entities, frames and the two context fields the DSL reads (sub_type, local_hour); the clip
id is the alias.  No device id, no started_at_ms, no cache key, no summary, no original id."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gridlib as G          # noqa: E402
import golden_io as IO       # noqa: E402


def scrubbed(alias: str, trace) -> dict:
    d = trace.model_dump(mode="json")
    ctx = d.get("context") or {}
    out = {"clip_id": alias, "duration_ms": d["duration_ms"], "status": d["status"], "entities": d["entities"],
           "frames": d["frames"], "context": {"sub_type": ctx.get("sub_type"), "local_hour": ctx.get("local_hour")}}
    out["digest"] = G.trace_digest(out)
    return out


def build() -> dict[str, dict]:
    return {c.alias: scrubbed(c.alias, c.trace) for c in G.library()}


def main() -> None:
    traces = build()
    IO.GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    p = IO.GOLDEN_DIR / "traces.json.gz"
    with gzip.GzipFile(filename="", mode="wb", fileobj=p.open("wb"), mtime=0) as gz:
        gz.write(IO.dumps({"traces": traces}).encode("utf-8"))
    print(p, len(traces), p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
