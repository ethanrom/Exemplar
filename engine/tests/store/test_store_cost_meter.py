"""Regression: the live cost meter must be the cost of watching (perception of monitored events / monitored
events), not every model call ever made divided by the monitored-event count (seeding, uploads and teach-time
agent calls inflated it ~10x during the 2026-10-15 Playground run)."""
from __future__ import annotations

from exemplar.api import cost as cost_mod
from exemplar.store import Store


def _event_with_clip(s: Store, eid: str) -> None:
    s._conn.execute("INSERT INTO events (id, source, start_ms, created_at_ms) VALUES (?, 'ring', 0, 0)", (eid,))
    s._conn.execute("INSERT INTO clips (id, event_id, status, created_at_ms) VALUES (?, ?, 'ready', 0)", (f"c-{eid}", eid))


def test_meter_counts_only_monitored_perception():
    s = Store(":memory:")
    _event_with_clip(s, "seeded")                     # imported by the seed CLI, never scored by a rule
    _event_with_clip(s, "watched")                    # scored by the monitor
    s._conn.execute("INSERT INTO concepts (id, name, created_at_ms) VALUES ('cn', 'x', 0)")
    s._conn.execute("INSERT INTO rules (id, concept_id, sketch_text, dsl_text, ast_json, english, margin, mdl, created_at_ms)"
                    " VALUES ('ru', 'cn', 's', 'd', '{}', 'e', 0.45, 8.8, 0)")
    s._conn.execute("INSERT INTO firings (id, rule_id, event_id, stage, score, fired, created_at_ms)"
                    " VALUES ('f1', 'ru', 'watched', 1, 0.45, 1, 0)")
    s.cost.add("perception_fast", clip_id="c-seeded", tokens_in=100_000, tokens_out=20_000)
    s.cost.add("perception_fast", clip_id="c-watched", tokens_in=6_400, tokens_out=1_500)
    s.cost.add("sketch", run_id="run1", tokens_in=1_000_000, tokens_out=100_000)        # teach-time agent call

    mon = s.cost.perception_totals(monitored_only=True)
    assert mon == {"perception_fast": {"calls": 1, "tokens_in": 6_400, "tokens_out": 1_500}}
    out = cost_mod.summarize(mon, s.firings.stage_counts(), 1, per_event_denominator=1)
    assert abs(out["per_event_usd"] - (6_400 * 0.10 + 1_500 * 0.50) / 1e6) < 1e-9          # ~$0.0014
    allp = s.cost.perception_totals(monitored_only=False)
    assert "sketch" not in allp and allp["perception_fast"]["calls"] == 2
