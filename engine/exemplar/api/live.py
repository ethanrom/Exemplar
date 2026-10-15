"""Live capture: JPEG frames from the browser's WHEP `<video>` -> `ring_live` clip.

Frames are stored per session under `<data_dir>/live/<session_id>/<t_ms>.jpg`. `finish` assembles them into an
mp4 (ffmpeg, timeline = `t_ms`), makes a `ring_live` event + clip, runs fast perception and the deployed
monitors, exactly like a Ring event.

`live_facts` MonitorEvents: a fast-perception call per few frames would lag the video by 10-30 s (Bedrock
latency) and cost real money, so facts are summarised at `finish`: right after the trace is
stored (and before the monitors run) one `live_facts` event per trace frame that has facts is published, so
the Live screen's ticker fills in order and the rule monitors light up after it.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from exemplar.contracts.trace import Trace
from exemplar.store import ClipRow, EventRow, now_ms

from . import media
from .errors import ApiError, BadRequest, NotFound, short_error

if TYPE_CHECKING:  # pragma: no cover
    from .state import AppState

log = logging.getLogger("exemplar.api.live")

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_FRAMES = 20_000


def session_dir(state: "AppState", session_id: str) -> Path:
    if not SESSION_RE.match(session_id):
        raise BadRequest("session_id must match [A-Za-z0-9_-]{1,64}", "INVALID_SESSION")
    return state.data_dir / "live" / session_id


def _meta_path(d: Path) -> Path:
    return d / "meta.json"


def _read_meta(d: Path) -> dict[str, Any]:
    try:
        return json.loads(_meta_path(d).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(d: Path, meta: dict[str, Any]) -> None:
    tmp = d / "meta.json.tmp"
    tmp.write_text(json.dumps(meta), encoding="utf-8")
    tmp.replace(_meta_path(d))


def save_frame(state: "AppState", session_id: str, t_ms: int, jpeg: bytes, device_id: str | None) -> None:
    if t_ms < 0:
        raise BadRequest("t_ms must be >= 0")
    if len(jpeg) > state.config.max_frame_bytes:
        raise ApiError(413, "frame too large", "FRAME_TOO_LARGE")
    if jpeg[:2] != b"\xff\xd8":
        raise BadRequest("image must be a JPEG", "INVALID_IMAGE")
    d = session_dir(state, session_id)
    d.mkdir(parents=True, exist_ok=True)
    meta = _read_meta(d)
    if meta.get("event_id"):
        raise ApiError(409, "session already finished", "SESSION_FINISHED")
    if not meta:
        meta = {"session_id": session_id, "device_id": device_id,
                "started_at_ms": now_ms() - t_ms}      # wall-clock time of t_ms = 0
        _write_meta(d, meta)
    elif device_id and not meta.get("device_id"):
        meta["device_id"] = device_id
        _write_meta(d, meta)
    if sum(1 for _ in d.glob("*.jpg")) >= MAX_FRAMES:
        raise ApiError(413, "too many frames in this session", "TOO_MANY_FRAMES")
    (d / f"{t_ms:09d}.jpg").write_bytes(jpeg)


def frame_list(d: Path) -> list[tuple[int, Path]]:
    return sorted((int(p.stem), p) for p in d.glob("*.jpg") if p.stem.isdigit())


def register_session(state: "AppState", session_id: str) -> tuple[str, bool]:
    """Create the `ring_live` event + pending clip for a finished session. Returns (event_id, created)."""
    d = session_dir(state, session_id)
    if not d.is_dir():
        raise NotFound(f"live session {session_id}")
    meta = _read_meta(d)
    if meta.get("event_id"):
        return meta["event_id"], False
    frames = frame_list(d)
    if not frames:
        raise NotFound(f"frames of live session {session_id}")
    eid = f"live_{session_id}"
    start_ms = int(meta.get("started_at_ms") or now_ms())
    end_ms = start_ms + frames[-1][0]
    ev = EventRow(id=eid, source="ring_live", device_id=meta.get("device_id"), kind="live", sub_type=None,
                  start_ms=start_ms, end_ms=end_ms, created_at_ms=now_ms(),
                  raw_json=json.dumps({"session_id": session_id, "frames": len(frames)}))
    if state.store.events.insert(ev):
        state.store.clips.insert(ClipRow(id=eid, event_id=eid, created_at_ms=now_ms(),
                                         duration_ms=frames[-1][0], status="pending",
                                         source_ref=f"live:{session_id}"))
        state.bus.emit("event_ingested", event_id=eid, message=f"live capture, {len(frames)} frames")
    meta["event_id"] = eid
    _write_meta(d, meta)
    return eid, True


def assemble_clip(state: "AppState", session_id: str, event_id: str) -> bool:
    """frames -> mp4 + snapshot (the middle frame) -> clip ready. Blocking."""
    st = state.store
    clip = st.clips.by_event(event_id)
    if clip is None:
        return False
    if clip.status == "ready" and clip.path and Path(clip.path).is_file():
        return True
    d = session_dir(state, session_id)
    frames = frame_list(d)
    st.clips.set_status(clip.id, "downloading")
    try:
        path = state.clip_path(clip.id)
        dur = media.frames_to_mp4(frames, path)
        snap = state.snapshot_path(clip.id)
        snap.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frames[len(frames) // 2][1], snap)
        st.clips.set_media(clip.id, path=str(path), snapshot_path=str(snap), sha256=media.sha256_file(path),
                           duration_ms=dur, status="ready")
    except Exception as e:  # noqa: BLE001
        log.warning("assembling live clip %s failed: %s", session_id, short_error(e))
        st.clips.set_status(clip.id, "failed", f"assemble failed: {short_error(e)}")
        state.bus.emit("error", event_id=event_id, message=f"live clip failed: {short_error(e)}")
        return False
    state.bus.emit("clip_ready", event_id=event_id, message=f"{dur / 1000:.1f} s live capture")
    return True


def publish_live_facts(state: "AppState", event_id: str, trace: Trace) -> None:
    """Replay the trace's facts, frame by frame, as `live_facts` MonitorEvents (see module docstring)."""
    first = True
    for fr in trace.frames:
        if not fr.facts:
            continue
        state.bus.emit("live_facts", event_id=event_id,
                       facts=[{"t_ms": fr.t_ms, "pred": f.pred, "args": list(f.args), "conf": f.conf} for f in fr.facts],
                       message="summary at session finish" if first else None)
        first = False


def process_session(state: "AppState", session_id: str, event_id: str) -> None:
    """Blocking: assemble the clip, perceive it, publish facts, run the monitors."""
    if not assemble_clip(state, session_id, event_id):
        return
    clip = state.store.clips.by_event(event_id)
    if clip is not None and not state.store.traces.has_any(clip.id):
        state.processor.process_clip(clip.id, on_trace=lambda tr: publish_live_facts(state, event_id, tr))
