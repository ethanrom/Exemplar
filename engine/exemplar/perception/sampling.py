"""Frame sampling (PLAN.md §2.1.1).

ffmpeg comes from `imageio-ffmpeg` (no system install, no ffprobe).  Frames are sampled uniformly (the
midpoints of N equal sub-windows, so the first/last frame never sit on a possibly-black boundary frame)
with **exact integer-millisecond timestamps relative to the window start** — that integer is what ends up
in `Frame.t_ms`.  The returned image is the first decodable frame at or after that time (so it can be up to
one source-frame late, ~33 ms at 30 fps; the label stays the *requested* time, as `docs/DSL.md` requires).
"""
from __future__ import annotations

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import imageio_ffmpeg

MAX_FRAMES_FAST = 24         # PLAN.md §2.1.1
MAX_FRAMES_STRONG = 32       # PLAN.md §2.1.8 / contracts.trace.MAX_FRAMES
DEFAULT_WIDTH = 640
DEFAULT_MIN_GAP_S = 0.5

ROI = tuple[int, int, int, int]      # (x, y, w, h) in source pixels


class SamplingError(RuntimeError):
    """ffmpeg could not read the clip / extract a frame."""


@dataclass(frozen=True)
class SampledFrame:
    t_ms: int        # ms from the *window* start (integer, exact)
    jpeg: bytes


@dataclass(frozen=True)
class SampledWindow:
    """Result of `sample_window`: the frames plus the window length they were taken from."""
    duration_ms: int             # length of the analysed window (becomes `Trace.duration_ms`)
    frames: tuple[SampledFrame, ...]


@dataclass(frozen=True)
class VideoInfo:
    duration_s: float
    width: Optional[int]
    height: Optional[int]


# ------------------------------------------------------------------ probing
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SIZE = re.compile(r"Stream #\d+:\d+.*?Video:.*?,\s*(\d{2,5})x(\d{2,5})")


def probe(path: str | Path) -> VideoInfo:
    """Duration (+ frame size when available) of a video, without ffprobe.

    Fast path: parse the `Duration:` header that `ffmpeg -i` prints (~50 ms).  Fallback, when the container
    has no duration (`N/A`): `imageio_ffmpeg.count_frames_and_secs`, which decodes the whole file (seconds
    for long 1080p clips) — hence not the default.
    """
    p = str(path)
    if not Path(p).is_file():
        raise SamplingError(f"clip not found: {p}")
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    text = subprocess.run([ff, "-hide_banner", "-i", p], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr
    size = _SIZE.search(text)
    w, h = (int(size.group(1)), int(size.group(2))) if size else (None, None)
    m = _DURATION.search(text)
    if m:
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    else:
        try:
            _, secs = imageio_ffmpeg.count_frames_and_secs(p)
        except Exception as e:                                     # noqa: BLE001 - surface as one error type
            raise SamplingError(f"cannot read duration of {p}: {e}") from e
    if not secs or secs <= 0:
        raise SamplingError(f"clip has no duration: {p}")
    return VideoInfo(duration_s=float(secs), width=w, height=h)


# ------------------------------------------------------------------ planning (pure)
def sample_times_ms(window_ms: int, n: int, min_gap_ms: int = 500) -> list[int]:
    """Integer-ms sample times (relative to window start) for `n` uniform samples.

    The window is cut into n_eff equal sub-windows and each sample is the (round-half-up) midpoint of its
    sub-window.  n_eff = min(n, window_ms // min_gap_ms), at least 1, so consecutive samples are at least
    `min_gap_ms` apart (rounding only ever makes gaps floor/ceil of the exact spacing).  Every time lies in
    [0, window_ms].
    """
    if window_ms <= 0:
        raise ValueError("window must be longer than 0 ms")
    if n < 1:
        raise ValueError("n must be >= 1")
    n_eff = max(1, min(n, window_ms // max(1, min_gap_ms)))
    return [(window_ms * (2 * i + 1) + n_eff) // (2 * n_eff) for i in range(n_eff)]


def window_bounds_ms(total_s: float, start_s: float = 0, dur_s: Optional[float] = None) -> tuple[int, int]:
    """(start_ms, window_ms) clipped to the clip; ValueError when the window is empty/outside the clip."""
    if start_s < 0 or (dur_s is not None and dur_s <= 0):
        raise ValueError("start_s must be >= 0 and dur_s > 0")
    total_ms = int(round(total_s * 1000))
    start_ms = int(round(start_s * 1000))
    if start_ms >= total_ms:
        raise ValueError(f"start_s={start_s} is beyond the end of the clip ({total_s:.2f}s)")
    end_ms = total_ms if dur_s is None else min(total_ms, start_ms + int(round(dur_s * 1000)))
    return start_ms, end_ms - start_ms


def check_roi(roi: Optional[ROI], info: Optional[VideoInfo] = None) -> Optional[ROI]:
    if roi is None:
        return None
    if len(roi) != 4 or any(int(v) != v for v in roi):
        raise ValueError("roi must be four integers (x, y, w, h)")
    x, y, w, h = (int(v) for v in roi)
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ValueError("roi needs x, y >= 0 and w, h > 0")
    if info and info.width and info.height and (x + w > info.width or y + h > info.height):
        raise ValueError(f"roi {(x, y, w, h)} exceeds the {info.width}x{info.height} frame")
    return (x, y, w, h)


# ------------------------------------------------------------------ extraction
def _extract_jpeg(path: str, abs_t_ms: int, roi: Optional[ROI], width: int) -> bytes:
    vf = []
    if roi:
        x, y, w, h = roi
        vf.append(f"crop={w}:{h}:{x}:{y}")
    vf.append(f"scale=min({width}\\,iw):-2")        # never upscale (MEVA crops are smaller than 640 px)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    for back_ms in (0, 300):                          # retry slightly earlier if we ran past the last frame
        t = max(0, abs_t_ms - back_ms) / 1000
        r = subprocess.run([ff, "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", ",".join(vf),
                            "-q:v", "3", "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"], capture_output=True)
        if r.returncode == 0 and r.stdout[:2] == b"\xff\xd8":
            return r.stdout
    raise SamplingError(f"no frame at t={abs_t_ms / 1000:.3f}s in {path}: {r.stderr.decode(errors='replace')[:300]}")


def sample_window(path: str | Path, n: int = 16, *, min_gap_s: float = DEFAULT_MIN_GAP_S, width: int = DEFAULT_WIDTH,
                  roi: Optional[ROI] = None, start_s: float = 0, dur_s: Optional[float] = None,
                  max_n: int = MAX_FRAMES_FAST) -> SampledWindow:
    """Like `sample_frames` but also returns the window length (needed for `Trace.duration_ms`)."""
    info = probe(path)
    roi = check_roi(roi, info)
    start_ms, window_ms = window_bounds_ms(info.duration_s, start_s, dur_s)
    times = sample_times_ms(window_ms, min(n, max_n), int(round(min_gap_s * 1000)))
    p = str(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        jpegs = list(pool.map(lambda t: _extract_jpeg(p, start_ms + t, roi, width), times))
    return SampledWindow(duration_ms=window_ms, frames=tuple(SampledFrame(t, j) for t, j in zip(times, jpegs)))


def sample_frames(path: str | Path, n: int = 16, *, min_gap_s: float = DEFAULT_MIN_GAP_S, width: int = DEFAULT_WIDTH,
                  roi: Optional[ROI] = None, start_s: float = 0, dur_s: Optional[float] = None,
                  max_n: int = MAX_FRAMES_FAST) -> list[SampledFrame]:
    """Uniformly sample JPEG frames from a window of a clip.

    - `n` is clamped to `max_n` (24 for fast mode; pass 32 for strong) and reduced for short windows so that
      samples are >= `min_gap_s` apart (a 3 s window yields at most 6 frames).
    - `t_ms` is an exact integer number of milliseconds **relative to the window start** (`start_s`).
    - `roi=(x, y, w, h)` crops in source pixels *before* scaling (MEVA uses one fixed crop per camera).
      Do not crop Ring clips — keep the watermark.
    - Frames are scaled to `width` px wide (never upscaled), aspect preserved.
    - `dur_s=None` means "to the end of the clip"; a window running past the end is clipped.
    """
    return list(sample_window(path, n, min_gap_s=min_gap_s, width=width, roi=roi, start_s=start_s, dur_s=dur_s,
                              max_n=max_n).frames)
