"""SQLite store (PLAN.md §1 `store/`) over the frozen `contracts/schema.sql`.

One connection shared by every thread behind an `RLock` (FastAPI calls in via its threadpool, the ingest
workers, the teach thread and the event loop all touch it). Statements are tiny, so the lock is held for
microseconds; that also keeps `:memory:` databases (tests) working, which a connection-per-thread design
would not. WAL + foreign keys + a busy timeout are enabled for file databases.

Two additions beside the frozen schema, both created here with `IF NOT EXISTS` (see EXTENSIONS_SQL; they are
reported to the integrator as schema gaps):
  * `rule_actions`   - the actions enabled per rule (`rules` has no column for them);
  * `random_samples` - which clips `/random-sample` handed out per concept, so provenance `random` can be
                       restricted to uniformly drawn clips (the conformal guarantee depends on it).
and the view `v_primary_trace` (one trace per clip: an `ok` one beats a failed one, then manual > fast >
fixture > strong).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from .repos import (AuthRepo, ClipsRepo, ConceptsRepo, CostRepo, EventsRepo, FiringsRepo, LabelsRepo, RandomSamplesRepo,
                    RulesRepo, RunsRepo, TracesRepo, WebhooksRepo, now_ms)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "contracts" / "schema.sql"

EXTENSIONS_SQL = """
CREATE TABLE IF NOT EXISTS rule_actions (
    rule_id         TEXT NOT NULL REFERENCES rules (id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK (action IN ('ui', 'webhook_out', 'slack', 'chime')),
    PRIMARY KEY (rule_id, action)
);
CREATE TABLE IF NOT EXISTS random_samples (
    concept_id      TEXT NOT NULL REFERENCES concepts (id) ON DELETE CASCADE,
    clip_id         TEXT NOT NULL REFERENCES clips (id) ON DELETE CASCADE,
    drawn_at_ms     INTEGER NOT NULL,
    PRIMARY KEY (concept_id, clip_id)
);
CREATE VIEW IF NOT EXISTS v_primary_trace AS
SELECT clip_id, mode, status, trace_json, cache_key, tokens_in, tokens_out, latency_ms, created_at_ms
FROM (SELECT t.*, ROW_NUMBER() OVER (
          PARTITION BY clip_id
          ORDER BY CASE status WHEN 'ok' THEN 0 ELSE 1 END,
                   CASE mode WHEN 'manual' THEN 0 WHEN 'fast' THEN 1 WHEN 'fixture' THEN 2 ELSE 3 END) AS rn
      FROM traces t)
WHERE rn = 1;
"""


__all__ = ["Store", "now_ms", "SCHEMA_PATH", "EXTENSIONS_SQL"]


class Store:
    """`Store(db_path)`; `":memory:"` is accepted. Repositories hang off it as attributes."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.path = str(db_path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA busy_timeout = 30000")
            self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            self._conn.executescript(EXTENSIONS_SQL)
            self._conn.execute("PRAGMA foreign_keys = ON")      # executescript may reset the session state
        self.events = EventsRepo(self)
        self.clips = ClipsRepo(self)
        self.traces = TracesRepo(self)
        self.concepts = ConceptsRepo(self)
        self.labels = LabelsRepo(self)
        self.random_samples = RandomSamplesRepo(self)
        self.runs = RunsRepo(self)
        self.rules = RulesRepo(self)
        self.firings = FiringsRepo(self)
        self.webhooks = WebhooksRepo(self)
        self.cost = CostRepo(self)
        self.auth = AuthRepo(self)

    # ---------------------------------------------------------------- primitives
    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        """Run one statement; returns the affected row count."""
        with self._lock:
            return self._conn.execute(sql, params).rowcount

    def insert(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        """Run one INSERT; returns `lastrowid`."""
        with self._lock:
            return self._conn.execute(sql, params).lastrowid or 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE .. COMMIT (ROLLBACK on error). Re-entrant: nested use joins the outer transaction."""
        with self._lock:
            if self._conn.in_transaction:
                yield
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
