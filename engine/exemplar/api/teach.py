"""Teach flow: labelled examples -> `run_cegis` in a worker thread -> run events + candidate rules -> question.

Provenance (docs/DSL.md): synthesis sees ONLY `example` + `active` labels. `random` labels are held out for
calibration (see rules_logic.py).
"""
from __future__ import annotations

import inspect
import json
import logging
import threading
import uuid
from typing import TYPE_CHECKING, Any

from exemplar.contracts.dsl_ast import Rule
from exemplar.dsl import to_english, to_text
from exemplar.store import ConceptRow, RunRow, now_ms

from .errors import short_error
from .serialize import event_summary, jsonable

if TYPE_CHECKING:  # pragma: no cover
    from .state import AppState

log = logging.getLogger("exemplar.api.teach")

SYNTHESIS_PROVENANCE = ("example", "active")
# Emitted by this module, never forwarded from D: they need rule ids / the final state only H knows.
_H_OWNED = {"candidates", "done"}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ====================================================================================== examples
def labelled_examples(state: "AppState", concept_id: str) -> list[Any]:
    """`Example`s for the concept's example+active labels whose clips have an ok trace."""
    labels = state.store.labels.list(concept_id, provenance=SYNTHESIS_PROVENANCE)
    assert all(l.provenance in SYNTHESIS_PROVENANCE for l in labels)
    traces = state.store.traces.primary_ok_for([l.clip_id for l in labels])
    Example = state.services.example_cls
    return [Example(trace=traces[l.clip_id], positive=(l.value == "pos"), weight=l.weight, clip_id=l.clip_id)
            for l in labels if l.clip_id in traces]


# ====================================================================================== run recording
class RunRecorder:
    """Adds `seq`/`at_ms` to every emitted RunEvent, stores it in `run_events` and wakes the SSE streams."""

    def __init__(self, state: "AppState", run_id: str) -> None:
        self.state, self.run_id = state, run_id
        self._seq = state.store.runs.last_seq(run_id)
        self._lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> dict[str, Any]:
        ev = jsonable(dict(event))
        if "type" not in ev:
            ev["type"] = "error"
        with self._lock:
            self._seq += 1
            ev["seq"], ev["at_ms"] = self._seq, now_ms()
            self.state.store.runs.append_event(self.run_id, ev["seq"], str(ev["type"]), ev, ev["at_ms"])
        tin, tout = ev.get("tokens_in"), ev.get("tokens_out")
        if isinstance(tin, int) or isinstance(tout, int):                  # sketch LLM spend, when D reports it
            self.state.store.cost.add("sketch", run_id=self.run_id, tokens_in=int(tin or 0), tokens_out=int(tout or 0))
        self.state.run_hub.notify(self.run_id)
        return ev


# ====================================================================================== persistence
def persist_candidates(state: "AppState", concept_id: str, run_id: str, candidates: list[Any]) -> list[str]:
    """Candidate -> `rules` rows (dsl_text / english from the DSL printers). Returns rule ids in rank order."""
    store = state.store
    ids: list[str] = []
    for cand in candidates:
        rule: Rule | None = getattr(cand, "rule", None)
        if rule is None:                                    # unsat sketch: nothing to store
            continue
        dsl_text, english = to_text(rule), to_english(rule)
        existing = store.rules.find_by_dsl(concept_id, dsl_text)
        if existing is not None:                            # same rule found again by a later run
            ids.append(existing.id)
            continue
        row = store.rules.insert(
            rule_id=new_id("ru"), concept_id=concept_id, run_id=run_id,
            sketch_text=getattr(cand, "sketch_text", "") or dsl_text, dsl_text=dsl_text, ast_json=rule.model_dump_json(),
            english=english, holes={k: float(v) for k, v in dict(getattr(cand, "holes", {}) or {}).items()},
            margin=float(cand.margin), mdl=float(cand.mdl),
            violated_clip_ids=list(getattr(cand, "violated_clip_ids", ()) or ()))
        ids.append(row.id)
    store.rules.supersede_candidates(concept_id, ids)
    return ids


# ====================================================================================== the run
def start_run(state: "AppState", concept: ConceptRow) -> RunRow | None:
    """Create the run row and start the worker thread. None if a run is already in progress for the concept."""
    with state.teach_lock:
        if state.store.runs.running_for_concept(concept.id) is not None:
            return None
        run = state.store.runs.create(new_id("run"), concept.id)
    run_cegis = state.services.run_cegis
    cancel = threading.Event()
    state.cancel_events[run.id] = cancel
    threading.Thread(target=_worker, args=(state, run, concept, run_cegis, cancel), daemon=True,
                     name=f"teach-{run.id}").start()
    return run


def _worker(state: "AppState", run: RunRow, concept: ConceptRow, run_cegis: Any, cancel: threading.Event) -> None:
    rec = RunRecorder(state, run.id)
    status, error = "done", None

    def emit(ev: dict[str, Any]) -> None:
        if str(ev.get("type")) in _H_OWNED:
            return
        rec.emit(ev)

    try:
        examples = labelled_examples(state, concept.id)
        if not any(e.positive for e in examples):
            raise ValueError("need at least one positive example with a trace: label a clip as +")
        cands = list(run_cegis(examples, nl_hint=concept.nl_hint, emit=emit, k=state.config.cegis_k,
                               max_rounds=state.config.cegis_rounds, cancel=cancel) or [])
        if cancel.is_set():
            status = "cancelled"
            rec.emit({"type": "error", "message": "run cancelled"})
        else:
            rule_ids = persist_candidates(state, concept.id, run.id, cands)
            rec.emit({"type": "candidates", "rule_ids": rule_ids,
                      "message": f"{len(rule_ids)} candidate rule(s), ranked by MDL" if rule_ids
                      else "no rule is consistent with the labelled examples"})
            try:
                q = compute_question(state, concept.id)
            except Exception as e:  # noqa: BLE001 - E missing or failing must not fail the run
                log.info("no question for %s: %s", concept.id, short_error(e))
                q = None
            if q is not None:
                rec.emit({"type": "question_ready",
                          "message": "your candidate rules disagree most on one unlabelled clip"})
            rec.emit({"type": "done"})
    except Exception as e:  # noqa: BLE001
        log.exception("teach run %s failed", run.id)
        status, error = "failed", short_error(e, 500)
        rec.emit({"type": "error", "message": error, "error": error})
    finally:
        state.store.runs.finish(run.id, status, error)
        state.run_hub.notify(run.id)
        state.cancel_events.pop(run.id, None)


# ====================================================================================== question
def candidate_objects(state: "AppState", concept_id: str) -> list[Any]:
    """Stored rules -> `Candidate`s (what `build_committee` expects)."""
    Candidate = state.services.candidate_cls
    out = []
    for r in state.store.rules.list_for_concept(concept_id):
        out.append(Candidate(sketch_text=r.sketch_text, dsl_text=r.dsl_text, english=r.english,
                             rule=Rule.model_validate_json(r.ast_json), holes=r.holes, margin=r.margin, mdl=r.mdl,
                             violated_clip_ids=tuple(r.violated_clip_ids)))
    return out


def compute_question(state: "AppState", concept_id: str) -> dict[str, Any] | None:
    """The unlabelled traced clip the committee disagrees on most, as an api.yaml `Question`.

    Clips drawn by `/random-sample` but not yet labelled are excluded: pulling them into the active set would
    bias the calibration sample.
    """
    svc, store = state.services, state.store
    build_committee, select_query = svc.build_committee, svc.select_query
    rules = store.rules.list_for_concept(concept_id)
    if not rules:
        return None
    examples = labelled_examples(state, concept_id)
    drawn = store.random_samples.all_for(concept_id)
    pool = [(cid, tr) for cid, tr in store.traces.unlabelled_ok(concept_id) if cid not in drawn]
    if not pool:
        return None
    labelled_ids = [l.clip_id for l in store.labels.list(concept_id)]
    labelled_traces = list(store.traces.primary_ok_for(labelled_ids).values())
    lab = store.labels.list(concept_id)
    key = (concept_id, tuple(sorted(r.id for r in rules)), len(lab), max((l.created_at_ms for l in lab), default=0),
           len(pool))
    if key in state.question_cache:
        return state.question_cache[key]
    committee = build_committee(candidate_objects(state, concept_id), examples,
                                n_samples=state.config.committee_samples)
    extra: dict[str, Any] = {}
    accepted = inspect.signature(select_query).parameters
    if "labelled" in accepted:                      # E: already-labelled clips are the diversity reference set
        extra["labelled"] = labelled_traces
    if "exclude" in accepted:
        extra["exclude"] = sorted(drawn)
    qs = list(select_query(committee, [tr for _, tr in pool], k=1, **extra) or [])
    result = None
    if qs:
        q = qs[0]
        view = store.events.view_by_clip(q.clip_id, concept_id)
        result = jsonable(q.to_api(concept_id=concept_id, event=event_summary(view) if view else None))
    state.question_cache[key] = result
    return result
