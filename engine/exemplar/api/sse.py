"""Server-sent events: `event: <type>`, `id: <seq>`, `data: <json>`, `event: ping` every 15 s (api.yaml)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import Request
from sse_starlette import EventSourceResponse, ServerSentEvent
from starlette.concurrency import run_in_threadpool

if TYPE_CHECKING:  # pragma: no cover
    from .state import AppState

log = logging.getLogger("exemplar.api.sse")


def last_event_id(request: Request) -> int:
    raw = request.headers.get("last-event-id") or request.query_params.get("last_event_id") or "0"
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _ping() -> ServerSentEvent:
    return ServerSentEvent(data="{}", event="ping")


def response(gen: AsyncIterator[Any], state: "AppState") -> EventSourceResponse:
    return EventSourceResponse(gen, ping=state.config.sse_ping_s, ping_message_factory=_ping,
                               headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def frame(type_: str, id_: int | str, payload: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(data=json.dumps(payload, separators=(",", ":")), event=type_, id=str(id_))


async def run_events(state: "AppState", run_id: str, after: int) -> AsyncIterator[ServerSentEvent]:
    """Replay `run_events` after `after`, then follow the run until it has finished and everything is flushed.

    The DB is the source of truth; the hub only wakes us early. Order matters: read the run status BEFORE the
    events, because the worker writes its last event before flipping the status, so "finished and no new
    events" can only be seen after every event is visible.
    """
    store = state.store
    wake = state.run_hub.subscribe(run_id)
    last = after
    try:
        yield ServerSentEvent(comment="run stream open", retry=3000)
        while True:
            run = await run_in_threadpool(store.runs.get, run_id)
            events = await run_in_threadpool(store.runs.events, run_id, last)
            for ev in events:
                last = int(ev["seq"])
                yield frame(str(ev["type"]), last, ev)
            if run is None or (run.status != "running" and not events):
                return
            if events:
                continue
            try:
                await asyncio.wait_for(wake.get(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            while not wake.empty():
                wake.get_nowait()
    finally:
        state.run_hub.unsubscribe(run_id, wake)


async def monitor_events(state: "AppState", after: int | None) -> AsyncIterator[ServerSentEvent]:
    """Live MonitorEvents. With a `Last-Event-ID` the recent buffer is replayed first."""
    q = state.bus.subscribe()
    sent = after or 0
    try:
        yield ServerSentEvent(comment="monitor stream open", retry=3000)
        if after:
            for eid, ev in state.bus.replay_after(after):
                sent = eid
                yield frame(str(ev["type"]), eid, ev)
        while True:
            eid, ev = await q.get()
            if eid <= sent:
                continue
            sent = eid
            yield frame(str(ev["type"]), eid, ev)
    finally:
        state.bus.unsubscribe(q)
