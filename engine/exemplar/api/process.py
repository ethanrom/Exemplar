"""Synchronous per-clip processing shared by the HTTP pipeline, uploads, live capture and the seed CLI:

    media ready -> fast perception -> trace row (+ cost ledger unless cached) -> trace_ready
                -> Monitor.process for deployed rules (Ring-sourced events only)

Everything here is plain blocking code; async callers run it with `loop.run_in_executor`.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from exemplar.contracts.ontology import SUB_TYPES
from exemplar.contracts.trace import Trace, TraceContext
from exemplar.perception import SamplingError
from exemplar.store import EventRow

from .errors import NotAvailable, short_error
from .serialize import jsonable
from .tz import local_parts

if TYPE_CHECKING:  # pragma: no cover
    from .state import AppState

log = logging.getLogger("exemplar.api.process")

_KINDS = ("motion", "ding", "on_demand", "live", "upload")
MONITORED_SOURCES = ("ring", "ring_live")        # uploads / meva / fixtures never reach deployed monitors


@dataclass
class PerceptionOutcome:
    trace: Trace
    cached: bool
    mode: str


class Processor:
    def __init__(self, state: "AppState") -> None:
        self.state = state
        self._sem = threading.BoundedSemaphore(max(1, state.config.perception_concurrency))
        self._lock = threading.Lock()
        self._inflight: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------ context
    def context_for(self, event: EventRow) -> TraceContext:
        """`TraceContext` for an event: sub_type, event_kind, local hour/weekday, device, start."""
        hour = weekday = None
        if event.source in MONITORED_SOURCES:
            hour, weekday = local_parts(event.start_ms, self.state.tz_for_device(event.device_id))
        return TraceContext(
            sub_type=event.sub_type if event.sub_type in SUB_TYPES else None,
            event_kind=event.kind if event.kind in _KINDS else None,
            local_hour=hour, weekday=weekday, device_id=event.device_id, started_at_ms=event.start_ms)

    # ------------------------------------------------------------------ perception
    def perceive_clip(self, clip_id: str, *, mode: str = "fast", force: bool = False) -> PerceptionOutcome:
        """Run perception on a stored clip and persist the trace (+ ledger row when it actually cost something).

        Raises SamplingError (unreadable media) or whatever the backend raises; `process_clip` handles those.
        """
        st = self.state
        clip = st.store.clips.get(clip_id)
        if clip is None:
            raise KeyError(f"unknown clip {clip_id}")
        if not clip.path:
            raise ValueError(f"clip {clip_id} has no media to perceive")
        event = st.store.events.get(clip.event_id)
        assert event is not None
        ctx = self.context_for(event)
        cfg = st.config
        with self._sem:
            res = st.services.perceive(
                clip.path, clip_id=clip_id, source=event.source, context=ctx, mode=mode,
                n_frames=cfg.fast_frames if mode == "fast" else cfg.strong_frames, force=force)
        trace: Trace = res if isinstance(res, Trace) else res.trace
        cached = False if isinstance(res, Trace) else bool(getattr(res, "cached", False))
        meta = trace.perception
        st.store.traces.put(clip_id, trace, mode=mode)
        if not cached and meta is not None:                    # a cache hit cost nothing; a failed trace still did
            st.store.cost.add(f"perception_{mode}", model_alias=meta.model_alias, clip_id=clip_id,
                              tokens_in=meta.tokens_in, tokens_out=meta.tokens_out, latency_ms=meta.latency_ms)
        return PerceptionOutcome(trace, cached, mode)

    # Monitor callbacks: `Callable[[EventInput], Trace]`
    def perceive_fast(self, ev: Any) -> PerceptionOutcome:
        """Returns an object with `.trace` / `.cached` (E accepts that as well as a bare Trace; a cache hit adds
        no tokens to its cost meter)."""
        return self.perceive_clip(ev.clip_id, mode="fast")

    def perceive_strong(self, ev: Any) -> PerceptionOutcome:
        return self.perceive_clip(ev.clip_id, mode="strong")

    def process_clip(self, clip_id: str, *, monitor: bool = True,
                     on_trace: Callable[[Trace], None] | None = None) -> PerceptionOutcome | None:
        """fast perception -> trace_ready -> (on_trace) -> monitor. Never raises: problems land in `clips.error`
        + an `error` event. `on_trace` runs after the trace is stored and before the monitor sees the event."""
        st = self.state
        key = (clip_id, "fast")
        with self._lock:
            if key in self._inflight:
                return None
            self._inflight.add(key)
        try:
            clip = st.store.clips.get(clip_id)
            if clip is None:
                return None
            try:
                out = self.perceive_clip(clip_id)
            except SamplingError as e:
                st.store.clips.set_status(clip_id, "failed", f"unreadable media: {short_error(e)}")
                st.bus.emit("error", event_id=clip.event_id, message=f"clip {clip_id[:24]} unreadable: {short_error(e)}")
                return None
            except Exception as e:  # noqa: BLE001 - backend outage, missing model config, ...
                log.warning("perception failed for %s: %s", clip_id, short_error(e))
                st.store.clips.set_error(clip_id, f"perception unavailable: {short_error(e)}")
                st.bus.emit("error", event_id=clip.event_id, message=f"perception failed: {short_error(e)}")
                return None
            st.store.clips.set_error(clip_id, None)
            st.bus.emit("trace_ready", event_id=clip.event_id,
                        message=out.trace.summary or out.trace.error or out.trace.status)
            if on_trace is not None:
                try:
                    on_trace(out.trace)
                except Exception:  # noqa: BLE001
                    log.exception("on_trace hook failed for %s", clip_id)
            if monitor and out.trace.status == "ok":
                event = st.store.events.get(clip.event_id)
                if event is not None:
                    try:
                        self.run_monitor(event, out.trace)
                    except NotAvailable as e:
                        log.info("monitor skipped: %s", e.message)
                    except Exception as e:  # noqa: BLE001
                        log.exception("monitor failed for %s", event.id)
                        st.bus.emit("error", event_id=event.id, message=f"monitor failed: {short_error(e)}")
            return out
        finally:
            with self._lock:
                self._inflight.discard(key)

    # ------------------------------------------------------------------ monitor
    def event_input(self, event: EventRow, trace: Trace | None) -> Any:
        clip = self.state.store.clips.by_event(event.id)
        assert clip is not None
        cls = self.state.services.event_input_cls
        kw: dict[str, Any] = dict(event_id=event.id, clip_id=clip.id, clip_path=clip.path, sub_type=event.sub_type,
                                  device_id=event.device_id, context=self.context_for(event), trace=trace)
        # The fast trace was paid for (and ledgered) at ingest: tell the monitor so it neither perceives again nor
        # counts the tokens a second time. Older EventInput versions have no such field.
        if trace is not None and "trace_cached" in {f.name for f in dataclasses.fields(cls)}:
            kw["trace_cached"] = True
        return cls(**kw)

    def run_monitor(self, event: EventRow, trace: Trace) -> list[Any]:
        """`Monitor.process` for the deployed rules; persists every returned record that `on_firing` missed."""
        st = self.state
        if event.source not in MONITORED_SOURCES or not st.store.rules.deployed():
            return []
        monitor = st.get_monitor()
        records = list(monitor.process(self.event_input(event, trace)) or [])
        for r in records:
            if not st.store.firings.exists(r.rule_id, r.event_id):
                self.on_firing(r)
        return records

    def on_firing(self, record: Any) -> None:
        """Monitor -> store. `record.to_api()` is an api.yaml `Firing`."""
        f = jsonable(record.to_api() if hasattr(record, "to_api") else record)
        try:
            self.state.store.firings.upsert(f)
        except Exception:  # noqa: BLE001 - e.g. the rule was deleted while the event was in flight
            log.exception("could not persist firing %s", f.get("id"))

    def on_monitor_event(self, event: dict[str, Any]) -> None:
        """Monitor -> `/monitor/stream`."""
        self.state.bus.publish(jsonable(event))
