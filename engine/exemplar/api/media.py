"""ffmpeg helpers (binary from `imageio_ffmpeg`, no system install): window cutting, thumbnails, frames -> mp4."""
from __future__ import annotations

import hashlib
import re
import statistics
import subprocess
from pathlib import Path
from typing import Sequence

import imageio_ffmpeg


class MediaError(RuntimeError):
    """ffmpeg failed or the input is unreadable."""


def ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: Sequence[str], *, cwd: str | Path | None = None, timeout: float = 600.0) -> None:
    cmd = [ffmpeg_exe(), "-hide_banner", "-v", "error", "-y", *args]
    try:
        r = subprocess.run(cmd, capture_output=True, cwd=str(cwd) if cwd else None, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise MediaError(f"ffmpeg timed out after {timeout:.0f}s") from e
    if r.returncode != 0:
        raise MediaError(r.stderr.decode("utf-8", errors="replace").strip()[-400:] or f"ffmpeg exit {r.returncode}")


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def probe_duration_ms(path: str | Path) -> int:
    from exemplar.perception.sampling import SamplingError, probe
    try:
        return int(round(probe(path).duration_s * 1000))
    except SamplingError as e:
        raise MediaError(str(e)) from e


def plan_windows(duration_s: float, window_s: float, stride_s: float, max_windows: int = 200) -> list[tuple[float, float]]:
    """(start_s, length_s) windows: starts at 0, stride, 2*stride, ... while the whole window fits; a video shorter
    than `window_s` yields one window covering it."""
    if window_s <= 0 or stride_s <= 0:
        raise ValueError("window_s and stride_s must be > 0")
    if duration_s <= window_s + 1e-6:
        return [(0.0, round(duration_s, 3))]
    out: list[tuple[float, float]] = []
    start = 0.0
    while start + window_s <= duration_s + 1e-6 and len(out) < max_windows:
        out.append((round(start, 3), round(window_s, 3)))
        start += stride_s
    return out


def cut_window(src: str | Path, dst: str | Path, start_s: float, length_s: float, *, width: int = 1280) -> Path:
    """Frame-accurate H.264 cut (re-encoded, audio dropped: perception and the UI player only need video)."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    run_ffmpeg(["-ss", f"{start_s:.3f}", "-i", str(src), "-t", f"{length_s:.3f}",
                "-vf", f"scale=min({width}\\,iw):-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart", str(tmp)])
    tmp.replace(dst)
    return dst


def extract_jpeg(src: str | Path, dst: str | Path, at_s: float, *, width: int = 640) -> Path:
    """One JPEG frame (thumbnail) at `at_s`."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-ss", f"{max(0.0, at_s):.3f}", "-i", str(src), "-frames:v", "1",
                "-vf", f"scale=min({width}\\,iw):-2", "-q:v", "3", str(dst)])
    if not dst.is_file() or dst.stat().st_size == 0:
        raise MediaError(f"no frame at {at_s:.2f}s in {src}")
    return dst


def middle_frame_jpeg(src: str | Path, dst: str | Path, duration_ms: int | None = None, *, width: int = 640) -> Path:
    dur = duration_ms if duration_ms else probe_duration_ms(src)
    try:
        return extract_jpeg(src, dst, dur / 2000.0, width=width)
    except MediaError:
        return extract_jpeg(src, dst, 0.0, width=width)


_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def frames_to_mp4(frames: Sequence[tuple[int, Path]], dst: str | Path, *, fps: int = 10) -> int:
    """Assemble `(t_ms, jpeg path)` frames into a constant-frame-rate H.264 mp4 whose timeline matches `t_ms`.

    Uses the concat demuxer with per-frame durations (gaps between frames are preserved), then resamples to
    `fps`. Returns the video duration in ms.
    """
    if not frames:
        raise MediaError("no frames")
    frames = sorted(frames, key=lambda f: f[0])
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    gaps = [max(20, b[0] - a[0]) for a, b in zip(frames, frames[1:])]
    last = int(statistics.median(gaps)) if gaps else 500
    durations = [*gaps, last]
    list_path = dst.with_suffix(".concat.txt")
    lines = ["ffconcat version 1.0"]
    for (t, p), d in zip(frames, durations):
        lines.append(f"file '{Path(p).resolve().as_posix()}'")
        lines.append(f"duration {d / 1000:.3f}")
    lines.append(f"file '{Path(frames[-1][1]).resolve().as_posix()}'")      # concat quirk: last duration needs a repeat
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    try:
        run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(list_path),
                    "-vf", f"fps={fps},scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                    "-t", f"{sum(durations) / 1000:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-an", "-movflags", "+faststart",
                    str(tmp)])
        tmp.replace(dst)
    finally:
        list_path.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return sum(durations)


def safe_name(s: str, limit: int = 64) -> str:
    return _SAFE.sub("_", s)[:limit] or "x"


def file_stem(ident: str, limit: int = 64) -> str:
    """Filesystem-safe, collision-free stem for an id (Ring ids are 140+ chars; only their tails differ)."""
    safe = _SAFE.sub("_", ident)
    if safe == ident and len(ident) <= limit:
        return ident
    return f"{safe[:limit - 13]}_{hashlib.sha1(ident.encode('utf-8')).hexdigest()[:12]}"
