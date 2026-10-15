"""In-process fan-out for SSE: thread-safe publishers (worker threads), asyncio subscribers (the event loop)."""
from __future__ import annotations

import asyncio
import itertools
import logging
import threading
import time
from collections import deque
from typing import Any, Hashable

log = logging.getLogger("exemplar.api.bus")


class Fanout:
    """Subscribers are `(loop, asyncio.Queue)` pairs per key; `publish` may be called from any thread."""

    def __init__(self, queue_size: int = 1000) -> None:
        self._lock = threading.Lock()
        self._subs: dict[Hashable, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._size = queue_size

    def subscribe(self, key: Hashable = None) -> asyncio.Queue:
        """Call from the event loop that will consume the queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=self._size)
        with self._lock:
            self._subs.setdefault(key, []).append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, key: Hashable, q: asyncio.Queue) -> None:
        with self._lock:
            subs = [s for s in self._subs.get(key, []) if s[1] is not q]
            if subs:
                self._subs[key] = subs
            else:
                self._subs.pop(key, None)

    def publish(self, key: Hashable, item: Any) -> None:
        with self._lock:
            targets = list(self._subs.get(key, ()))
        for loop, q in targets:
            try:
                loop.call_soon_threadsafe(self._put, q, item)
            except RuntimeError:        # loop closed (shutdown)
                pass

    @staticmethod
    def _put(q: asyncio.Queue, item: Any) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:       # a stalled client must not block the pipeline: drop the oldest
            try:
                q.get_nowait()
                q.put_nowait(item)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def count(self, key: Hashable = None) -> int:
        with self._lock:
            return len(self._subs.get(key, ()))


class MonitorBus:
    """MonitorEvent stream (`GET /monitor/stream`): the monitor's `on_event` plus the ingest events.

    Every event gets a monotonically increasing id (the SSE `id:`) and `at_ms`; the last `replay` events are
    kept so a reconnecting client can resume with `Last-Event-ID`.
    """

    def __init__(self, replay: int = 200) -> None:
        self._fan = Fanout()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._buf: deque[tuple[int, dict[str, Any]]] = deque(maxlen=replay)

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        ev = dict(event)
        ev.setdefault("at_ms", int(time.time() * 1000))
        if not ev.get("at_ms"):
            ev["at_ms"] = int(time.time() * 1000)
        with self._lock:
            eid = next(self._ids)
            self._buf.append((eid, ev))
        self._fan.publish(None, (eid, ev))
        return ev

    def emit(self, type_: str, **fields: Any) -> dict[str, Any]:
        return self.publish({"type": type_, **fields})

    def subscribe(self) -> asyncio.Queue:
        return self._fan.subscribe(None)

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._fan.unsubscribe(None, q)

    def replay_after(self, last_id: int) -> list[tuple[int, dict[str, Any]]]:
        with self._lock:
            return [(i, e) for i, e in self._buf if i > last_id]

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return [e for _, e in self._buf]

    @property
    def subscribers(self) -> int:
        return self._fan.count(None)


class RunHub:
    """Wake-ups for `/runs/{id}/stream`: the DB (`run_events`) is the source of truth, this only cuts latency."""

    def __init__(self) -> None:
        self._fan = Fanout(queue_size=8)

    def notify(self, run_id: str) -> None:
        self._fan.publish(run_id, 1)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        return self._fan.subscribe(run_id)

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        self._fan.unsubscribe(run_id, q)
