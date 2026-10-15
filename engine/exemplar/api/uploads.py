"""`POST /uploads` core: third-party footage -> windows -> `upload` events + clips -> fast perception.

Windows are cut with ffmpeg (`imageio_ffmpeg`), each becomes an `upload` event with a clip carrying
`source_ref` and the CC BY `attribution`. Uploads are not Ring events: they never reach deployed monitors.
Ids are deterministic (`up_<sha256[:10]>_<start_ms>_<window_ms>`), so re-importing the same file is idempotent
and B's perception cache (keyed by clip id, not bytes) makes repeats free.
"""
from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from exemplar.store import ClipRow, EventRow, now_ms

from . import media
from .errors import short_error

if TYPE_CHECKING:  # pragma: no cover
    from .state import AppState

log = logging.getLogger("exemplar.api.uploads")


@dataclass(frozen=True)
class WindowSpec:
    event_id: str
    src: Path
    start_s: float
    length_s: float


def source_ref(filename: str, source_url: str | None, start_s: float, length_s: float) -> str:
    """e.g. `youtube:TfTFu8lGrwk@12.0+20.0` (clips.source_ref)."""
    base = filename
    if source_url:
        u = urlparse(source_url)
        vid = None
        if u.hostname and "youtube.com" in u.hostname:
            vid = (parse_qs(u.query).get("v") or [None])[0]
        elif u.hostname == "youtu.be":
            vid = u.path.strip("/") or None
        base = f"youtube:{vid}" if vid else source_url
    return f"{base}@{start_s:.1f}+{length_s:.1f}"


def save_source(state: "AppState", tmp_path: Path, filename: str) -> tuple[Path, str]:
    """Move an uploaded file to `uploads/<sha256[:10]><ext>`; returns (path, sha256 hex)."""
    sha = media.sha256_file(tmp_path)
    ext = re.sub(r"[^A-Za-z0-9.]", "", Path(filename).suffix.lower())[:8] or ".mp4"
    dest = state.data_dir / "uploads" / f"{sha[:10]}{ext}"
    if dest.exists():
        tmp_path.unlink(missing_ok=True)
    else:
        shutil.move(str(tmp_path), dest)
    return dest, sha


def import_file(state: "AppState", path: Path) -> tuple[Path, str]:
    """Copy an existing video into `uploads/<sha256[:10]><ext>` (the seed CLI; the original stays untouched)."""
    sha = media.sha256_file(path)
    dest = state.data_dir / "uploads" / f"{sha[:10]}{path.suffix.lower() or '.mp4'}"
    if not dest.exists():
        shutil.copyfile(path, dest)
    return dest, sha


def register_upload(state: "AppState", src: Path, sha: str, *, filename: str, attribution: str,
                    source_url: str | None, window_s: float, stride_s: float,
                    base_ms: int | None = None) -> list[WindowSpec]:
    """Create the pending event + clip rows for every window of `src` (idempotent). Raises media.MediaError."""
    duration_s = media.probe_duration_ms(src) / 1000
    windows = media.plan_windows(duration_s, window_s, stride_s, state.config.max_windows)
    base = base_ms if base_ms is not None else now_ms()
    specs: list[WindowSpec] = []
    for start_s, length_s in windows:
        eid = f"up_{sha[:10]}_{int(round(start_s * 1000)):07d}_{int(round(length_s * 1000))}"
        start_ms = base + int(round(start_s * 1000))
        ev = EventRow(id=eid, source="upload", device_id=None, kind="upload", sub_type=None, start_ms=start_ms,
                      end_ms=start_ms + int(round(length_s * 1000)), created_at_ms=now_ms(),
                      raw_json=None)
        if state.store.events.insert(ev):
            state.store.clips.insert(ClipRow(
                id=eid, event_id=eid, created_at_ms=now_ms(), duration_ms=int(round(length_s * 1000)),
                source_ref=source_ref(filename, source_url, start_s, length_s), attribution=attribution,
                status="pending"))
            state.bus.emit("event_ingested", event_id=eid, message=f"upload window {start_s:.0f}-{start_s + length_s:.0f} s")
        specs.append(WindowSpec(eid, src, start_s, length_s))
    return specs


def cut_window_clip(state: "AppState", spec: WindowSpec) -> bool:
    """Cut one window + thumbnail and mark the clip ready (skips work already done). True if media is ready."""
    st = state.store
    clip = st.clips.by_event(spec.event_id)
    if clip is None:
        return False
    if clip.status == "ready" and clip.path and Path(clip.path).is_file():
        return True
    st.clips.set_status(clip.id, "downloading")
    try:
        path = state.clip_path(clip.id)
        media.cut_window(spec.src, path, spec.start_s, spec.length_s)
        snap = state.snapshot_path(clip.id)
        media.middle_frame_jpeg(path, snap, int(spec.length_s * 1000))
        st.clips.set_media(clip.id, path=str(path), snapshot_path=str(snap), sha256=media.sha256_file(path),
                           duration_ms=int(round(spec.length_s * 1000)), status="ready")
    except Exception as e:  # noqa: BLE001 - ffmpeg failure, disk full
        log.warning("cutting window %s failed: %s", spec.event_id, short_error(e))
        st.clips.set_status(clip.id, "failed", f"cut failed: {short_error(e)}")
        state.bus.emit("error", event_id=spec.event_id, message=f"cut failed: {short_error(e)}")
        return False
    state.bus.emit("clip_ready", event_id=spec.event_id, message=f"window {spec.start_s:.0f}-{spec.start_s + spec.length_s:.0f} s")
    return True


def process_window(state: "AppState", spec: WindowSpec, *, perceive: bool = True) -> None:
    """Blocking: cut the window, then (optionally) run fast perception on it."""
    if cut_window_clip(state, spec) and perceive:
        clip = state.store.clips.by_event(spec.event_id)
        if clip is not None and not state.store.traces.has_any(clip.id):
            state.processor.process_clip(clip.id, monitor=False)


def process_upload(state: "AppState", specs: list[WindowSpec], *, perceive: bool = True, workers: int = 2) -> float:
    """Blocking helper for the seed CLI: cut sequentially, perceive with `workers` threads. Returns seconds taken."""
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = []
        for spec in specs:
            if cut_window_clip(state, spec) and perceive:
                clip = state.store.clips.by_event(spec.event_id)
                if clip is not None and not state.store.traces.has_any(clip.id):
                    futs.append(pool.submit(state.processor.process_clip, clip.id, monitor=False))
        for f in futs:
            f.result()
    return time.monotonic() - t0
