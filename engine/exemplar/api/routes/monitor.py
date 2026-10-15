"""/monitor/*: SSE fan-out, cost meter, firings. Plus /eval/results and /health."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import metadata
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from .. import sse
from ..state import AppState
from .deps import get_state

router = APIRouter(tags=["live"])


@router.get("/health", tags=["meta"])
def health() -> dict[str, Any]:
    try:
        version = metadata.version("exemplar")
    except metadata.PackageNotFoundError:
        version = "0.1.0"
    return {"ok": True, "version": version}


@router.get("/monitor/stream")
async def stream_monitor(request: Request, st: AppState = Depends(get_state)):
    """SSE of MonitorEvents (event_ingested, clip_ready, trace_ready, live_facts, rule_fired, ...)."""
    raw = request.headers.get("last-event-id")
    return sse.response(sse.monitor_events(st, sse.last_event_id(request) if raw else None), st)


@router.get("/monitor/cost")
def get_cost(st: AppState = Depends(get_state)) -> dict[str, Any]:
    return st.cost_summary()


@router.get("/monitor/firings")
def list_firings(rule_id: str | None = None, limit: int = Query(50, ge=1, le=1000),
                 st: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    return st.store.firings.list(rule_id, limit)


@router.get("/eval/results", tags=["eval"])
def get_eval_results(st: AppState = Depends(get_state)) -> dict[str, Any]:
    """MEVA benchmark results written by `python -m eval.run` to `<data_dir>/eval/results.json`."""
    path = st.data_dir / "eval" / "results.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
            doc.setdefault("generated_at", datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
            return doc
    except (OSError, ValueError):
        pass
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "rows": []}
