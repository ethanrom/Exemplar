"""Fixture-like traces, windows and fake D / E services for the harness tests (no model, no Z3, no data files)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from eval.harness import metrics
from eval.harness.dataset import Window
from eval.harness.experiment import Services
from exemplar.contracts.labels import Label
from exemplar.contracts.trace import Entity, Fact, Frame, PerceptionMeta, Trace
from exemplar.dsl import parse, robustness

RULE_TEXT = "exists p: Person: eventually[0, 30] in_zone(p, door)"
CONCEPT = "c1"


def make_trace(clip_id: str, kind: str, *, tokens: tuple[int, int] = (8000, 1500), latency_ms: int = 14000) -> Trace:
    """kind: pos (door, high: score +0.45) | weak_neg (door, low: +0.10) | neg (person in the street: -0.45) | empty (-0.5) | failed."""
    meta = PerceptionMeta(mode="fast", model_alias="fast", n_frames=4, tokens_in=tokens[0], tokens_out=tokens[1], latency_ms=latency_ms)
    if kind == "failed":
        return Trace(clip_id=clip_id, source="meva", duration_ms=10000, status="perception_failed", error="x", perception=meta)
    if kind == "empty":
        frames = tuple(Frame(t_ms=t) for t in (1000, 4000, 7000))
        return Trace(clip_id=clip_id, source="meva", duration_ms=10000, frames=frames, perception=meta)
    zone, conf = {"pos": ("door", "high"), "weak_neg": ("door", "low"), "neg": ("street", "high")}[kind]
    frames = tuple(Frame(t_ms=t, facts=(Fact(pred="in_zone", args=("p1", zone), conf=conf),)) for t in (1000, 4000, 7000))
    return Trace(clip_id=clip_id, source="meva", duration_ms=10000, entities=(Entity(id="p1", type="person"),), frames=frames,
                 perception=meta)


def window(wid: str, label: str, split: Optional[str], concept: str = CONCEPT) -> Window:
    return Window(id=wid, concept=concept, label=label, split=split, clip=f"meva/clips/{concept}/{wid}.mp4", source="meva")


@dataclass
class World:
    train: list[Window]
    calib: list[Window]
    test: list[Window]
    traces: dict[str, Trace]

    @property
    def all(self) -> list[Window]:
        return self.train + self.calib + self.test


def make_world(*, n_train: tuple[int, int] = (6, 12), n_calib: tuple[int, int] = (5, 20), n_test: tuple[int, int] = (4, 10),
               calib_weak: int = 3, test_weak: int = 2) -> World:
    """Positives score +0.45.  Calibration negatives: `calib_weak` of them score +0.10, the rest -0.45 (so tau_0.1 = 0.10 with 20
    negatives).  Test negatives: `test_weak` score +0.10 (they do NOT fire at tau 0.10), the rest -0.45."""
    traces: dict[str, Trace] = {}

    def build(split: str, npos: int, nneg: int, weak: int) -> list[Window]:
        ws = []
        for i in range(npos):
            w = window(f"{split}-pos-{i:02d}", "pos", split)
            ws.append(w)
            traces[w.id] = make_trace(w.id, "pos")
        for i in range(nneg):
            w = window(f"{split}-neg-{i:02d}", "neg", split)
            ws.append(w)
            traces[w.id] = make_trace(w.id, "weak_neg" if i < weak else "neg")
        return ws

    return World(build("train", *n_train, weak=4), build("calib", *n_calib, weak=calib_weak),
                 build("test", *n_test, weak=test_weak), traces)


@dataclass(frozen=True)
class FakeCandidate:
    rule: Any
    dsl_text: str
    english: str
    margin: float = 0.45
    mdl: float = 10.0


@dataclass(frozen=True)
class FakeQuestion:
    clip_id: str
    p: float = 0.5
    committee_size: int = 3


@dataclass(frozen=True)
class FakeCalibration:
    alpha: float
    tau: float
    guarantee: bool
    delta: float
    n_random_neg: int
    n_random_pos: int
    recall: Optional[float] = None
    recall_ci95: Optional[tuple[float, float]] = None


class Recorder:
    """What the fake D / E saw, for the leakage assertions."""

    def __init__(self) -> None:
        self.cegis_ids: list[list[str]] = []
        self.committee_ids: list[list[str]] = []
        self.query_pool_ids: list[list[str]] = []
        self.calibrate_labels: list[list[tuple[str, str]]] = []      # (clip_id, provenance)
        self.example_weights: list[float] = []
        self.proposers_made = 0


def fake_services(rec: Optional[Recorder] = None, *, candidates: bool = True, question_ids: Optional[list[str]] = None,
                  rule_text: str = RULE_TEXT) -> tuple[Services, Recorder]:
    rec = rec or Recorder()
    rule = parse(rule_text)

    def run_cegis(examples, *, nl_hint, emit, k=6, max_rounds=4, model=None):
        rec.cegis_ids.append([e.clip_id for e in examples])
        emit({"type": "done", "message": "fake"})
        if not candidates or not any(e.positive for e in examples):
            return []
        return [FakeCandidate(rule=rule, dsl_text=rule_text, english="fake english")]

    def build_committee(cands, examples, *, seed=0, n_samples=200):
        rec.committee_ids.append([e.clip_id for e in examples])
        return ("committee", len(cands))

    def select_query(committee, unlabelled, *, k=1, labelled=()):
        ids = sorted(t.clip_id for t in unlabelled)
        rec.query_pool_ids.append(ids)
        if question_ids is not None:
            return [FakeQuestion(clip_id=question_ids.pop(0))] if question_ids else []
        return [FakeQuestion(clip_id=ids[0])] if ids else []

    def calibrate(rule_, labelled, alpha):
        rec.calibrate_labels.append([(lab.clip_id, lab.provenance) for _, lab in labelled])
        assert all(lab.provenance == "random" for _, lab in labelled)
        neg = [robustness(rule_, t) for t, lab in labelled if not lab.positive]
        pos = [robustness(rule_, t) for t, lab in labelled if lab.positive]
        th = metrics.conformal_threshold(neg, alpha, fallback=0.0)
        tau = max(th.tau, 0.0)
        rc = sum(s > tau for s in pos) / len(pos) if pos else None
        return FakeCalibration(alpha=alpha, tau=tau, guarantee=th.guarantee, delta=0.1, n_random_neg=len(neg), n_random_pos=len(pos),
                               recall=rc)

    def make_example(*, trace, positive, weight, clip_id):
        rec.example_weights.append(weight)
        return type("Ex", (), {"trace": trace, "positive": positive, "weight": weight, "clip_id": clip_id})()

    def make_label(**kw):
        return Label(weight=1.0, **kw)

    def new_proposer():
        rec.proposers_made += 1
        return None

    return Services(run_cegis=run_cegis, build_committee=build_committee, select_query=select_query, calibrate=calibrate,
                    make_example=make_example, make_label=make_label, robustness=robustness, new_proposer=new_proposer,
                    proposer_name="fake"), rec
