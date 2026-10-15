"""`python -m exemplar.perception CLIP [options]` — run perception on one clip and print a compact summary."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from exemplar.contracts.trace import Trace

from .pipeline import PerceptionResult, perceive_detailed
from .sampling import DEFAULT_MIN_GAP_S, DEFAULT_WIDTH


def parse_roi(text: str) -> tuple[int, int, int, int]:
    try:
        x, y, w, h = (int(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("roi must be x,y,w,h (four integers, source pixels)") from None
    return x, y, w, h


def format_summary(res: PerceptionResult, window_s: Optional[float] = None) -> str:
    tr, rep = res.trace, res.report
    pm = tr.perception
    lines = []
    head = (f"clip={tr.clip_id} status={tr.status} mode={pm.mode if pm else '?'} frames={pm.n_frames if pm else 0} "
            f"window={tr.duration_ms / 1000:.1f}s cached={res.cached}")
    if pm:
        head += (f" samples={pm.samples} tokens in={pm.tokens_in} out={pm.tokens_out} latency={pm.latency_ms / 1000:.1f}s"
                 f" attempts={rep.attempts}")
    lines.append(head)
    if tr.status != "ok":
        lines.append(f"ERROR: {tr.error}")
        return "\n".join(lines)
    lines.append("entities: " + (" | ".join(f"{e.id}:{e.type}[{','.join(e.attrs)}]" for e in tr.entities) or "(none)"))
    for fr in tr.frames:
        present = list(dict.fromkeys(a for f in fr.facts for a in f.args if tr.entity(a)))   # explicit or implied
        others = [f"{f.pred}({','.join(f.args)}){'' if f.conf == 'high' else '/' + f.conf}" for f in fr.facts
                  if f.pred != "present"]
        lines.append(f"  t={fr.t_ms / 1000:5.1f}s  present: {','.join(present) or '-'}  " + " ".join(others))
    lines.append(f"summary: {tr.summary}")
    if rep.dropped or rep.retry_errors or rep.merge:
        lines.append(f"normalised: {rep.dropped}  retry_errors: {rep.retry_errors[:3]}  merge: {rep.merge}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None, client: Any = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m exemplar.perception", description=__doc__)
    ap.add_argument("clip", type=Path)
    ap.add_argument("--strong", action="store_true", help="escalation mode: strong model, up to 32 frames")
    ap.add_argument("--n", type=int, default=16, help="frames to sample (<=24 fast, <=32 strong)")
    ap.add_argument("--start", type=float, default=0.0, help="window start, seconds")
    ap.add_argument("--dur", type=float, default=None, help="window length, seconds (default: to the end)")
    ap.add_argument("--roi", type=parse_roi, default=None, help="x,y,w,h crop in source pixels (not for Ring clips)")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    ap.add_argument("--min-gap", type=float, default=DEFAULT_MIN_GAP_S)
    ap.add_argument("--samples", type=int, default=1, help="self-consistency samples to merge (1..3)")
    ap.add_argument("--clip-id", default=None, help="default: <parent-dir>_<file-stem>")
    ap.add_argument("--source", default="upload", choices=["ring", "ring_live", "upload", "meva", "fixture"])
    ap.add_argument("--force", action="store_true", help="ignore the trace cache")
    ap.add_argument("--json", type=Path, default=None, metavar="FILE", help="also write the full trace JSON here")
    a = ap.parse_args(argv)
    res = perceive_detailed(a.clip, clip_id=a.clip_id or f"{a.clip.resolve().parent.name}_{a.clip.stem}", source=a.source,
                            mode="strong" if a.strong else "fast", n_frames=a.n, roi=a.roi, start_s=a.start, dur_s=a.dur,
                            samples=a.samples, force=a.force, client=client, width=a.width, min_gap_s=a.min_gap)
    print(format_summary(res))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps({"trace": res.trace.model_dump(mode="json"), "report": res.report.__dict__},
                                     indent=1), encoding="utf-8")
    return 0 if res.trace.status == "ok" else 2
