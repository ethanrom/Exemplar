"""On-disk trace cache: `<data_dir>/cache/traces/<key>.json`.

The key hashes the *identity* of a perception request — clip id, window, sampling parameters, ROI, mode,
samples, PROMPT_VERSION, model alias — and deliberately **not** the clip bytes: Ring re-renders the watermark
(`Generated-At`) on every download, so the bytes of the same event differ run to run.  A model
fingerprint (8 hex chars of sha256 of the Bedrock model id — never the id itself) is mixed in so that pointing
`.env` at a different model invalidates old entries even if the alias string stays the same.

Failed traces (`perception_failed`) are never cached, so a re-run gets another chance.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Sequence

from exemplar.contracts.trace import Trace

from .prompt import PROMPT_VERSION


def _ms(x: Optional[float]) -> Optional[int]:
    return None if x is None else int(round(x * 1000))


def model_fingerprint(model_id: Optional[str]) -> str:
    return hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:8] if model_id else "none"


def cache_key(*, clip_id: str, start_s: float = 0, dur_s: Optional[float] = None, n_frames: int, min_gap_s: float,
              width: int, roi: Optional[Sequence[int]], mode: str, samples: int, model_alias: Optional[str],
              model_fp: str = "none") -> str:
    ident: dict[str, Any] = {
        "clip_id": clip_id, "window_ms": [_ms(start_s), _ms(dur_s)],
        "sampling": {"n": n_frames, "min_gap_ms": _ms(min_gap_s), "width": width},
        "roi": list(roi) if roi else None, "mode": mode, "samples": samples,
        "prompt_version": PROMPT_VERSION, "model_alias": model_alias, "model_fp": model_fp,
    }
    return hashlib.sha256(json.dumps(ident, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def cache_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "cache" / "traces"


def load(data_dir: Path, key: str) -> Optional[tuple[Trace, dict[str, Any]]]:
    """(trace, report-dict) or None on a miss / unreadable entry."""
    p = cache_dir(data_dir) / f"{key}.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return Trace.model_validate(doc["trace"]), dict(doc.get("report") or {})
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store(data_dir: Path, key: str, trace: Trace, report: dict[str, Any]) -> Path:
    d = cache_dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{key}.json"
    doc = {"key": key, "prompt_version": PROMPT_VERSION, "trace": trace.model_dump(mode="json"), "report": report}
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest
