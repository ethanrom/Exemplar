"""Trace access for the harness: cache keys, offline loading of cached traces, and the fast-perception call.

`perceive_detailed` (stream B) is the single place that talks to Bedrock.  The harness computes the same cache key
(`exemplar.perception.cache.cache_key`) so that `python -m eval.run` can read traces without a client, without ffmpeg and
without any chance of a paid call: a miss is reported, never silently filled.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from exemplar.contracts.trace import Trace, TraceContext
from exemplar.perception import cache as pcache
from exemplar.perception.pipeline import PerceptionResult, perceive_detailed
from exemplar.perception.sampling import DEFAULT_MIN_GAP_S, DEFAULT_WIDTH, MAX_FRAMES_FAST, MAX_FRAMES_STRONG

from .dataset import N_FRAMES, Window, data_dir

CONTEXT = TraceContext(sub_type=None, event_kind=None)


class MissingTrace(KeyError):
    """No cached trace for a window: run `python -m eval.precompute` first."""


def key_for(window_id: str, *, mode: str = "fast", n_frames: int = N_FRAMES, samples: int = 1) -> str:
    from exemplar.settings import get_settings
    st = get_settings()
    strong = mode == "strong"
    model_id = st.strong_model if strong else st.fast_model
    alias = (st.model_alias or "strong") if strong else "fast"
    n_req = min(n_frames, MAX_FRAMES_STRONG if strong else MAX_FRAMES_FAST)
    return pcache.cache_key(clip_id=window_id, start_s=0, dur_s=None, n_frames=n_req, min_gap_s=DEFAULT_MIN_GAP_S,
                            width=DEFAULT_WIDTH, roi=None, mode=mode, samples=samples, model_alias=alias,
                            model_fp=pcache.model_fingerprint(model_id))


def load_cached(window: Window, *, mode: str = "fast", n_frames: int = N_FRAMES, base: Optional[Path] = None) -> Optional[Trace]:
    """The cached trace for a window (context/source stamped like `perceive_detailed` does), or None on a miss."""
    hit = pcache.load(Path(base or data_dir()), key_for(window.id, mode=mode, n_frames=n_frames))
    if hit is None:
        return None
    trace, _ = hit
    return trace.model_copy(update={"context": CONTEXT, "source": window.source})


def require_cached(window: Window, **kw: Any) -> Trace:
    tr = load_cached(window, **kw)
    if tr is None:
        raise MissingTrace(window.id)
    return tr


def perceive_window(window: Window, *, client: Any = None, mode: str = "fast", n_frames: int = N_FRAMES,
                    force: bool = False) -> PerceptionResult:
    """Fast (or strong) perception of one window exactly as the pipeline would do it for an event: 16 frames, 640 px,
    no extra ROI (the MEVA clips are already cut to the per-camera ROI), source `meva` / `upload`, empty context."""
    return perceive_detailed(window.path(), clip_id=window.id, source=window.source, context=CONTEXT, mode=mode,
                             n_frames=n_frames, roi=None, client=client, force=force)
