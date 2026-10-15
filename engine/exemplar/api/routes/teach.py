"""Concepts, labels, teach runs, questions, candidate rules."""
from __future__ import annotations

import random
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import sse, teach
from ..errors import ApiError, BadRequest, NotFound, error_body
from ..serialize import PROVENANCE_WEIGHT, BULK_WEIGHT, concept_view, event_summary, rule_summary
from ..state import AppState
from .deps import get_state

router = APIRouter(tags=["teach"])


class ConceptIn(BaseModel):
    name: str = Field(min_length=1)
    nl_hint: str | None = None
    alpha: float = Field(default=0.1, gt=0, lt=1)


class LabelIn(BaseModel):
    clip_id: str
    value: Literal["pos", "neg"] | None
    provenance: Literal["example", "active", "random"]


class BulkNegIn(BaseModel):
    clip_ids: list[str] = Field(min_length=1)
    provenance: Literal["example", "random"]


def _concept(st: AppState, concept_id: str):
    c = st.store.concepts.get(concept_id)
    if c is None:
        raise NotFound(f"concept {concept_id}")
    return c


def _require_drawn(st: AppState, concept_id: str, clip_ids: list[str]) -> None:
    """Provenance `random` is only honest for clips that `/random-sample` drew (uniformly) for this concept."""
    drawn = st.store.random_samples.drawn(concept_id, clip_ids)
    missing = [c for c in clip_ids if c not in drawn]
    if missing:
        raise BadRequest("provenance=random is only valid for clips drawn by /random-sample "
                         "(calibration labels must be uniformly sampled); not drawn: " + ", ".join(m[:24] for m in missing[:5]),
                         "INVALID_PROVENANCE")


# ------------------------------------------------------------------------------------------------ concepts
@router.get("/concepts")
def list_concepts(st: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    return [concept_view(st.store, c) for c in st.store.concepts.list()]


@router.post("/concepts", status_code=201)
def create_concept(body: ConceptIn, st: AppState = Depends(get_state)) -> dict[str, Any]:
    c = st.store.concepts.create(teach.new_id("cn"), body.name.strip(), body.nl_hint, body.alpha)
    return concept_view(st.store, c)


# ------------------------------------------------------------------------------------------------ labels
@router.get("/concepts/{concept_id}/labels")
def list_labels(concept_id: str, st: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    _concept(st, concept_id)
    return [l.to_api() for l in st.store.labels.list(concept_id)]


@router.put("/concepts/{concept_id}/labels")
def put_label(concept_id: str, body: LabelIn, st: AppState = Depends(get_state)) -> dict[str, Any]:
    """Set or replace the label of one clip; `value: null` deletes it."""
    _concept(st, concept_id)
    if st.store.clips.get(body.clip_id) is None:
        raise NotFound(f"clip {body.clip_id}")
    weight = PROVENANCE_WEIGHT[body.provenance]
    if body.value is None:
        st.store.labels.delete(concept_id, body.clip_id)
        return {"concept_id": concept_id, "clip_id": body.clip_id, "value": None,
                "provenance": body.provenance, "weight": weight}
    if body.provenance == "random":
        _require_drawn(st, concept_id, [body.clip_id])
    return st.store.labels.put(concept_id, body.clip_id, body.value, body.provenance, weight).to_api()


@router.post("/concepts/{concept_id}/labels/bulk-negative")
def bulk_negative(concept_id: str, body: BulkNegIn, st: AppState = Depends(get_state)) -> dict[str, Any]:
    _concept(st, concept_id)
    ids = list(dict.fromkeys(body.clip_ids))
    unknown = [c for c in ids if st.store.clips.get(c) is None]
    if unknown:
        raise NotFound("clip " + ", ".join(u[:24] for u in unknown[:5]))
    if body.provenance == "random":
        _require_drawn(st, concept_id, ids)
    st.store.labels.put_many(concept_id, ids, "neg", body.provenance, BULK_WEIGHT)
    return {"concept_id": concept_id, "clip_id": ids[0], "value": "neg", "provenance": body.provenance,
            "weight": BULK_WEIGHT}


@router.post("/concepts/{concept_id}/random-sample")
def random_sample(concept_id: str, n: int = Query(10, ge=1, le=50), seed: int | None = None,
                  st: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    """Uniform (seeded) sample of the concept's unlabelled traced clips, to be labelled with provenance=random."""
    _concept(st, concept_id)
    pool = sorted(st.store.traces.unlabelled_ok_ids(concept_id))     # sorted: the same seed gives the same draw
    rng = random.Random(seed)
    pick = rng.sample(pool, min(n, len(pool)))
    st.store.random_samples.add(concept_id, pick)
    views = st.store.events.views_by_clips(pick, concept_id)
    return [event_summary(views[c]) for c in pick if c in views]


# ------------------------------------------------------------------------------------------------ teach
@router.post("/concepts/{concept_id}/teach", status_code=202)
def start_teach(concept_id: str, st: AppState = Depends(get_state)) -> Any:
    concept = _concept(st, concept_id)
    st.services.run_cegis, st.services.example_cls            # 503 before a run row exists when D is missing
    run = teach.start_run(st, concept)
    if run is None:
        return JSONResponse(error_body("a run is already in progress for this concept", "RUN_IN_PROGRESS"),
                            status_code=409)
    return run.to_api()


@router.get("/concepts/{concept_id}/question")
def get_question(concept_id: str, st: AppState = Depends(get_state)) -> Any:
    _concept(st, concept_id)
    q = teach.compute_question(st, concept_id)
    if q is None:
        return Response(status_code=204)
    return q


@router.get("/concepts/{concept_id}/rules")
def list_rules(concept_id: str, st: AppState = Depends(get_state)) -> list[dict[str, Any]]:
    _concept(st, concept_id)
    return [rule_summary(r) for r in st.store.rules.list_for_concept(concept_id)]


# ------------------------------------------------------------------------------------------------ runs
@router.get("/runs/{run_id}")
def get_run(run_id: str, st: AppState = Depends(get_state)) -> dict[str, Any]:
    run = st.store.runs.get(run_id)
    if run is None:
        raise NotFound(f"run {run_id}")
    return run.to_api()


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, st: AppState = Depends(get_state)):
    """SSE of RunEvents; replays from `Last-Event-ID` (default: the start), then follows until the run ends."""
    if await run_in_threadpool(st.store.runs.get, run_id) is None:
        raise NotFound(f"run {run_id}")
    return sse.response(sse.run_events(st, run_id, sse.last_event_id(request)), st)
