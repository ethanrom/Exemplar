"""Ring ingest (PLAN.md §2.7, phase2-interfaces H): history poller and webhook -> event row -> clip download
(clip end + 5 s, 416/425 backoff lives in stream A) -> snapshot -> fast perception -> trace -> monitor.

Playground events are `on_demand` with no `sub_type`; their `TraceContext.sub_type` is `"on_demand"`.
Webhook events keep Ring's `subType` (`motion`, `human`, `vehicle`, ...); `button_press` becomes kind/sub_type
`ding`. A poll hit that lies within `dedupe_window_ms` of a webhook event on the same device is the same
physical event and is skipped.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from exemplar.contracts.ontology import SUB_TYPES
from exemplar.ring import (IPBlockedError, MediaNotFoundError, RingAuthError, RingError, RingEvent, WebhookEvent)
from exemplar.store import ClipRow, EventRow, now_ms

from . import live, media, uploads
from .errors import short_error

if TYPE_CHECKING:  # pragma: no cover
    from .state import AppState

log = logging.getLogger("exemplar.api.ingest")

_HISTORY_KINDS = ("motion", "on_demand", "ding")


class IngestPipeline:
    def __init__(self, state: "AppState") -> None:
        self.state = state
        self._tasks: set[asyncio.Task] = set()
        self._inflight: set[str] = set()
        self._sync_lock: asyncio.Lock | None = None
        self._devices: tuple[float, list[Any]] | None = None
        self._bg: list[asyncio.Task] = []

    # ================================================================== lifecycle
    def start(self) -> None:
        """Start the background tasks inside the running loop."""
        st = self.state
        if st.config.poll_enabled:
            self._bg.append(asyncio.create_task(self._poll_loop(), name="ring-poller"))
        self._bg.append(asyncio.create_task(self._auth_watch(), name="auth-watch"))
        self._bg.append(asyncio.create_task(self.resume(), name="ingest-resume"))

    async def stop(self) -> None:
        for t in [*self._bg, *self._tasks]:
            t.cancel()
        await asyncio.gather(*self._bg, *self._tasks, return_exceptions=True)
        self._bg.clear()

    async def drain(self, timeout: float = 60.0) -> None:
        """Wait for in-flight per-event tasks (tests, seed CLI)."""
        deadline = time.monotonic() + timeout
        while self._tasks and time.monotonic() < deadline:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _spawn(self, coro: Any, name: str) -> asyncio.Task:
        t = asyncio.create_task(coro, name=name)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def resume(self) -> None:
        """After a restart: finish downloads that were interrupted and trace clips left untraced by an outage."""
        st = self.state
        try:
            for clip in st.store.clips.awaiting_download():
                self.submit(clip.event_id)
            for clip in st.store.clips.awaiting_perception():
                self._spawn(self._perceive(clip.id), f"perceive-{clip.id[:16]}")
        except Exception:  # noqa: BLE001
            log.exception("resume failed")

    # ================================================================== registration
    def register_ring_event(self, ev: RingEvent, *, device_id: str | None, sub_type: str | None = None) -> EventRow | None:
        """Insert event + pending clip for a history item. None if the event is already known."""
        st = self.state
        dev = ev.device_id or device_id
        if st.store.events.exists(ev.id):
            return None
        near = st.store.events.find_near(dev, ev.start_ms, st.config.dedupe_window_ms, "ring")
        if near is not None:
            return None
        kind = ev.event_type if ev.event_type in _HISTORY_KINDS else None
        sub = ev.sub_type or sub_type or (kind if kind in ("on_demand", "ding") else "motion" if kind == "motion" else None)
        row = EventRow(id=ev.id, source="ring", device_id=dev, kind=kind, sub_type=sub if sub in SUB_TYPES else None,
                       start_ms=ev.start_ms, end_ms=ev.end_ms, raw_json=json.dumps(dataclasses.asdict(ev)),
                       created_at_ms=now_ms())
        return self._insert(row)

    def register_webhook(self, wh: WebhookEvent) -> EventRow | None:
        """`motion_detected` / `button_press` -> event row. None for lifecycle and other notifications."""
        if wh.event_type == "motion_detected":
            kind, sub = "motion", wh.sub_type or "motion"
        elif wh.event_type == "button_press":
            kind, sub = "ding", "ding"
        else:
            return None
        start = wh.timestamp_ms or now_ms()
        row = EventRow(id=wh.event_id or wh.request_id, source="ring", device_id=wh.device_id, kind=kind,
                       sub_type=sub if sub in SUB_TYPES else None, start_ms=start, end_ms=None,
                       raw_json=json.dumps(wh.raw), created_at_ms=now_ms())
        return self._insert(row)

    def _insert(self, row: EventRow) -> EventRow | None:
        st = self.state
        if not st.store.events.insert(row):
            return None
        st.store.clips.insert(ClipRow(id=row.id, event_id=row.id, created_at_ms=now_ms(), status="pending"))
        st.bus.emit("event_ingested", event_id=row.id,
                    message=f"{row.kind or 'event'} on {(row.device_id or 'device')[-8:]}")
        return row

    def kick_sync(self) -> None:
        """Poll right now in the background (after a fresh token was pasted)."""
        if self.state.config.poll_enabled:
            async def run() -> None:
                try:
                    await self.sync_history()
                except Exception as e:  # noqa: BLE001
                    log.info("kick sync failed: %s", short_error(e))
            self._spawn(run(), "kick-sync")

    def submit_upload(self, specs: list[Any]) -> None:
        """Cut the windows of an upload one by one (CPU-bound) and trace each as soon as it exists."""
        async def run() -> None:
            loop = asyncio.get_running_loop()
            for spec in specs:
                ok = await loop.run_in_executor(self.state.executor, uploads.cut_window_clip, self.state, spec)
                clip = self.state.store.clips.by_event(spec.event_id)
                if ok and clip is not None and not self.state.store.traces.has_any(clip.id):
                    self._spawn(self._perceive(clip.id), f"perceive-{clip.id[:16]}")
        self._spawn(run(), "upload")

    def submit_live(self, session_id: str, event_id: str) -> None:
        """Assemble a finished live session into a clip, trace it, publish facts, run the monitors."""
        async def run() -> None:
            await asyncio.get_running_loop().run_in_executor(
                self.state.executor, live.process_session, self.state, session_id, event_id)
        self._spawn(run(), f"live-{session_id[:16]}")

    # ================================================================== per-event processing
    def submit(self, event_id: str) -> None:
        """Schedule clip download + perception + monitor for an event (idempotent while in flight)."""
        if event_id in self._inflight:
            return
        self._inflight.add(event_id)
        self._spawn(self._process_event(event_id), f"event-{event_id[:16]}")

    async def _process_event(self, event_id: str) -> None:
        st = self.state
        try:
            event = st.store.events.get(event_id)
            clip = st.store.clips.by_event(event_id)
            if event is None or clip is None:
                return
            if clip.status in ("pending", "downloading"):
                if not await self._download(event, clip):
                    return
            clip = st.store.clips.by_event(event_id)
            if clip and clip.status == "ready" and clip.path and not st.store.traces.has_any(clip.id):
                await self._perceive(clip.id)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("ingest of %s failed", event_id)
            st.bus.emit("error", event_id=event_id, message=f"ingest failed: {short_error(e)}")
        finally:
            self._inflight.discard(event_id)

    async def _perceive(self, clip_id: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.state.executor, self.state.processor.process_clip, clip_id)

    async def _download(self, event: EventRow, clip: ClipRow) -> bool:
        """Fetch video + snapshot through stream A's client. Returns True when the clip is ready."""
        st, cfg = self.state, self.state.config
        st.store.clips.set_status(clip.id, "downloading")
        end = event.end_ms if event.end_ms is not None else event.start_ms + int(cfg.webhook_assumed_clip_s * 1000)
        rev = RingEvent(id=event.id, event_type=event.kind or "on_demand", start_ms=event.start_ms, end_ms=end,
                        device_id=event.device_id)
        ring = st.ring()
        vid, snap = await asyncio.gather(
            ring.download_event_video(rev, event.device_id, grace_s=cfg.clip_grace_s),
            ring.download_event_snapshot(rev, event.device_id, grace_s=cfg.clip_grace_s),
            return_exceptions=True)
        if isinstance(vid, asyncio.CancelledError):
            raise vid
        if isinstance(vid, BaseException):
            self._clip_failed(event, clip, vid)
            return False
        path = st.clip_path(clip.id)
        snap_path = st.snapshot_path(clip.id)
        loop = asyncio.get_running_loop()

        def finish() -> tuple[str, str | None, str]:
            vid.write(path)
            sha = media.sha256_file(path)
            snap_ok: str | None = None
            if not isinstance(snap, BaseException):
                snap.write(snap_path)
                snap_ok = str(snap_path)
            else:                                   # the snapshot is a nicety: grab a frame from the clip instead
                try:
                    media.middle_frame_jpeg(path, snap_path)
                    snap_ok = str(snap_path)
                except Exception as e:  # noqa: BLE001
                    log.info("no snapshot for %s: %s", clip.id[:16], short_error(e))
            return str(path), snap_ok, sha

        try:
            p, s, sha = await loop.run_in_executor(st.executor, finish)
        except Exception as e:  # noqa: BLE001 - disk full, bad bytes
            self._clip_failed(event, clip, e)
            return False
        dur = vid.media_duration_ms or (event.end_ms - event.start_ms if event.end_ms is not None else None)
        st.store.clips.set_media(clip.id, path=p, snapshot_path=s, sha256=sha, duration_ms=dur, status="ready")
        st.bus.emit("clip_ready", event_id=event.id, message=f"{(dur or 0) / 1000:.1f} s clip downloaded")
        return True

    def _clip_failed(self, event: EventRow, clip: ClipRow, e: BaseException) -> None:
        st = self.state
        if isinstance(e, MediaNotFoundError):
            st.store.clips.set_status(clip.id, "not_found", f"{e.code or e.status}: {e.message}")
        else:
            code = f"{getattr(e, 'code', None) or getattr(e, 'status', None) or ''}".strip()
            st.store.clips.set_status(clip.id, "failed", f"{code + ': ' if code else ''}{getattr(e, 'message', None) or short_error(e)}")
        st.bus.emit("error", event_id=event.id, message=f"clip download failed: {short_error(e)}")

    # ================================================================== history poll
    async def devices(self, *, refresh: bool = False) -> list[Any]:
        cfg = self.state.config
        if not refresh and self._devices and time.monotonic() - self._devices[0] < cfg.device_cache_s:
            return self._devices[1]
        devs = await self.state.ring().list_devices()
        self._devices = (time.monotonic(), devs)
        for d in devs:                              # local time zone per device (location CA -> America/Los_Angeles)
            if d.id not in self.state._device_tz:
                try:
                    self.state.note_device_location(d.id, await self.state.ring().device_location(d.id))
                except RingError as e:
                    log.info("device location unavailable (%s); using %s", e.code or e.status,
                             self.state.config.default_timezone)
        return devs

    async def sync_history(self) -> int:
        """One poll: list new events for every device, register them and start their pipelines. Returns the count."""
        if self._sync_lock is None:
            self._sync_lock = asyncio.Lock()
        async with self._sync_lock:
            st, cfg = self.state, self.state.config
            ring = st.ring()
            new = 0
            for dev in await self.devices():
                latest = st.store.events.latest_start("ring", dev.id)
                since = None if latest is None else latest - 120_000    # events surface late (27-44 s on the Playground)
                found = [e async for e in ring.history(dev.id, since_ms=since)]          # newest first
                fresh = [e for e in found if not st.store.events.exists(e.id)]
                if latest is None:
                    fresh = fresh[:cfg.initial_sync_limit]
                tags: dict[str, str] = {}
                if any(e.event_type == "motion" and e.sub_type is None for e in fresh):
                    tagged = await ring.history_tagged(dev.id, since_ms=min(e.start_ms for e in fresh) - 1000)
                    tags = {t.id: t.sub_type for t in tagged if t.sub_type}
                for ev in reversed(fresh):                                                # oldest first
                    row = self.register_ring_event(ev, device_id=dev.id, sub_type=tags.get(ev.id))
                    if row is not None:
                        new += 1
                        self.submit(row.id)
            await self.resume()                  # retry downloads / perception that an outage left unfinished
            return new

    async def _poll_loop(self) -> None:
        st = self.state
        last_err: str | None = None
        while True:
            try:
                if st.auth.status().connected:
                    await self.sync_history()
                    last_err = None
            except asyncio.CancelledError:
                raise
            except IPBlockedError as e:
                st.bus.emit("error", message=f"Ring blocked this IP (406); polling stopped: {e.message}")
                log.error("Ring answered 406 (IP blocked): polling stopped")
                return
            except Exception as e:  # noqa: BLE001
                msg = short_error(e)
                if msg != last_err:
                    log.warning("history poll failed: %s", msg)
                    if not isinstance(e, RingAuthError):
                        st.bus.emit("error", message=f"history poll failed: {msg}")
                    last_err = msg
            await asyncio.sleep(st.config.poll_interval_s)

    async def _auth_watch(self) -> None:
        """`auth_expiring` MonitorEvent 5 minutes before a Playground token runs out (once per token)."""
        st = self.state
        announced: set[int] = set()
        while True:
            try:
                s = st.auth.status()
                if s.mode == "playground" and s.expires_at_ms and s.connected:
                    left = s.expires_at_ms / 1000 - time.time()
                    if 0 < left <= st.config.auth_expiring_s and s.expires_at_ms not in announced:
                        announced.add(s.expires_at_ms)
                        st.bus.emit("auth_expiring", message=f"Playground token expires in {int(left // 60)} min "
                                    f"{int(left % 60)} s - paste a fresh one")
            except Exception:  # noqa: BLE001
                log.exception("auth watch failed")
            await asyncio.sleep(st.config.auth_check_interval_s)
