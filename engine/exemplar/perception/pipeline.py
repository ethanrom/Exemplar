"""Public perception entry points: `perceive` (-> Trace) and `perceive_detailed` (-> Trace + report)."""
from __future__ import annotations

import logging
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from exemplar.contracts.trace import PerceptionMeta, Trace, TraceContext
from exemplar.settings import get_settings

from . import cache
from .extract import SampleResult, make_client, run_sample
from .merge import merge_traces
from .normalize import failed_trace
from .sampling import (DEFAULT_MIN_GAP_S, DEFAULT_WIDTH, MAX_FRAMES_FAST, MAX_FRAMES_STRONG, ROI, check_roi,
                       sample_window)

log = logging.getLogger("exemplar.perception")

Source = Literal["ring", "ring_live", "upload", "meva", "fixture"]
MAX_SAMPLES = 3


@dataclass
class PerceptionReport:
    """What happened while producing a trace (not part of the frozen `Trace` contract; cached beside it)."""
    attempts: int = 0                                   # Converse calls made, over all samples
    dropped: dict[str, int] = field(default_factory=dict)   # harmless repairs, e.g. {"fact_unknown_entity": 2}
    retry_errors: list[str] = field(default_factory=list)   # validation errors that triggered a retry
    merge: dict[str, int] = field(default_factory=dict)     # samples>1: facts_both / facts_partial / ...
    samples_failed: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PerceptionReport":
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class PerceptionResult:
    trace: Trace
    report: PerceptionReport
    cached: bool = False        # True: nothing was spent on this call (tokens in `trace.perception` are historical)


def perceive_detailed(clip_path: str | Path, *, clip_id: str, source: Source,
                      context: TraceContext = TraceContext(), mode: Literal["fast", "strong"] = "fast",
                      n_frames: int = 16, roi: Optional[ROI] = None, start_s: float = 0, dur_s: Optional[float] = None,
                      samples: int = 1, force: bool = False, client: Any = None, width: int = DEFAULT_WIDTH,
                      min_gap_s: float = DEFAULT_MIN_GAP_S) -> PerceptionResult:
    """Same as `perceive` but also returns the `PerceptionReport` and whether the trace came from the cache."""
    if mode not in ("fast", "strong"):
        raise ValueError("mode must be 'fast' or 'strong'")
    if not 1 <= samples <= MAX_SAMPLES:
        raise ValueError(f"samples must be 1..{MAX_SAMPLES}")
    if n_frames < 1:
        raise ValueError("n_frames must be >= 1")
    strong = mode == "strong"
    max_n = MAX_FRAMES_STRONG if strong else MAX_FRAMES_FAST
    n_req = min(n_frames, max_n)
    roi = check_roi(roi)

    st = get_settings()
    model_id = st.strong_model if strong else st.fast_model
    alias = (st.model_alias or "strong") if strong else "fast"
    key = cache.cache_key(clip_id=clip_id, start_s=start_s, dur_s=dur_s, n_frames=n_req, min_gap_s=min_gap_s,
                          width=width, roi=roi, mode=mode, samples=samples, model_alias=alias,
                          model_fp=cache.model_fingerprint(model_id))
    if not force and (hit := cache.load(st.data_dir, key)):
        trace, rep = hit
        # context/source describe the caller's event, not the perception, so they are not part of the key
        trace = trace.model_copy(update={"context": context, "source": source})
        return PerceptionResult(trace, PerceptionReport.from_dict(rep), cached=True)

    if client is None:
        if not model_id:
            raise RuntimeError(f"{'CLAUDE_AWS_MODEL' if strong else 'CLAUDE_AWS_FAST_MODEL'} is not configured (.env)")
        client = make_client()
    model_id = model_id or "unset"

    t0 = time.perf_counter()
    win = sample_window(clip_path, n_req, min_gap_s=min_gap_s, width=width, roi=roi, start_s=start_s, dur_s=dur_s,
                        max_n=max_n)

    def one(_: int) -> SampleResult:
        return run_sample(client, model_id=model_id, strong=strong, model_alias=alias, frames=win.frames,
                          window_ms=win.duration_ms, clip_id=clip_id, source=source, context=context)

    if samples == 1:
        results = [one(0)]
    else:                                                   # independent samples run concurrently
        with ThreadPoolExecutor(max_workers=samples) as pool:
            results = list(pool.map(one, range(samples)))

    report = PerceptionReport(attempts=sum(r.attempts for r in results),
                              retry_errors=[e for r in results for e in r.retry_errors][:10])
    dropped: Counter = Counter()
    for r in results:
        dropped.update(r.dropped)
    ok = [r.trace for r in results if r.trace.status == "ok"]
    report.samples_failed = len(results) - len(ok)
    tokens_in, tokens_out = sum(r.tokens_in for r in results), sum(r.tokens_out for r in results)
    latency_ms = int((time.perf_counter() - t0) * 1000)
    meta = PerceptionMeta(mode=mode, model_alias=alias, n_frames=len(win.frames), samples=max(1, len(ok)),
                          tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms, cache_key=key)
    if not ok:
        trace = failed_trace(clip_id=clip_id, source=source, duration_ms=win.duration_ms, context=context, meta=meta,
                             error=results[0].trace.error or "perception failed")
    else:
        trace, stats = merge_traces(ok)
        report.merge = dict(stats)
        trace = trace.model_copy(update={"perception": meta})
    report.dropped = dict(dropped)
    if trace.status == "ok":
        cache.store(st.data_dir, key, trace, asdict(report))
    return PerceptionResult(trace, report, cached=False)


def perceive(clip_path: str | Path, *, clip_id: str, source: Source, context: TraceContext = TraceContext(),
             mode: Literal["fast", "strong"] = "fast", n_frames: int = 16, roi: Optional[ROI] = None,
             start_s: float = 0, dur_s: Optional[float] = None, samples: int = 1, force: bool = False,
             client: Any = None, width: int = DEFAULT_WIDTH, min_gap_s: float = DEFAULT_MIN_GAP_S) -> Trace:
    """Clip (window) -> symbolic `Trace`.  The one call other streams need.

    * `clip_id` / `source` / `context` are stamped onto the trace; they identify the event, not the pixels.
      `clip_id` is part of the cache key — give distinct ids to distinct windows/ROIs of a file only if you
      want them cached separately (window, ROI and sampling parameters are in the key as well).
    * `mode="fast"` uses `CLAUDE_AWS_FAST_MODEL` with up to 24 frames; `mode="strong"` uses `CLAUDE_AWS_MODEL`
      with up to 32 frames.  `n_frames` is clamped to that limit and reduced for short windows (>= 0.5 s apart).
    * `samples=k` (1..3) runs k independent extractions concurrently and merges them (see
      `merge.merge_traces`: agreement keeps the lowest confidence, one-sided facts are demoted to `low`).
    * `roi=(x, y, w, h)` crops in source pixels before scaling (MEVA); never crop Ring clips (watermark).
    * `start_s` / `dur_s` select a window; frame times and `duration_ms` are relative to the window start.
    * Results are cached under `<data_dir>/cache/traces/` (key excludes the clip bytes); `force=True` bypasses
      the lookup (and overwrites the entry).  `perception_failed` traces are not cached.
    * `client`: a bedrock-runtime client or any object with `.converse(**kw)`; default built from `.env`.
    * Model-quality problems return `Trace(status="perception_failed", error=...)` after one retry; they never
      raise.  Bad arguments raise `ValueError`; unreadable clips raise `SamplingError`; AWS/network failures raise
      `PerceptionBackendError` (model id scrubbed from the message).
    * `trace.perception` carries mode, model alias, n_frames, samples, tokens, wall-clock latency (sampling +
      model calls) and the cache key.  Nothing is written to SQLite or any cost ledger; callers record usage
      (and should skip recording when `perceive_detailed(...).cached` is True).
    """
    return perceive_detailed(clip_path, clip_id=clip_id, source=source, context=context, mode=mode,
                             n_frames=n_frames, roi=roi, start_s=start_s, dur_s=dur_s, samples=samples, force=force,
                             client=client, width=width, min_gap_s=min_gap_s).trace
