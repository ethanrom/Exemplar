-- Exemplar SQLite schema (PLAN.md §1 store/). Frozen contract — changes go through the integrator.
-- JSON columns hold the pydantic models from exemplar.contracts (model_dump_json()).
-- Times: *_ms columns are epoch milliseconds (UTC) unless noted.
PRAGMA foreign_keys = ON;

-- One row per Ring event (webhook / history poll), live-view capture, MEVA window, or fixture.
CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,            -- ring history id, webhook data.id, or synthetic
    source          TEXT NOT NULL CHECK (source IN ('ring', 'ring_live', 'upload', 'meva', 'fixture')),
    device_id       TEXT,
    kind            TEXT,                        -- motion | ding | on_demand | live | upload | <meva activity>
    sub_type        TEXT,                        -- human | vehicle | package_delivery | other_motion | NULL
    start_ms        INTEGER NOT NULL,
    end_ms          INTEGER,
    raw_json        TEXT,                        -- original payload (webhook body / history item)
    created_at_ms   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_start ON events (start_ms);

-- Media for an event. One clip per event in v1.
CREATE TABLE IF NOT EXISTS clips (
    id              TEXT PRIMARY KEY,            -- = trace.clip_id
    event_id        TEXT NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    path            TEXT,                        -- local file (data/clips/…); NULL for frame-only live captures
    snapshot_path   TEXT,
    sha256          TEXT,
    duration_ms     INTEGER,
    source_ref      TEXT,                        -- upload/meva: source file or URL + window, e.g. "youtube:TfTFu8lGrwk@12.0+20.0"
    attribution     TEXT,                        -- CC BY credit line for third-party footage
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'downloading', 'ready', 'not_found', 'failed')),
    error           TEXT,
    created_at_ms   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS clips_event ON clips (event_id);

-- Perception output. A clip may have a fast trace and later a strong (escalation) trace.
CREATE TABLE IF NOT EXISTS traces (
    clip_id         TEXT NOT NULL REFERENCES clips (id) ON DELETE CASCADE,
    mode            TEXT NOT NULL CHECK (mode IN ('fast', 'strong', 'fixture', 'manual')),
    status          TEXT NOT NULL CHECK (status IN ('ok', 'perception_failed')),
    trace_json      TEXT NOT NULL,               -- exemplar.contracts.trace.Trace
    cache_key       TEXT,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    created_at_ms   INTEGER NOT NULL,
    PRIMARY KEY (clip_id, mode)
);

-- What the user is teaching ("package taken by a non-deliverer").
CREATE TABLE IF NOT EXISTS concepts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    nl_hint         TEXT,
    alpha           REAL NOT NULL DEFAULT 0.1,
    created_at_ms   INTEGER NOT NULL
);

-- exemplar.contracts.labels.Label. One label per (concept, clip); relabelling replaces it.
CREATE TABLE IF NOT EXISTS labels (
    concept_id      TEXT NOT NULL REFERENCES concepts (id) ON DELETE CASCADE,
    clip_id         TEXT NOT NULL REFERENCES clips (id) ON DELETE CASCADE,
    value           TEXT NOT NULL CHECK (value IN ('pos', 'neg')),
    provenance      TEXT NOT NULL CHECK (provenance IN ('example', 'active', 'random')),
    weight          REAL NOT NULL DEFAULT 3.0 CHECK (weight > 0),
    created_at_ms   INTEGER NOT NULL,
    PRIMARY KEY (concept_id, clip_id)
);

-- A synthesis run (one "Teach" click): the CEGIS agent's timeline is replayable from run_events.
CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    concept_id      TEXT NOT NULL REFERENCES concepts (id) ON DELETE CASCADE,
    status          TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed', 'cancelled')),
    error           TEXT,
    started_at_ms   INTEGER NOT NULL,
    finished_at_ms  INTEGER
);
CREATE TABLE IF NOT EXISTS run_events (
    run_id          TEXT NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    type            TEXT NOT NULL,               -- SSE event type, see api.yaml RunEvent
    payload_json    TEXT NOT NULL,
    created_at_ms   INTEGER NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- Candidate and deployed rules. Closed rules only (holes filled).
CREATE TABLE IF NOT EXISTS rules (
    id              TEXT PRIMARY KEY,
    concept_id      TEXT NOT NULL REFERENCES concepts (id) ON DELETE CASCADE,
    run_id          TEXT REFERENCES runs (id) ON DELETE SET NULL,
    sketch_text     TEXT NOT NULL,               -- DSL with holes, as proposed
    dsl_text        TEXT NOT NULL,               -- DSL, holes filled (canonical printer)
    ast_json        TEXT NOT NULL,               -- exemplar.contracts.dsl_ast.Rule (closed)
    english         TEXT NOT NULL,               -- deterministic printer output
    holes_json      TEXT NOT NULL DEFAULT '{}',  -- {"b": 20.0, ...}
    margin          REAL NOT NULL,               -- m from the solver
    mdl             REAL NOT NULL,
    violations_json TEXT NOT NULL DEFAULT '[]',  -- clip ids of violated (perception-suspect) examples
    status          TEXT NOT NULL DEFAULT 'candidate'
                    CHECK (status IN ('candidate', 'selected', 'deployed', 'retired')),
    tau             REAL,                        -- conformal threshold τ_α; NULL until calibrated
    delta           REAL NOT NULL DEFAULT 0.1,   -- escalation band half-width δ
    calibration_json TEXT,                       -- api.yaml Calibration
    created_at_ms   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS rules_concept ON rules (concept_id, status);

-- Per (rule, event) monitor outcome: fired or dropped, with the stage that decided it.
CREATE TABLE IF NOT EXISTS firings (
    id              TEXT PRIMARY KEY,
    rule_id         TEXT NOT NULL REFERENCES rules (id) ON DELETE CASCADE,
    event_id        TEXT NOT NULL REFERENCES events (id) ON DELETE CASCADE,
    stage           INTEGER NOT NULL CHECK (stage IN (0, 1, 2)),   -- 0 subtype prefilter, 1 fast, 2 escalated
    score           REAL,
    tau             REAL,
    fired           INTEGER NOT NULL CHECK (fired IN (0, 1)),
    witness_json    TEXT,                        -- api.yaml Witness (only when fired)
    created_at_ms   INTEGER NOT NULL,
    UNIQUE (rule_id, event_id)
);

CREATE TABLE IF NOT EXISTS actions_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    firing_id       TEXT NOT NULL REFERENCES firings (id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK (action IN ('ui', 'webhook_out', 'slack', 'chime')),
    status          TEXT NOT NULL CHECK (status IN ('ok', 'skipped', 'failed')),
    detail          TEXT,
    created_at_ms   INTEGER NOT NULL
);

-- Webhook dedupe on meta.request_id (PLAN.md §2.7).
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    request_id      TEXT PRIMARY KEY,
    event_type      TEXT,
    received_at_ms  INTEGER NOT NULL
);

-- Cost meter (§2.6): one row per model call.
CREATE TABLE IF NOT EXISTS cost_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose         TEXT NOT NULL CHECK (purpose IN ('perception_fast', 'perception_strong', 'sketch', 'baseline')),
    model_alias     TEXT,
    clip_id         TEXT,
    run_id          TEXT,
    tokens_in       INTEGER NOT NULL DEFAULT 0,
    tokens_out      INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    created_at_ms   INTEGER NOT NULL
);

-- Ring token state (Playground paste or OAuth). Secrets live here only on the local dev box.
CREATE TABLE IF NOT EXISTS ring_auth (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    mode            TEXT NOT NULL CHECK (mode IN ('playground', 'oauth')),
    access_token    TEXT,
    refresh_token   TEXT,
    issued_at_ms    INTEGER,
    expires_at_ms   INTEGER,
    updated_at_ms   INTEGER NOT NULL
);

-- Added in contracts 1.1.0 (from stream H) ---------------------------------------------------------
-- Actions configured on a rule (PATCH /rules/{id} actions).
-- Clips handed out by POST /concepts/{id}/random-sample: only these may be labelled with provenance
-- 'random' (the engine returns 400 INVALID_PROVENANCE otherwise), which keeps calibration labels
-- uniformly sampled, as the conformal guarantee requires.
-- v_primary_trace: the trace to use for a clip (ok before failed; manual > fast > fixture > strong).
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
