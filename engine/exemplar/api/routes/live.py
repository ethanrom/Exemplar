"""/live/*: browser frame grabs -> `ring_live` clip."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from .. import live
from ..state import AppState
from .deps import get_state

router = APIRouter(tags=["live"])


@router.post("/live/frames", status_code=202)
async def post_live_frame(session_id: str = Form(...), t_ms: int = Form(...), image: UploadFile = File(...),
                          device_id: str | None = Form(None), st: AppState = Depends(get_state)) -> dict[str, Any]:
    """One JPEG from the WHEP `<video>` (~2 fps), stored under the session until `finish`."""
    data = await image.read()
    await run_in_threadpool(live.save_frame, st, session_id, t_ms, data, device_id)
    return {"ok": True}


@router.post("/live/sessions/{session_id}/finish", status_code=202)
async def finish_live_session(session_id: str, st: AppState = Depends(get_state)) -> dict[str, Any]:
    """Frames -> mp4 -> `ring_live` event + clip -> fast perception -> `live_facts` -> deployed monitors."""
    event_id, created = await run_in_threadpool(live.register_session, st, session_id)
    if created:
        st.pipeline.submit_live(session_id, event_id)
    return {"event_id": event_id}
