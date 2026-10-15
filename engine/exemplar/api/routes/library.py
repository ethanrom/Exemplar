"""Library: events, media, uploads."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .. import media, uploads
from ..errors import ApiError, BadRequest, NotFound
from ..serialize import event_summary, trace_text_fallback
from ..state import AppState
from .deps import get_state

log = logging.getLogger("exemplar.api.library")
router = APIRouter(tags=["library"])

Source = Literal["ring", "ring_live", "upload", "meva", "fixture"]
Labelled = Literal["any", "pos", "neg", "unlabelled"]


@router.get("/events")
def list_events(concept_id: str | None = None, source: Source | None = None, labelled: Labelled = "any",
                limit: int = Query(100, ge=1, le=500), cursor: str | None = None,
                st: AppState = Depends(get_state)) -> dict[str, Any]:
    """Newest first, keyset-paginated. `labelled` filters need a `concept_id`."""
    if concept_id is not None and st.store.concepts.get(concept_id) is None:
        raise NotFound(f"concept {concept_id}")
    if labelled != "any" and concept_id is None:
        raise BadRequest("labelled=pos|neg|unlabelled needs concept_id")
    try:
        items, nxt = st.store.events.list_view(concept_id=concept_id, source=source, labelled=labelled,
                                               limit=limit, cursor=cursor)
    except ValueError as e:
        raise BadRequest(str(e), "INVALID_CURSOR") from e
    return {"items": [event_summary(v) for v in items], "next_cursor": nxt}


@router.get("/events/{event_id}")
def get_event(event_id: str, concept_id: str | None = None, st: AppState = Depends(get_state)) -> dict[str, Any]:
    view = st.store.events.get_view(event_id, concept_id)
    if view is None:
        raise NotFound(f"event {event_id}")
    trace = st.store.traces.primary(view.clip_id)
    strong = st.store.traces.get(view.clip_id, "strong")
    text = None
    if trace is not None and trace.status == "ok":
        render = st.services.render_trace_text          # the synth renderer (what the sketch LLM sees) when available
        try:
            text = render(trace) if render else trace_text_fallback(trace)
        except Exception:  # noqa: BLE001
            log.exception("render_trace_text failed; using the fallback")
            text = trace_text_fallback(trace)
    return {**event_summary(view),
            "trace": trace.model_dump(mode="json") if trace else None,
            "strong_trace": strong.model_dump(mode="json") if strong and strong.status == "ok" else None,
            "trace_text": text}


def _file(path: str | None, media_type: str, what: str) -> FileResponse:
    if not path or not Path(path).is_file():
        raise NotFound(what)
    return FileResponse(path, media_type=media_type)


@router.get("/events/{event_id}/snapshot")
def get_snapshot(event_id: str, st: AppState = Depends(get_state)) -> FileResponse:
    view = st.store.events.get_view(event_id)
    if view is None:
        raise NotFound(f"event {event_id}")
    return _file(view.snapshot_path, "image/jpeg", f"snapshot of event {event_id}")


@router.get("/events/{event_id}/clip")
def get_clip(event_id: str, st: AppState = Depends(get_state)) -> FileResponse:
    """MP4 with HTTP Range support (Starlette's FileResponse answers 206/416)."""
    view = st.store.events.get_view(event_id)
    if view is None:
        raise NotFound(f"event {event_id}")
    return _file(view.clip_path, "video/mp4", f"clip of event {event_id}")


@router.post("/uploads", status_code=202)
async def upload_video(file: UploadFile = File(...), attribution: str = Form(...), source_url: str | None = Form(None),
                       window_s: float = Form(20.0), stride_s: float = Form(10.0),
                       st: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    """Cut third-party footage into windows; each becomes an `upload` event + clip and is traced in the background."""
    if not attribution.strip():
        raise BadRequest("attribution is required (the CC BY credit line)")
    if not 0.5 <= window_s <= 600 or not 0.5 <= stride_s <= 600:
        raise BadRequest("window_s and stride_s must be between 0.5 and 600 seconds")
    tmp = st.data_dir / "uploads" / f"incoming-{uuid.uuid4().hex}.part"
    limit = st.config.max_upload_bytes

    def save() -> int:
        n = 0
        with open(tmp, "wb") as out:
            while chunk := file.file.read(1 << 20):
                n += len(chunk)
                if n > limit:
                    return -1
                out.write(chunk)
        return n

    size = await run_in_threadpool(save)
    await file.close()
    if size < 0:
        tmp.unlink(missing_ok=True)
        raise ApiError(413, f"upload larger than {limit // (1 << 20)} MB", "TOO_LARGE")
    if size == 0:
        tmp.unlink(missing_ok=True)
        raise BadRequest("empty upload")
    name = file.filename or "upload.mp4"

    def register() -> list[uploads.WindowSpec]:
        src, sha = uploads.save_source(st, tmp, name)
        return uploads.register_upload(st, src, sha, filename=name, attribution=attribution.strip(),
                                       source_url=source_url, window_s=window_s, stride_s=stride_s)

    try:
        specs = await run_in_threadpool(register)
    except media.MediaError as e:
        tmp.unlink(missing_ok=True)
        raise BadRequest(f"could not read that video: {e}", "UNREADABLE_VIDEO") from e
    st.pipeline.submit_upload(specs)
    views = [st.store.events.get_view(s.event_id) for s in specs]
    return [event_summary(v) for v in views if v is not None]
