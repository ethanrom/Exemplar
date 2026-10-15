"""Typed repositories over the SQLite tables (one class per table family).

Rows come back as small frozen dataclasses; JSON columns hold `model_dump_json()` of the contract models.
Every method is a short, self-contained statement (or a `store.transaction()`), safe to call from any thread.
"""
from __future__ import annotations

import base64
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from exemplar.contracts.trace import Trace
from exemplar.ring.tokens import StoredAuth

if TYPE_CHECKING:  # pragma: no cover
    from .store import Store


def now_ms() -> int:
    return int(time.time() * 1000)


# =================================================================================================== rows
@dataclass(frozen=True)
class EventRow:
    id: str
    source: str
    start_ms: int
    created_at_ms: int
    device_id: str | None = None
    kind: str | None = None
    sub_type: str | None = None
    end_ms: int | None = None
    raw_json: str | None = None


@dataclass(frozen=True)
class ClipRow:
    id: str
    event_id: str
    created_at_ms: int
    path: str | None = None
    snapshot_path: str | None = None
    sha256: str | None = None
    duration_ms: int | None = None
    source_ref: str | None = None
    attribution: str | None = None
    status: str = "pending"
    error: str | None = None


@dataclass(frozen=True)
class TraceRow:
    clip_id: str
    mode: str
    status: str
    trace_json: str
    cache_key: str | None
    tokens_in: int
    tokens_out: int
    latency_ms: int
    created_at_ms: int

    def trace(self) -> Trace:
        return Trace.model_validate_json(self.trace_json)


@dataclass(frozen=True)
class ConceptRow:
    id: str
    name: str
    nl_hint: str | None
    alpha: float
    created_at_ms: int


@dataclass(frozen=True)
class LabelRow:
    concept_id: str
    clip_id: str
    value: str
    provenance: str
    weight: float
    created_at_ms: int

    def to_api(self) -> dict[str, Any]:
        return {"concept_id": self.concept_id, "clip_id": self.clip_id, "value": self.value,
                "provenance": self.provenance, "weight": self.weight}


@dataclass(frozen=True)
class RunRow:
    id: str
    concept_id: str
    status: str
    started_at_ms: int
    error: str | None = None
    finished_at_ms: int | None = None

    def to_api(self) -> dict[str, Any]:
        return {"id": self.id, "concept_id": self.concept_id, "status": self.status, "error": self.error,
                "started_at_ms": self.started_at_ms, "finished_at_ms": self.finished_at_ms}


@dataclass(frozen=True)
class RuleRow:
    id: str
    concept_id: str
    run_id: str | None
    sketch_text: str
    dsl_text: str
    ast_json: str
    english: str
    holes_json: str
    margin: float
    mdl: float
    violations_json: str
    status: str
    tau: float | None
    delta: float
    calibration_json: str | None
    created_at_ms: int
    actions: tuple[str, ...] = field(default=())

    @property
    def holes(self) -> dict[str, float]:
        return json.loads(self.holes_json or "{}")

    @property
    def violated_clip_ids(self) -> list[str]:
        return json.loads(self.violations_json or "[]")

    @property
    def calibration(self) -> dict[str, Any] | None:
        return json.loads(self.calibration_json) if self.calibration_json else None


@dataclass(frozen=True)
class EventView:
    """An event joined with its clip, primary trace status/summary and (optionally) one concept's label."""
    id: str
    clip_id: str
    source: str
    device_id: str | None
    kind: str | None
    sub_type: str | None
    start_ms: int
    end_ms: int | None
    duration_ms: int | None
    clip_status: str
    clip_error: str | None
    clip_path: str | None
    snapshot_path: str | None
    trace_status: str                 # none | ok | perception_failed
    summary: str | None
    attribution: str | None
    source_ref: str | None
    created_at_ms: int
    label: LabelRow | None = None

    @property
    def has_snapshot(self) -> bool:
        return bool(self.snapshot_path)


# =================================================================================================== helpers
def _ph(n: int) -> str:
    return ",".join("?" * n)


def encode_cursor(start_ms: int, event_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([start_ms, event_id]).encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        start_ms, event_id = json.loads(raw)
        return int(start_ms), str(event_id)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        raise ValueError("invalid cursor") from e


_VIEW_SELECT = """
SELECT e.id AS id, c.id AS clip_id, e.source AS source, e.device_id AS device_id, e.kind AS kind,
       e.sub_type AS sub_type, e.start_ms AS start_ms, e.end_ms AS end_ms,
       c.duration_ms AS clip_duration_ms, c.status AS clip_status, c.error AS clip_error,
       c.path AS clip_path, c.snapshot_path AS snapshot_path, c.attribution AS attribution,
       c.source_ref AS source_ref, e.created_at_ms AS created_at_ms,
       pt.status AS trace_status, json_extract(pt.trace_json, '$.summary') AS summary,
       l.concept_id AS l_concept, l.value AS l_value, l.provenance AS l_prov, l.weight AS l_weight,
       l.created_at_ms AS l_created
FROM events e
JOIN clips c ON c.event_id = e.id
LEFT JOIN v_primary_trace pt ON pt.clip_id = c.id
LEFT JOIN labels l ON l.concept_id = :cid AND l.clip_id = c.id
"""


def _view(r: sqlite3.Row) -> EventView:
    label = None
    if r["l_value"] is not None:
        label = LabelRow(r["l_concept"], r["clip_id"], r["l_value"], r["l_prov"], r["l_weight"], r["l_created"])
    dur = r["clip_duration_ms"]
    if dur is None and r["end_ms"] is not None:
        dur = max(0, r["end_ms"] - r["start_ms"])
    return EventView(
        id=r["id"], clip_id=r["clip_id"], source=r["source"], device_id=r["device_id"], kind=r["kind"],
        sub_type=r["sub_type"], start_ms=r["start_ms"], end_ms=r["end_ms"], duration_ms=dur,
        clip_status=r["clip_status"], clip_error=r["clip_error"], clip_path=r["clip_path"],
        snapshot_path=r["snapshot_path"], trace_status=r["trace_status"] or "none", summary=r["summary"] or None,
        attribution=r["attribution"], source_ref=r["source_ref"], created_at_ms=r["created_at_ms"], label=label)


class _Repo:
    def __init__(self, store: "Store") -> None:
        self.s = store


# =================================================================================================== events
class EventsRepo(_Repo):
    def insert(self, ev: EventRow) -> bool:
        """Insert unless the id exists (ON CONFLICT DO NOTHING: unlike INSERT OR IGNORE it does not swallow CHECK
        violations such as an unknown `source`). True if the row is new."""
        return self.s.execute(
            "INSERT INTO events (id, source, device_id, kind, sub_type, start_ms, end_ms, raw_json, created_at_ms)"
            " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
            (ev.id, ev.source, ev.device_id, ev.kind, ev.sub_type, ev.start_ms, ev.end_ms, ev.raw_json,
             ev.created_at_ms)) == 1

    def get(self, event_id: str) -> EventRow | None:
        r = self.s.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
        return EventRow(**dict(r)) if r else None

    def exists(self, event_id: str) -> bool:
        return self.s.query_one("SELECT 1 FROM events WHERE id = ?", (event_id,)) is not None

    def update_sub_type(self, event_id: str, sub_type: str | None) -> None:
        self.s.execute("UPDATE events SET sub_type = ? WHERE id = ?", (sub_type, event_id))

    def find_near(self, device_id: str | None, start_ms: int, tol_ms: int, source: str = "ring") -> EventRow | None:
        r = self.s.query_one(
            "SELECT * FROM events WHERE source = ? AND device_id IS ? AND ABS(start_ms - ?) <= ? "
            "ORDER BY ABS(start_ms - ?) LIMIT 1", (source, device_id, start_ms, tol_ms, start_ms))
        return EventRow(**dict(r)) if r else None

    def latest_start(self, source: str, device_id: str | None = None) -> int | None:
        if device_id is None:
            r = self.s.query_one("SELECT MAX(start_ms) AS m FROM events WHERE source = ?", (source,))
        else:
            r = self.s.query_one("SELECT MAX(start_ms) AS m FROM events WHERE source = ? AND device_id = ?",
                                 (source, device_id))
        return r["m"] if r and r["m"] is not None else None

    def count(self, source: str | None = None) -> int:
        if source:
            return self.s.query_one("SELECT COUNT(*) AS n FROM events WHERE source = ?", (source,))["n"]
        return self.s.query_one("SELECT COUNT(*) AS n FROM events")["n"]

    def get_view(self, event_id: str, concept_id: str | None = None) -> EventView | None:
        r = self.s.query_one(_VIEW_SELECT + " WHERE e.id = :id", {"cid": concept_id, "id": event_id})
        return _view(r) if r else None

    def view_by_clip(self, clip_id: str, concept_id: str | None = None) -> EventView | None:
        r = self.s.query_one(_VIEW_SELECT + " WHERE c.id = :id", {"cid": concept_id, "id": clip_id})
        return _view(r) if r else None

    def views_by_clips(self, clip_ids: Sequence[str], concept_id: str | None = None) -> dict[str, EventView]:
        out: dict[str, EventView] = {}
        for i in range(0, len(clip_ids), 500):
            for v in self._views_in(list(clip_ids[i:i + 500]), concept_id):
                out[v.clip_id] = v
        return out

    def _views_in(self, clip_ids: Sequence[str], concept_id: str | None) -> list[EventView]:
        names = {f"p{i}": cid for i, cid in enumerate(clip_ids)}
        sql = _VIEW_SELECT + " WHERE c.id IN (" + ",".join(f":{k}" for k in names) + ")"
        return [_view(r) for r in self.s.query(sql, {"cid": concept_id, **names})]

    def list_view(self, *, concept_id: str | None = None, source: str | None = None, labelled: str = "any",
                  limit: int = 100, cursor: str | None = None) -> tuple[list[EventView], str | None]:
        """Newest first (start_ms DESC, id DESC) with keyset pagination. Returns (items, next_cursor)."""
        where: list[str] = []
        params: dict[str, Any] = {"cid": concept_id}
        if source:
            where.append("e.source = :source")
            params["source"] = source
        if labelled in ("pos", "neg"):
            where.append("l.value = :lv")
            params["lv"] = labelled
        elif labelled == "unlabelled":
            where.append("l.clip_id IS NULL")
        if cursor:
            cs, ci = decode_cursor(cursor)
            where.append("(e.start_ms, e.id) < (:cs, :ci)")
            params.update(cs=cs, ci=ci)
        limit = max(1, min(int(limit), 500))
        sql = _VIEW_SELECT + (" WHERE " + " AND ".join(where) if where else "") + \
            " ORDER BY e.start_ms DESC, e.id DESC LIMIT :lim"
        params["lim"] = limit + 1
        rows = [_view(r) for r in self.s.query(sql, params)]
        nxt = None
        if len(rows) > limit:
            rows = rows[:limit]
            nxt = encode_cursor(rows[-1].start_ms, rows[-1].id)
        return rows, nxt


# =================================================================================================== clips
class ClipsRepo(_Repo):
    def insert(self, clip: ClipRow) -> bool:
        return self.s.execute(
            "INSERT INTO clips (id, event_id, path, snapshot_path, sha256, duration_ms, source_ref,"
            " attribution, status, error, created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
            (clip.id, clip.event_id, clip.path, clip.snapshot_path, clip.sha256, clip.duration_ms, clip.source_ref,
             clip.attribution, clip.status, clip.error, clip.created_at_ms)) == 1

    def get(self, clip_id: str) -> ClipRow | None:
        r = self.s.query_one("SELECT * FROM clips WHERE id = ?", (clip_id,))
        return ClipRow(**dict(r)) if r else None

    def by_event(self, event_id: str) -> ClipRow | None:
        r = self.s.query_one("SELECT * FROM clips WHERE event_id = ? ORDER BY created_at_ms LIMIT 1", (event_id,))
        return ClipRow(**dict(r)) if r else None

    def set_status(self, clip_id: str, status: str, error: str | None = None) -> None:
        self.s.execute("UPDATE clips SET status = ?, error = ? WHERE id = ?", (status, error, clip_id))

    def set_error(self, clip_id: str, error: str | None) -> None:
        self.s.execute("UPDATE clips SET error = ? WHERE id = ?", (error, clip_id))

    def set_media(self, clip_id: str, *, path: str | None, snapshot_path: str | None = None, sha256: str | None = None,
                  duration_ms: int | None = None, status: str = "ready") -> None:
        self.s.execute(
            "UPDATE clips SET path = ?, snapshot_path = COALESCE(?, snapshot_path), sha256 = ?,"
            " duration_ms = COALESCE(?, duration_ms), status = ?, error = NULL WHERE id = ?",
            (path, snapshot_path, sha256, duration_ms, status, clip_id))

    def set_snapshot(self, clip_id: str, snapshot_path: str) -> None:
        self.s.execute("UPDATE clips SET snapshot_path = ? WHERE id = ?", (snapshot_path, clip_id))

    def awaiting_perception(self) -> list[ClipRow]:
        """Ready clips with media but no trace at all (a backend outage left them untraced)."""
        rows = self.s.query(
            "SELECT c.* FROM clips c WHERE c.status = 'ready' AND c.path IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM traces t WHERE t.clip_id = c.id) ORDER BY c.created_at_ms")
        return [ClipRow(**dict(r)) for r in rows]

    def awaiting_download(self) -> list[ClipRow]:
        """Clips of ring events whose download never finished (restart mid-flight)."""
        rows = self.s.query(
            "SELECT c.* FROM clips c JOIN events e ON e.id = c.event_id "
            "WHERE c.status IN ('pending','downloading') AND e.source = 'ring' ORDER BY c.created_at_ms")
        return [ClipRow(**dict(r)) for r in rows]


# =================================================================================================== traces
class TracesRepo(_Repo):
    def put(self, clip_id: str, trace: Trace, *, mode: str | None = None, cache_key: str | None = None,
            tokens_in: int | None = None, tokens_out: int | None = None, latency_ms: int | None = None) -> None:
        meta = trace.perception
        mode = mode or (meta.mode if meta else "fast")
        tokens_in = meta.tokens_in if tokens_in is None and meta else (tokens_in or 0)
        tokens_out = meta.tokens_out if tokens_out is None and meta else (tokens_out or 0)
        latency_ms = meta.latency_ms if latency_ms is None and meta else (latency_ms or 0)
        cache_key = cache_key or (meta.cache_key if meta else None)
        self.s.execute(
            "INSERT INTO traces (clip_id, mode, status, trace_json, cache_key, tokens_in, tokens_out, latency_ms,"
            " created_at_ms) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(clip_id, mode) DO UPDATE SET status=excluded.status, trace_json=excluded.trace_json,"
            " cache_key=excluded.cache_key, tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out,"
            " latency_ms=excluded.latency_ms, created_at_ms=excluded.created_at_ms",
            (clip_id, mode, trace.status, trace.model_dump_json(), cache_key, tokens_in, tokens_out, latency_ms,
             now_ms()))

    def get_row(self, clip_id: str, mode: str) -> TraceRow | None:
        r = self.s.query_one("SELECT * FROM traces WHERE clip_id = ? AND mode = ?", (clip_id, mode))
        return TraceRow(**dict(r)) if r else None

    def get(self, clip_id: str, mode: str) -> Trace | None:
        row = self.get_row(clip_id, mode)
        return row.trace() if row else None

    def primary_row(self, clip_id: str) -> TraceRow | None:
        r = self.s.query_one("SELECT * FROM v_primary_trace WHERE clip_id = ?", (clip_id,))
        return TraceRow(**dict(r)) if r else None

    def primary(self, clip_id: str) -> Trace | None:
        row = self.primary_row(clip_id)
        return row.trace() if row else None

    def has_any(self, clip_id: str) -> bool:
        return self.s.query_one("SELECT 1 FROM traces WHERE clip_id = ?", (clip_id,)) is not None

    def list_primary_ok(self) -> list[tuple[str, Trace]]:
        """Every clip's primary trace with status ok, newest event first (backtest, learning)."""
        rows = self.s.query(
            "SELECT pt.clip_id AS clip_id, pt.trace_json AS trace_json FROM v_primary_trace pt "
            "JOIN clips c ON c.id = pt.clip_id JOIN events e ON e.id = c.event_id "
            "WHERE pt.status = 'ok' ORDER BY e.start_ms DESC, e.id DESC")
        return [(r["clip_id"], Trace.model_validate_json(r["trace_json"])) for r in rows]

    def primary_ok_for(self, clip_ids: Sequence[str]) -> dict[str, Trace]:
        out: dict[str, Trace] = {}
        for i in range(0, len(clip_ids), 500):
            chunk = list(clip_ids[i:i + 500])
            rows = self.s.query(
                f"SELECT clip_id, trace_json FROM v_primary_trace WHERE status = 'ok' AND clip_id IN ({_ph(len(chunk))})",
                chunk)
            for r in rows:
                out[r["clip_id"]] = Trace.model_validate_json(r["trace_json"])
        return out

    def unlabelled_ok(self, concept_id: str) -> list[tuple[str, Trace]]:
        """Traced (ok) clips with no label for this concept, newest first."""
        rows = self.s.query(
            "SELECT pt.clip_id AS clip_id, pt.trace_json AS trace_json FROM v_primary_trace pt "
            "JOIN clips c ON c.id = pt.clip_id JOIN events e ON e.id = c.event_id "
            "WHERE pt.status = 'ok' AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.concept_id = ? AND l.clip_id = pt.clip_id) "
            "ORDER BY e.start_ms DESC, e.id DESC", (concept_id,))
        return [(r["clip_id"], Trace.model_validate_json(r["trace_json"])) for r in rows]

    def unlabelled_ok_ids(self, concept_id: str) -> list[str]:
        rows = self.s.query(
            "SELECT pt.clip_id AS clip_id FROM v_primary_trace pt "
            "JOIN clips c ON c.id = pt.clip_id JOIN events e ON e.id = c.event_id "
            "WHERE pt.status = 'ok' AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.concept_id = ? AND l.clip_id = pt.clip_id) "
            "ORDER BY e.start_ms DESC, e.id DESC", (concept_id,))
        return [r["clip_id"] for r in rows]


# =================================================================================================== concepts / labels
class ConceptsRepo(_Repo):
    def create(self, concept_id: str, name: str, nl_hint: str | None, alpha: float) -> ConceptRow:
        row = ConceptRow(concept_id, name, nl_hint, alpha, now_ms())
        self.s.execute("INSERT INTO concepts (id, name, nl_hint, alpha, created_at_ms) VALUES (?,?,?,?,?)",
                       (row.id, row.name, row.nl_hint, row.alpha, row.created_at_ms))
        return row

    def get(self, concept_id: str) -> ConceptRow | None:
        r = self.s.query_one("SELECT * FROM concepts WHERE id = ?", (concept_id,))
        return ConceptRow(**dict(r)) if r else None

    def list(self) -> list[ConceptRow]:
        return [ConceptRow(**dict(r)) for r in self.s.query("SELECT * FROM concepts ORDER BY created_at_ms, id")]

    def counts(self, concept_id: str) -> dict[str, int]:
        out = {f"{p}_{v}": 0 for p in ("example", "active", "random") for v in ("pos", "neg")}
        for r in self.s.query("SELECT provenance, value, COUNT(*) AS n FROM labels WHERE concept_id = ? "
                              "GROUP BY provenance, value", (concept_id,)):
            out[f"{r['provenance']}_{r['value']}"] = r["n"]
        return out


class LabelsRepo(_Repo):
    def put(self, concept_id: str, clip_id: str, value: str, provenance: str, weight: float) -> LabelRow:
        row = LabelRow(concept_id, clip_id, value, provenance, weight, now_ms())
        self.s.execute(
            "INSERT INTO labels (concept_id, clip_id, value, provenance, weight, created_at_ms) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(concept_id, clip_id) DO UPDATE SET value=excluded.value, provenance=excluded.provenance,"
            " weight=excluded.weight, created_at_ms=excluded.created_at_ms",
            (concept_id, clip_id, value, provenance, weight, row.created_at_ms))
        return row

    def put_many(self, concept_id: str, clip_ids: Iterable[str], value: str, provenance: str, weight: float) -> int:
        n = 0
        with self.s.transaction():
            for cid in clip_ids:
                self.put(concept_id, cid, value, provenance, weight)
                n += 1
        return n

    def delete(self, concept_id: str, clip_id: str) -> bool:
        return self.s.execute("DELETE FROM labels WHERE concept_id = ? AND clip_id = ?", (concept_id, clip_id)) > 0

    def get(self, concept_id: str, clip_id: str) -> LabelRow | None:
        r = self.s.query_one("SELECT * FROM labels WHERE concept_id = ? AND clip_id = ?", (concept_id, clip_id))
        return LabelRow(**dict(r)) if r else None

    def list(self, concept_id: str, provenance: Sequence[str] | None = None) -> list[LabelRow]:
        sql, params = "SELECT * FROM labels WHERE concept_id = ?", [concept_id]
        if provenance:
            sql += f" AND provenance IN ({_ph(len(provenance))})"
            params += list(provenance)
        return [LabelRow(**dict(r)) for r in self.s.query(sql + " ORDER BY created_at_ms, clip_id", params)]

    def clip_ids(self, concept_id: str) -> set[str]:
        return {r["clip_id"] for r in self.s.query("SELECT clip_id FROM labels WHERE concept_id = ?", (concept_id,))}


class RandomSamplesRepo(_Repo):
    def add(self, concept_id: str, clip_ids: Iterable[str]) -> None:
        t = now_ms()
        with self.s.transaction():
            for cid in clip_ids:
                self.s.execute("INSERT INTO random_samples (concept_id, clip_id, drawn_at_ms) VALUES (?,?,?) "
                               "ON CONFLICT(concept_id, clip_id) DO NOTHING",
                               (concept_id, cid, t))

    def all_for(self, concept_id: str) -> set[str]:
        return {r["clip_id"] for r in self.s.query("SELECT clip_id FROM random_samples WHERE concept_id = ?",
                                                   (concept_id,))}

    def drawn(self, concept_id: str, clip_ids: Sequence[str]) -> set[str]:
        out: set[str] = set()
        for i in range(0, len(clip_ids), 500):
            chunk = list(clip_ids[i:i + 500])
            out |= {r["clip_id"] for r in self.s.query(
                f"SELECT clip_id FROM random_samples WHERE concept_id = ? AND clip_id IN ({_ph(len(chunk))})",
                [concept_id, *chunk])}
        return out


# =================================================================================================== runs
class RunsRepo(_Repo):
    def create(self, run_id: str, concept_id: str) -> RunRow:
        row = RunRow(run_id, concept_id, "running", now_ms())
        self.s.execute("INSERT INTO runs (id, concept_id, status, started_at_ms) VALUES (?,?,?,?)",
                       (row.id, row.concept_id, row.status, row.started_at_ms))
        return row

    def get(self, run_id: str) -> RunRow | None:
        r = self.s.query_one("SELECT * FROM runs WHERE id = ?", (run_id,))
        return RunRow(**dict(r)) if r else None

    def finish(self, run_id: str, status: str, error: str | None = None) -> None:
        self.s.execute("UPDATE runs SET status = ?, error = ?, finished_at_ms = ? WHERE id = ?",
                       (status, error, now_ms(), run_id))

    def running_for_concept(self, concept_id: str) -> RunRow | None:
        r = self.s.query_one("SELECT * FROM runs WHERE concept_id = ? AND status = 'running' "
                             "ORDER BY started_at_ms DESC LIMIT 1", (concept_id,))
        return RunRow(**dict(r)) if r else None

    def latest_for_concept(self, concept_id: str) -> RunRow | None:
        r = self.s.query_one("SELECT * FROM runs WHERE concept_id = ? ORDER BY started_at_ms DESC, id DESC LIMIT 1",
                             (concept_id,))
        return RunRow(**dict(r)) if r else None

    def fail_stale(self, error: str = "engine restarted while the run was in progress") -> int:
        return self.s.execute("UPDATE runs SET status = 'failed', error = ?, finished_at_ms = ? WHERE status = 'running'",
                              (error, now_ms()))

    # ---- run_events
    def append_event(self, run_id: str, seq: int, type_: str, payload: dict[str, Any], at_ms: int) -> None:
        self.s.execute("INSERT INTO run_events (run_id, seq, type, payload_json, created_at_ms) VALUES (?,?,?,?,?)",
                       (run_id, seq, type_, json.dumps(payload, separators=(",", ":")), at_ms))

    def events(self, run_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        rows = self.s.query("SELECT payload_json FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq",
                            (run_id, after_seq))
        return [json.loads(r["payload_json"]) for r in rows]

    def last_seq(self, run_id: str) -> int:
        r = self.s.query_one("SELECT MAX(seq) AS m FROM run_events WHERE run_id = ?", (run_id,))
        return r["m"] or 0


# =================================================================================================== rules
_RULE_UPDATABLE = {"status", "tau", "delta", "calibration_json", "run_id", "english", "dsl_text"}


class RulesRepo(_Repo):
    def insert(self, *, rule_id: str, concept_id: str, run_id: str | None, sketch_text: str, dsl_text: str,
               ast_json: str, english: str, holes: dict[str, float], margin: float, mdl: float,
               violated_clip_ids: Sequence[str], status: str = "candidate", delta: float = 0.1,
               actions: Sequence[str] = ("ui",)) -> RuleRow:
        t = now_ms()
        with self.s.transaction():
            self.s.execute(
                "INSERT INTO rules (id, concept_id, run_id, sketch_text, dsl_text, ast_json, english, holes_json,"
                " margin, mdl, violations_json, status, delta, created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rule_id, concept_id, run_id, sketch_text, dsl_text, ast_json, english, json.dumps(holes),
                 float(margin), float(mdl), json.dumps(list(violated_clip_ids)), status, float(delta), t))
            self.set_actions(rule_id, actions)
        return self.get(rule_id)  # type: ignore[return-value]

    def _rows(self, rows: list[sqlite3.Row]) -> list[RuleRow]:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        acts: dict[str, list[str]] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for a in self.s.query(f"SELECT rule_id, action FROM rule_actions WHERE rule_id IN ({_ph(len(chunk))}) "
                                  "ORDER BY action", chunk):
                acts.setdefault(a["rule_id"], []).append(a["action"])
        return [RuleRow(**dict(r), actions=tuple(acts.get(r["id"], ()))) for r in rows]

    def get(self, rule_id: str) -> RuleRow | None:
        rows = self._rows(self.s.query("SELECT * FROM rules WHERE id = ?", (rule_id,)))
        return rows[0] if rows else None

    def list_for_concept(self, concept_id: str, *, include_retired: bool = False) -> list[RuleRow]:
        sql = "SELECT * FROM rules WHERE concept_id = ?"
        if not include_retired:
            sql += " AND status != 'retired'"
        sql += " ORDER BY mdl ASC, margin DESC, created_at_ms DESC, id"
        return self._rows(self.s.query(sql, (concept_id,)))

    def deployed(self) -> list[RuleRow]:
        return self._rows(self.s.query("SELECT * FROM rules WHERE status = 'deployed' ORDER BY created_at_ms"))

    def deployed_for_concept(self, concept_id: str) -> RuleRow | None:
        rows = self._rows(self.s.query("SELECT * FROM rules WHERE concept_id = ? AND status = 'deployed' "
                                       "ORDER BY created_at_ms DESC LIMIT 1", (concept_id,)))
        return rows[0] if rows else None

    def find_by_dsl(self, concept_id: str, dsl_text: str) -> RuleRow | None:
        rows = self._rows(self.s.query("SELECT * FROM rules WHERE concept_id = ? AND dsl_text = ? "
                                       "AND status != 'retired' LIMIT 1", (concept_id, dsl_text)))
        return rows[0] if rows else None

    def update(self, rule_id: str, **fields: Any) -> None:
        bad = set(fields) - _RULE_UPDATABLE
        if bad:
            raise ValueError(f"cannot update rule columns {sorted(bad)}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.s.execute(f"UPDATE rules SET {sets} WHERE id = ?", [*fields.values(), rule_id])

    def set_calibration(self, rule_id: str, *, tau: float, delta: float, calibration: dict[str, Any]) -> None:
        self.update(rule_id, tau=float(tau), delta=float(delta), calibration_json=json.dumps(calibration))

    def supersede_candidates(self, concept_id: str, keep_ids: Sequence[str]) -> int:
        """Retire earlier plain candidates of the concept when a new run produced a fresh set."""
        sql = "UPDATE rules SET status = 'retired' WHERE concept_id = ? AND status = 'candidate'"
        params: list[Any] = [concept_id]
        if keep_ids:
            sql += f" AND id NOT IN ({_ph(len(keep_ids))})"
            params += list(keep_ids)
        return self.s.execute(sql, params)

    def set_actions(self, rule_id: str, actions: Sequence[str]) -> None:
        with self.s.transaction():
            self.s.execute("DELETE FROM rule_actions WHERE rule_id = ?", (rule_id,))
            for a in dict.fromkeys(actions):
                self.s.execute("INSERT INTO rule_actions (rule_id, action) VALUES (?,?)", (rule_id, a))


# =================================================================================================== firings
class FiringsRepo(_Repo):
    def exists(self, rule_id: str, event_id: str) -> bool:
        return self.s.query_one("SELECT 1 FROM firings WHERE rule_id = ? AND event_id = ?", (rule_id, event_id)) is not None

    def upsert(self, f: dict[str, Any]) -> str:
        """Persist an api.yaml Firing dict (keyed by (rule_id, event_id)); returns the stored firing id.
        Actions are logged once, when the row is first created."""
        witness = f.get("witness")
        with self.s.transaction():
            existing = self.s.query_one("SELECT id FROM firings WHERE rule_id = ? AND event_id = ?",
                                        (f["rule_id"], f["event_id"]))
            if existing:
                fid = existing["id"]
                self.s.execute(
                    "UPDATE firings SET stage = ?, score = ?, tau = ?, fired = ?, witness_json = ?, created_at_ms = ? "
                    "WHERE id = ?",
                    (int(f["stage"]), f.get("score"), f.get("tau"), 1 if f.get("fired") else 0,
                     json.dumps(witness) if witness else None, int(f.get("created_at_ms") or now_ms()), fid))
                return fid
            fid = f["id"]
            self.s.execute(
                "INSERT INTO firings (id, rule_id, event_id, stage, score, tau, fired, witness_json, created_at_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (fid, f["rule_id"], f["event_id"], int(f["stage"]), f.get("score"), f.get("tau"),
                 1 if f.get("fired") else 0, json.dumps(witness) if witness else None,
                 int(f.get("created_at_ms") or now_ms())))
            for a in f.get("actions") or []:
                self.s.execute("INSERT INTO actions_log (firing_id, action, status, detail, created_at_ms) VALUES (?,?,?,?,?)",
                               (fid, a["action"], a["status"], a.get("detail"), int(f.get("created_at_ms") or now_ms())))
            return fid

    def add_action(self, firing_id: str, action: str, status: str, detail: str | None) -> None:
        self.s.execute("INSERT INTO actions_log (firing_id, action, status, detail, created_at_ms) VALUES (?,?,?,?,?)",
                       (firing_id, action, status, detail, now_ms()))

    def _dicts(self, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        acts: dict[str, list[dict[str, Any]]] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for a in self.s.query(f"SELECT firing_id, action, status, detail FROM actions_log "
                                  f"WHERE firing_id IN ({_ph(len(chunk))}) ORDER BY id", chunk):
                acts.setdefault(a["firing_id"], []).append(
                    {"action": a["action"], "status": a["status"], "detail": a["detail"]})
        return [{"id": r["id"], "rule_id": r["rule_id"], "event_id": r["event_id"], "stage": r["stage"],
                 "score": r["score"], "tau": r["tau"], "fired": bool(r["fired"]),
                 "witness": json.loads(r["witness_json"]) if r["witness_json"] else None,
                 "actions": acts.get(r["id"], []), "created_at_ms": r["created_at_ms"]} for r in rows]

    def list(self, rule_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM firings", []
        if rule_id:
            sql += " WHERE rule_id = ?"
            params.append(rule_id)
        sql += " ORDER BY created_at_ms DESC, id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        return self._dicts(self.s.query(sql, params))

    def get(self, firing_id: str) -> dict[str, Any] | None:
        rows = self._dicts(self.s.query("SELECT * FROM firings WHERE id = ?", (firing_id,)))
        return rows[0] if rows else None

    def stage_counts(self) -> dict[int, int]:
        return {r["stage"]: r["n"] for r in self.s.query("SELECT stage, COUNT(*) AS n FROM firings GROUP BY stage")}

    def distinct_events(self) -> int:
        return self.s.query_one("SELECT COUNT(DISTINCT event_id) AS n FROM firings")["n"]


# =================================================================================================== webhooks / cost / auth
class WebhooksRepo(_Repo):
    def claim(self, request_id: str, event_type: str | None = None) -> bool:
        """A's `WebhookDeduper.claim`: atomically record `request_id` (an insert that ignores only a duplicate
        primary key); False if it was already delivered."""
        return self.s.execute(
            "INSERT INTO webhook_deliveries (request_id, event_type, received_at_ms) VALUES (?,?,?) "
            "ON CONFLICT(request_id) DO NOTHING",
            (request_id, event_type, now_ms())) == 1

    def release(self, request_id: str) -> None:
        self.s.execute("DELETE FROM webhook_deliveries WHERE request_id = ?", (request_id,))


class CostRepo(_Repo):
    def add(self, purpose: str, *, model_alias: str | None = None, clip_id: str | None = None,
            run_id: str | None = None, tokens_in: int = 0, tokens_out: int = 0, latency_ms: int = 0) -> int:
        return self.s.insert(
            "INSERT INTO cost_ledger (purpose, model_alias, clip_id, run_id, tokens_in, tokens_out, latency_ms,"
            " created_at_ms) VALUES (?,?,?,?,?,?,?,?)",
            (purpose, model_alias, clip_id, run_id, int(tokens_in), int(tokens_out), int(latency_ms), now_ms()))

    def distinct_clips(self) -> int:
        """Clips that cost something (perception calls); the denominator of per-event cost before any rule runs."""
        return self.s.query_one("SELECT COUNT(DISTINCT clip_id) AS n FROM cost_ledger WHERE clip_id IS NOT NULL")["n"]

    def totals(self) -> dict[str, dict[str, int]]:
        """{purpose: {calls, tokens_in, tokens_out}}"""
        return {r["purpose"]: {"calls": r["n"], "tokens_in": r["ti"] or 0, "tokens_out": r["to"] or 0}
                for r in self.s.query("SELECT purpose, COUNT(*) AS n, SUM(tokens_in) AS ti, SUM(tokens_out) AS 'to' "
                                      "FROM cost_ledger GROUP BY purpose")}


class AuthRepo(_Repo):
    """A's `TokenStore` over the single-row `ring_auth` table."""

    def load(self) -> StoredAuth | None:
        r = self.s.query_one("SELECT * FROM ring_auth WHERE id = 1")
        if not r:
            return None
        return StoredAuth(mode=r["mode"], access_token=r["access_token"], refresh_token=r["refresh_token"],
                          issued_at_ms=r["issued_at_ms"], expires_at_ms=r["expires_at_ms"],
                          updated_at_ms=r["updated_at_ms"])

    def save(self, auth: StoredAuth) -> None:
        self.s.execute(
            "INSERT INTO ring_auth (id, mode, access_token, refresh_token, issued_at_ms, expires_at_ms, updated_at_ms)"
            " VALUES (1,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET mode=excluded.mode,"
            " access_token=excluded.access_token, refresh_token=excluded.refresh_token,"
            " issued_at_ms=excluded.issued_at_ms, expires_at_ms=excluded.expires_at_ms,"
            " updated_at_ms=excluded.updated_at_ms",
            (auth.mode, auth.access_token, auth.refresh_token, auth.issued_at_ms, auth.expires_at_ms,
             auth.updated_at_ms or now_ms()))

    def clear(self) -> None:
        self.s.execute("DELETE FROM ring_auth WHERE id = 1")
