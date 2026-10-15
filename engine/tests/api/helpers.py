"""Fakes and utilities for the API tests: fake Ring, fake perception, and stand-ins for synthesis and the monitor.

The signatures of `exemplar.synth`, `exemplar.agent`, `exemplar.monitor` and `exemplar.calibrate` are reproduced
here as small fakes. The fake Monitor and the fake
`calibrate` use the REAL DSL evaluator, so deploy -> event -> firing runs through real scoring.
"""
from __future__ import annotations

import base64
import json
import subprocess
import threading
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Callable, Optional

import imageio_ffmpeg
import numpy as np

from exemplar.contracts.dsl_ast import Rule
from exemplar.contracts.trace import PerceptionMeta, Trace, TraceContext
from exemplar.dsl import parse, robustness, to_english, to_text, witness
from exemplar.ring import MediaResult, RingDevice, RingEvent

FIXTURE_TRACES = Path(__file__).resolve().parents[1] / "fixtures" / "traces"
WEBHOOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "webhooks"
DEVICE_ID = "ava1.ring.device.FAKEPLAYGROUND0001"
T0 = 1792048103109          # 2026-10-15T07:08:23Z = 00:08 PDT, a Thursday (weekday 3)


def make_jwt(iat: int | None = None, exp: int | None = None) -> str:
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    claims: dict[str, Any] = {}
    if iat is not None:
        claims["iat"] = iat
    if exp is not None:
        claims["exp"] = exp
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}.c2ln"


def fresh_jwt(minutes: float = 30.0) -> str:
    now = int(time.time())
    return make_jwt(now - 60, now + int(minutes * 60))


def wait_until(fn: Callable[[], Any], timeout: float = 15.0, interval: float = 0.05, what: str = "condition") -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what} (last value: {last!r})")


# ------------------------------------------------------------------------------------------ media
def make_mp4(path: Path, seconds: float = 6.0, size: str = "320x240", fps: int = 10) -> Path:
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc=size={size}:rate={fps}:duration={seconds}", "-pix_fmt", "yuv420p", "-y", str(path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


def make_jpeg(color: tuple[int, int, int] = (200, 30, 30), size: tuple[int, int] = (160, 120)) -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


# ------------------------------------------------------------------------------------------ traces
def load_trace(name: str) -> Trace:
    return Trace.model_validate_json((FIXTURE_TRACES / f"{name}.json").read_text(encoding="utf-8"))


def as_perceived(tr: Trace, *, clip_id: str, source: str, context: TraceContext, mode: str = "fast",
                 tokens_in: int = 6400, tokens_out: int = 1400) -> Trace:
    meta = PerceptionMeta(mode=mode, model_alias="test-alias", n_frames=len(tr.frames), tokens_in=tokens_in,
                          tokens_out=tokens_out, latency_ms=900, cache_key=f"key-{clip_id}-{mode}")
    return tr.model_copy(update={"clip_id": clip_id, "source": source, "context": context, "perception": meta})


class FakePerceive:
    """Stands in for `exemplar.perception.perceive_detailed`.

    `script[clip_id] = "theft_a"` picks the fixture trace a clip yields (default `default`); a callable value is
    called with the clip id; an Exception instance is raised. `cached_ids` yield `cached=True`.
    """

    def __init__(self, default: str = "unattended_package") -> None:
        self.default = default
        self.script: dict[str, Any] = {}
        self.cached_ids: set[str] = set()
        self.calls: list[dict[str, Any]] = []
        self.delay_s = 0.0
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def __call__(self, clip_path: Any, *, clip_id: str, source: str, context: TraceContext, mode: str = "fast",
                 **kw: Any) -> Any:
        with self._lock:
            self.calls.append({"clip_path": str(clip_path), "clip_id": clip_id, "source": source, "context": context,
                               "mode": mode, **kw})
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay_s:
                time.sleep(self.delay_s)
            what = self.script.get(clip_id, self.default)
            if isinstance(what, BaseException):
                raise what
            if callable(what):
                what = what(clip_id)
            if isinstance(what, Trace):
                tr = what
            elif what == "FAILED":
                tr = Trace(clip_id=clip_id, source=source, duration_ms=6000, status="perception_failed",
                           error="schema validation failed twice", context=context,
                           perception=PerceptionMeta(mode=mode, model_alias="test-alias", tokens_in=3000, tokens_out=200))
            else:
                tr = as_perceived(load_trace(what), clip_id=clip_id, source=source, context=context, mode=mode)
            if tr.status == "ok":
                tr = tr.model_copy(update={"clip_id": clip_id, "source": source, "context": context})
            return SimpleNamespace(trace=tr, report=None, cached=clip_id in self.cached_ids)
        finally:
            with self._lock:
                self.active -= 1

    def calls_for(self, clip_id: str, mode: str | None = None) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["clip_id"] == clip_id and (mode is None or c["mode"] == mode)]


# ------------------------------------------------------------------------------------------ fake Ring
class FakeRing:
    """The subset of `RingClient` the engine uses. Newest-first `events`, programmable download failures."""

    def __init__(self, video_bytes: bytes, jpeg_bytes: bytes) -> None:
        self.video, self.jpeg = video_bytes, jpeg_bytes
        self.devices = [RingDevice(id=DEVICE_ID, name="Playground Device", online=True, codecs=("h264",),
                                   snapshot=True, chime=False)]
        self.events: list[RingEvent] = []
        self.location = {"country": "US", "state": "CA"}
        self.video_errors: dict[str, BaseException] = {}
        self.snapshot_errors: dict[str, BaseException] = {}
        self.verify_error: BaseException | None = None
        self.history_error: BaseException | None = None
        self.calls: list[tuple[str, Any]] = []
        self.token_checked = 0

    def add_event(self, eid: str, start_ms: int, dur_ms: int = 6000, event_type: str = "on_demand") -> RingEvent:
        ev = RingEvent(id=eid, event_type=event_type, start_ms=start_ms, end_ms=start_ms + dur_ms, device_id=DEVICE_ID)
        self.events.insert(0, ev)
        self.events.sort(key=lambda e: e.start_ms, reverse=True)
        return ev

    async def verify_connection(self) -> Any:
        self.token_checked += 1
        if self.verify_error:
            raise self.verify_error
        return None

    async def list_devices(self, include: str | None = None) -> list[RingDevice]:
        self.calls.append(("list_devices", None))
        return list(self.devices)

    async def device_location(self, device_id: str) -> dict[str, Any]:
        return dict(self.location)

    async def history(self, device_id: str, event_types: Any = None, *, since_ms: int | None = None,
                      max_pages: int | None = 50) -> AsyncIterator[RingEvent]:
        self.calls.append(("history", since_ms))
        if self.history_error:
            raise self.history_error
        for e in list(self.events):
            if since_ms is not None and e.start_ms < since_ms:
                continue
            yield e

    async def history_tagged(self, device_id: str, *, since_ms: int | None = None, subtypes: Any = ()) -> list[RingEvent]:
        return list(self.events)

    async def download_event_video(self, event: RingEvent, device_id: str | None = None, *, grace_s: float = 5.0,
                                   **kw: Any) -> MediaResult:
        self.calls.append(("video", event.id))
        if event.id in self.video_errors:
            raise self.video_errors[event.id]
        dur = event.duration_ms or 10_000
        return MediaResult(data=self.video, content_type="video/mp4", status=200, media_timestamp_ms=event.start_ms,
                           media_duration_ms=dur, media_origin="recording")

    async def download_event_snapshot(self, event: RingEvent, device_id: str | None = None, *, grace_s: float = 5.0,
                                      **kw: Any) -> MediaResult:
        self.calls.append(("snapshot", event.id))
        if event.id in self.snapshot_errors:
            raise self.snapshot_errors[event.id]
        return MediaResult(data=self.jpeg, content_type="image/jpeg", status=200, media_timestamp_ms=event.start_ms,
                           media_duration_ms=None, media_origin="snapshot")

    async def aclose(self) -> None:
        pass


# ------------------------------------------------------------------------------------------ synthesis stand-ins
@dataclass(frozen=True)
class Example:
    trace: Trace
    positive: bool
    weight: float
    clip_id: str


@dataclass(frozen=True)
class Candidate:
    sketch_text: str
    dsl_text: str
    english: str
    rule: Rule
    holes: dict
    margin: float
    mdl: float
    violated_clip_ids: tuple = ()


THEFT_DSL = "exists p: Person, k: Package: picks_up(p, k)"
THEFT_SKETCH = "exists p: Person, k: Package: picks_up(p, k) then[0, ?b] leaves(p, porch)"
SITTING_DSL = "exists k: Package: holds_for >= 4 in_zone(k, porch)"
SITTING_SKETCH = "exists k: Package: holds_for >= ?d in_zone(k, porch)"


def make_candidate(dsl: str, sketch: str, *, mdl: float, margin: float, holes: dict | None = None,
                   violated: tuple = ()) -> Candidate:
    rule = parse(dsl)
    return Candidate(sketch_text=sketch, dsl_text=to_text(rule), english=to_english(rule), rule=rule,
                     holes=holes or {}, margin=margin, mdl=mdl, violated_clip_ids=violated)


class FakeCegis:
    """`run_cegis(examples, *, nl_hint, emit, k, max_rounds, model, cancel) -> list[Candidate]`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.candidates = [make_candidate(THEFT_DSL, THEFT_SKETCH, mdl=21.0, margin=0.3, holes={"b": 6.0}),
                           make_candidate(SITTING_DSL, SITTING_SKETCH, mdl=24.0, margin=0.25, holes={"d": 4.0})]
        self.gate: threading.Event | None = None     # when set, the run blocks until the test opens the gate
        self.error: BaseException | None = None
        self.extra_events: list[dict[str, Any]] = []

    def __call__(self, examples: list[Any], *, nl_hint: str | None, emit: Callable[[dict], None], k: int = 6,
                 max_rounds: int = 4, model: Any = None, cancel: threading.Event | None = None) -> list[Candidate]:
        self.calls.append({"examples": list(examples), "nl_hint": nl_hint, "k": k, "max_rounds": max_rounds})
        emit({"type": "round_started", "round": 1, "message": "sketching"})
        emit({"type": "sketch_proposed", "round": 1, "sketch": THEFT_SKETCH})
        emit({"type": "typecheck_failed", "round": 1, "sketch": "exists p: Person: rings_doorbell(p)",
              "error": "unknown predicate 'rings_doorbell'"})
        emit({"type": "solve_result", "round": 1, "sketch": THEFT_SKETCH, "result": "sat", "holes": {"b": np.float64(6.0)},
              "margin": np.float64(0.3), "violated_clip_ids": []})
        for ev in self.extra_events:
            emit(ev)
        emit({"type": "done"})                       # the API must ignore the proposer's own `done` and send its own
        if self.gate is not None:
            self.gate.wait(10)
        if self.error:
            raise self.error
        return list(self.candidates)


# ------------------------------------------------------------------------------------------ monitor / calibration stand-ins
@dataclass(frozen=True)
class FakeCalibration:
    alpha: float
    n_random_neg: int
    n_random_pos: int
    k: Optional[int]
    tau: float
    guarantee: bool
    message: Optional[str]
    delta: float
    recall: Optional[float]
    recall_ci95: Optional[tuple]

    def to_api(self) -> dict[str, Any]:
        return {"alpha": self.alpha, "n_random_neg": self.n_random_neg, "n_random_pos": self.n_random_pos, "k": self.k,
                "tau": self.tau, "guarantee": self.guarantee, "message": self.message, "delta": self.delta,
                "recall": self.recall, "recall_ci95": list(self.recall_ci95) if self.recall_ci95 else None}


class FakeCalibrate:
    """Conformal threshold on the labels it is given (scored with the real DSL evaluator)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, rule: Rule, random_labelled: list[tuple[Trace, Any]], alpha: float) -> FakeCalibration:
        self.calls.append({"rule": rule, "labels": [l for _, l in random_labelled], "alpha": alpha})
        assert all(l.provenance == "random" for _, l in random_labelled), "E raises ProvenanceError here"
        neg = sorted(float(robustness(rule, t)) for t, l in random_labelled if l.value == "neg")
        pos = [float(robustness(rule, t)) for t, l in random_labelled if l.value == "pos"]
        n = len(neg)
        import math
        k = math.ceil((n + 1) * (1 - alpha))
        if k <= n:
            tau, ok, msg = max(0.0, neg[k - 1]), True, None             # E floors tau at 0
        else:
            tau, ok, msg = 0.0, False, f"guarantee needs >= {math.ceil(1 / alpha) - 1} random negatives (have {n})"
        recall = (sum(1 for s in pos if s > tau) / len(pos)) if pos else None
        return FakeCalibration(alpha, n, len(pos), k if ok else None, tau, ok, msg, 0.1, recall,
                               (0.0, 1.0) if pos else None)


@dataclass
class DeployedRule:
    rule_id: str
    concept_id: str
    rule: Rule
    tau: float
    delta: float
    actions: tuple
    english: str


@dataclass(frozen=True)
class EventInput:
    event_id: str
    clip_id: str
    clip_path: Optional[str]
    sub_type: Optional[str]
    device_id: Optional[str]
    context: TraceContext
    trace: Optional[Trace] = None
    trace_cached: bool = False


@dataclass(frozen=True)
class FiringRecord:
    id: str
    rule_id: str
    event_id: str
    stage: int
    score: Optional[float]
    tau: Optional[float]
    fired: bool
    witness: Optional[dict]
    actions: tuple
    created_at_ms: int

    def to_api(self) -> dict[str, Any]:
        return {"id": self.id, "rule_id": self.rule_id, "event_id": self.event_id, "stage": self.stage,
                "score": self.score, "tau": self.tau, "fired": self.fired, "witness": self.witness,
                "actions": list(self.actions), "created_at_ms": self.created_at_ms}


def _unwrap(res: Any) -> Trace:
    """Like the real monitor: perceivers may return a Trace or a PerceptionResult-like object (`.trace`, `.cached`)."""
    return res if isinstance(res, Trace) else res.trace


class FakeMonitor:
    """Funnel in miniature: stage 0 drops impossible sub_types, stage 1 scores the fast trace, stage 2 escalates
    when |score - tau| <= delta. Constructed with the same signature as the real `Monitor`."""

    instances: list["FakeMonitor"] = []

    def __init__(self, *, perceive_fast: Callable, perceive_strong: Callable, on_firing: Callable,
                 on_event: Callable = lambda e: None, actions: Any = None) -> None:
        self.perceive_fast, self.perceive_strong = perceive_fast, perceive_strong
        self.on_firing, self.on_event, self.actions = on_firing, on_event, actions
        self.rules: dict[str, DeployedRule] = {}
        self.counts = {"events": 0, "stage0_dropped": 0, "stage1_scored": 0, "stage2_escalated": 0}
        self.deploy_calls: list[DeployedRule] = []
        self.inputs: list[EventInput] = []
        self._n = 0
        FakeMonitor.instances.append(self)

    def deploy(self, r: DeployedRule) -> None:
        self.rules[r.rule_id] = r
        self.deploy_calls.append(r)

    def undeploy(self, rule_id: str) -> None:
        self.rules.pop(rule_id, None)

    def process(self, ev: EventInput) -> list[FiringRecord]:
        self.inputs.append(ev)
        self.counts["events"] += 1
        out: list[FiringRecord] = []
        for r in list(self.rules.values()):
            self._n += 1
            stage, trace = 1, ev.trace or _unwrap(self.perceive_fast(ev))
            score = float(robustness(r.rule, trace))
            if abs(score - r.tau) <= r.delta:
                stage, trace = 2, _unwrap(self.perceive_strong(ev))
                score = float(robustness(r.rule, trace))
                self.counts["stage2_escalated"] += 1
                self.on_event({"type": "escalated", "event_id": ev.event_id, "rule_id": r.rule_id})
            else:
                self.counts["stage1_scored"] += 1
            fired = score > r.tau
            w = None
            if fired:
                w = witness(r.rule, trace)
                w.update(rule_id=r.rule_id, tau=r.tau, margin=score - r.tau)
            acts = tuple({"action": a, "status": "ok" if a == "ui" else "skipped", "detail": None} for a in r.actions)
            rec = FiringRecord(f"fi_{self._n:04d}_{r.rule_id[-4:]}", r.rule_id, ev.event_id, stage, score, r.tau, fired,
                               w, acts if fired else (), int(time.time() * 1000))
            self.on_firing(rec)
            self.on_event({"type": "rule_fired" if fired else "rule_dropped", "event_id": ev.event_id,
                           "rule_id": r.rule_id, "firing": rec.to_api()})
            out.append(rec)
        return out

    def cost(self) -> dict[str, Any]:
        return {**self.counts, "tokens_in": 0, "tokens_out": 0}


class FakeCommittee:
    def __init__(self, members: int) -> None:
        self.members = tuple((None, 1.0 / max(1, members)) for _ in range(members))


@dataclass(frozen=True)
class Question:
    clip_id: str
    p: float
    committee_size: int

    def to_api(self, *, concept_id: str, event: dict | None = None) -> dict[str, Any]:
        d = {"concept_id": concept_id, "clip_id": self.clip_id, "p": self.p, "committee_size": self.committee_size}
        if event is not None:
            d["event"] = event
        return d


class FakeActive:
    """`build_committee` + `select_query`: asks about the unlabelled trace with the most `picks_up` evidence."""

    def __init__(self) -> None:
        self.committee_calls: list[dict[str, Any]] = []
        self.query_calls: list[list[str]] = []
        self.query_kwargs: list[dict[str, Any]] = []
        self.none = False
        self.p = 0.5                      # the committee's split on the clip it asks about

    def build_committee(self, candidates: list[Candidate], examples: list[Example], *, box_fn: Any = None,
                        n_samples: int = 200, seed: int = 0,
                        mdl_temperature: float = 1.0) -> FakeCommittee:
        self.committee_calls.append({"candidates": candidates, "examples": examples, "n_samples": n_samples,
                                     "mdl_temperature": mdl_temperature})
        return FakeCommittee(len(candidates))

    def select_query(self, committee: FakeCommittee, unlabelled: list[Trace], *, k: int = 1,
                     labelled: Any = (), exclude: Any = ()) -> list[Question]:
        self.query_calls.append([t.clip_id for t in unlabelled])
        self.query_kwargs.append({"labelled": sorted(t.clip_id for t in labelled), "exclude": sorted(exclude)})
        unlabelled = [t for t in unlabelled if t.clip_id not in set(exclude)]
        if self.none or not unlabelled:
            return []
        best = max(unlabelled, key=lambda t: (sum(1 for f in t.frames for fa in f.facts if fa.pred == "picks_up"),
                                              t.clip_id))
        return [Question(best.clip_id, self.p, len(committee.members))][:k]


# ------------------------------------------------------------------------------------------ shared flows
ALL_FIXTURES = ("theft_a", "theft_b", "delivery_a", "delivery_b", "unattended_package", "visitor_no_ring",
                "visitor_rings", "empty_scene", "vehicle_passby", "birds_feeder")


def run_teach(env, cid, timeout=15.0):
    r = env.client.post(f"/concepts/{cid}/teach")
    assert r.status_code == 202, r.text
    run = r.json()
    wait_until(lambda: env.client.get(f"/runs/{run['id']}").json()["status"] != "running", timeout, what="run to finish")
    return env.client.get(f"/runs/{run['id']}").json()


def parse_sse(lines):
    """Iterable of text lines -> list of {event, id, data} (comments and pings skipped)."""
    frames, cur = [], {}
    for line in lines:
        line = line.rstrip("\r\n")
        if line == "":
            if cur.get("event") and cur["event"] != "ping":
                frames.append(cur)
            cur = {}
        elif line.startswith(":"):
            continue
        elif ":" in line:
            k, v = line.split(":", 1)
            cur[k] = v.lstrip(" ")
    return frames


EXAMPLES = {"theft_a": "pos", "theft_b": "pos", "delivery_a": "neg"}


def teach_and_calibrate(env, random_labels: bool = True):
    """Label 3 examples, run the (fake) CEGIS, and (by default) random-label the remaining 7 clips negative."""
    cid = env.cid
    for clip, v in EXAMPLES.items():
        env.label(cid, clip, v)
    run_teach(env, cid)
    env.rules = env.client.get(f"/concepts/{cid}/rules").json()
    env.theft = env.rules[0]
    if random_labels:
        drawn = [d["clip_id"] for d in env.client.post(f"/concepts/{cid}/random-sample?n=50&seed=5").json()]
        assert len(drawn) == 7
        for c in drawn:
            assert env.label(cid, c, "neg", "random").status_code == 200
    return env


def post_webhook(env, request_id, *, sub="human", ts=T0, device=DEVICE_ID):
    body = {"meta": {"request_id": request_id, "account_id": "a"},
            "data": {"id": f"evt-{request_id}", "type": "motion_detected", "subType": sub,
                     "attributes": {"source": device, "source_type": "devices", "timestamp": ts}}}
    return env.client.post("/ring/webhook-events", content=json.dumps(body), headers={"Content-Type": "application/json"})
