"""Store: schema, repositories, TokenStore / WebhookDeduper adapters, concurrency."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from exemplar.contracts.trace import PerceptionMeta, Trace
from exemplar.ring import AuthManager, InMemoryDeduper, StoredAuth, process_delivery, sign_body
from exemplar.store import ClipRow, EventRow, Store, decode_cursor, encode_cursor, now_ms

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def trace(name: str, clip_id: str | None = None, **update) -> Trace:
    tr = Trace.model_validate_json((FIXTURES / "traces" / f"{name}.json").read_text(encoding="utf-8"))
    return tr.model_copy(update={"clip_id": clip_id or tr.clip_id, **update})


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "db" / "x.sqlite3")
    yield s
    s.close()


def add_event(s: Store, eid: str, start: int = 1000, *, source="ring", device="dev1", kind="on_demand", sub=None, clip=True):
    s.events.insert(EventRow(id=eid, source=source, start_ms=start, created_at_ms=now_ms(), device_id=device, kind=kind,
                             sub_type=sub, end_ms=start + 5000))
    if clip:
        s.clips.insert(ClipRow(id=eid, event_id=eid, created_at_ms=now_ms(), status="ready", path=f"/x/{eid}.mp4"))


# ------------------------------------------------------------------------------------------ schema / connection
def test_applies_the_frozen_schema_and_pragmas(store):
    tables = {r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"events", "clips", "traces", "concepts", "labels", "runs", "run_events", "rules", "firings", "actions_log",
            "webhook_deliveries", "cost_ledger", "ring_auth"} <= tables
    assert store.query_one("PRAGMA foreign_keys")[0] == 1
    assert store.query_one("PRAGMA journal_mode")[0] == "wal"


def test_reopening_keeps_data_and_is_idempotent(tmp_path):
    p = tmp_path / "again.sqlite3"
    with Store(p) as s:
        add_event(s, "e1")
    with Store(p) as s:
        assert s.events.get("e1").id == "e1"


def test_memory_database_works():
    with Store(":memory:") as s:
        add_event(s, "e1")
        assert s.events.count() == 1


def test_foreign_keys_are_enforced_and_cascade(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.clips.insert(ClipRow(id="c", event_id="missing", created_at_ms=1))
    add_event(store, "e1")
    store.traces.put("e1", trace("theft_a", "e1"), mode="fast")
    store.concepts.create("cn", "n", None, 0.1)
    store.labels.put("cn", "e1", "pos", "example", 3.0)
    store.execute("DELETE FROM events WHERE id = 'e1'")                      # event -> clip -> trace, label
    assert store.clips.get("e1") is None and store.traces.get("e1", "fast") is None
    assert store.labels.list("cn") == []


def test_check_constraints_reject_bad_enums(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.events.insert(EventRow(id="x", source="cctv", start_ms=1, created_at_ms=1))
    store.concepts.create("cn", "n", None, 0.1)
    add_event(store, "e1")
    with pytest.raises(sqlite3.IntegrityError):
        store.labels.put("cn", "e1", "maybe", "example", 3.0)
    with pytest.raises(sqlite3.IntegrityError):
        store.labels.put("cn", "e1", "pos", "guess", 3.0)


def test_transaction_rolls_back_and_nests(store):
    with pytest.raises(RuntimeError):
        with store.transaction():
            add_event(store, "e1")
            raise RuntimeError("boom")
    assert store.events.get("e1") is None
    with store.transaction():
        with store.transaction():
            add_event(store, "e2")
    assert store.events.get("e2") is not None


# ------------------------------------------------------------------------------------------ events / clips
def test_event_insert_is_ignore_on_duplicate(store):
    add_event(store, "e1", 1000)
    assert store.events.insert(EventRow(id="e1", source="ring", start_ms=9, created_at_ms=1)) is False
    assert store.events.get("e1").start_ms == 1000


def test_event_view_joins_clip_trace_summary_and_label(store):
    add_event(store, "e1", 1000, sub="on_demand")
    add_event(store, "e2", 2000, clip=True)
    store.traces.put("e1", trace("theft_a", "e1"), mode="fast")
    store.traces.put("e2", trace("perception_failed", "e2"), mode="fast")
    store.concepts.create("cn", "n", None, 0.1)
    store.labels.put("cn", "e1", "pos", "example", 3.0)
    v1, v2 = store.events.get_view("e1", "cn"), store.events.get_view("e2", "cn")
    assert (v1.trace_status, v1.label.value, v1.duration_ms) == ("ok", "pos", 5000) and v1.summary.startswith("A person")
    assert (v2.trace_status, v2.summary, v2.label) == ("perception_failed", None, None)
    assert store.events.get_view("e1").label is None                          # no concept -> no label
    assert store.events.get_view("nope") is None


def test_primary_trace_prefers_ok_then_manual_fast_fixture_strong(store):
    add_event(store, "e1")
    store.traces.put("e1", trace("perception_failed", "e1"), mode="fast")
    assert store.traces.primary_row("e1").status == "perception_failed"
    store.traces.put("e1", trace("theft_a", "e1", perception=PerceptionMeta(mode="strong")), mode="strong")
    assert store.traces.primary_row("e1").mode == "strong"                    # an ok strong beats a failed fast
    store.traces.put("e1", trace("theft_a", "e1", perception=PerceptionMeta(mode="fast", tokens_in=7, tokens_out=3)), mode="fast")
    assert store.traces.primary_row("e1").mode == "fast"
    store.traces.put("e1", trace("theft_b", "e1"), mode="manual")
    assert store.traces.primary_row("e1").mode == "manual"
    row = store.traces.get_row("e1", "fast")
    assert (row.tokens_in, row.tokens_out) == (7, 3) and row.status == "ok"


def test_trace_put_upserts_and_roundtrips(store):
    add_event(store, "e1")
    tr = trace("theft_a", "e1")
    store.traces.put("e1", tr, mode="fast")
    store.traces.put("e1", trace("theft_b", "e1"), mode="fast")
    assert store.query_one("SELECT COUNT(*) FROM traces")[0] == 1
    assert store.traces.get("e1", "fast").summary == trace("theft_b", "e1").summary
    assert store.traces.has_any("e1") and not store.traces.has_any("zzz")


def test_list_view_cursor_is_stable_and_filters(store):
    for i in range(7):
        add_event(store, f"e{i}", 1000 + (i // 2) * 10, source="ring" if i % 2 else "upload", kind="x")   # equal start_ms ties
    store.concepts.create("cn", "n", None, 0.1)
    store.labels.put("cn", "e0", "pos", "example", 3.0)
    store.labels.put("cn", "e1", "neg", "example", 3.0)
    ids, cursor = [], None
    while True:
        page, cursor = store.events.list_view(limit=3, cursor=cursor)
        ids += [v.id for v in page]
        if not cursor:
            break
    assert len(ids) == len(set(ids)) == 7
    assert [v.id for v in store.events.list_view(source="upload")[0]] == ["e6", "e4", "e2", "e0"]
    assert [v.id for v in store.events.list_view(concept_id="cn", labelled="pos")[0]] == ["e0"]
    assert {v.id for v in store.events.list_view(concept_id="cn", labelled="unlabelled")[0]} == {f"e{i}" for i in range(2, 7)}
    with pytest.raises(ValueError):
        store.events.list_view(cursor="%%%")
    assert decode_cursor(encode_cursor(5, "abc")) == (5, "abc")


def test_find_near_and_latest_start(store):
    add_event(store, "e1", 10_000, device="d1")
    add_event(store, "e2", 50_000, device="d2")
    assert store.events.find_near("d1", 12_000, 5_000).id == "e1"
    assert store.events.find_near("d1", 30_000, 5_000) is None
    assert store.events.find_near("d2", 10_000, 5_000) is None                 # other device
    assert store.events.latest_start("ring") == 50_000 and store.events.latest_start("ring", "d1") == 10_000
    assert store.events.latest_start("upload") is None


def test_clip_awaiting_queries(store):
    store.events.insert(EventRow(id="a", source="ring", start_ms=1, created_at_ms=1))
    store.clips.insert(ClipRow(id="a", event_id="a", created_at_ms=1, status="pending"))
    add_event(store, "b")                                                      # ready, has media, no trace
    add_event(store, "c")
    store.traces.put("c", trace("theft_a", "c"), mode="fast")
    assert [c.id for c in store.clips.awaiting_download()] == ["a"]
    assert [c.id for c in store.clips.awaiting_perception()] == ["b"]
    store.clips.set_media("a", path="/p.mp4", snapshot_path="/s.jpg", sha256="ff", duration_ms=9, status="ready")
    got = store.clips.get("a")
    assert (got.status, got.path, got.snapshot_path, got.duration_ms, got.error) == ("ready", "/p.mp4", "/s.jpg", 9, None)


# ------------------------------------------------------------------------------------------ labels / concepts
def test_labels_one_per_concept_and_clip_put_replaces(store):
    add_event(store, "e1")
    store.concepts.create("cn", "n", "hint", 0.2)
    store.concepts.create("cn2", "n2", None, 0.1)
    store.labels.put("cn", "e1", "pos", "example", 3.0)
    store.labels.put("cn", "e1", "neg", "active", 1.0)
    store.labels.put("cn2", "e1", "pos", "random", 1.0)                         # another concept: independent
    assert [(l.value, l.provenance, l.weight) for l in store.labels.list("cn")] == [("neg", "active", 1.0)]
    assert store.concepts.counts("cn")["active_neg"] == 1 and store.concepts.counts("cn2")["random_pos"] == 1
    assert [l.provenance for l in store.labels.list("cn", provenance=("example", "active"))] == ["active"]
    assert store.labels.list("cn", provenance=("random",)) == []
    assert store.labels.delete("cn", "e1") and not store.labels.delete("cn", "e1")


def test_random_samples_registry(store):
    add_event(store, "e1")
    add_event(store, "e2")
    store.concepts.create("cn", "n", None, 0.1)
    store.random_samples.add("cn", ["e1"])
    store.random_samples.add("cn", ["e1"])                                       # idempotent
    assert store.random_samples.drawn("cn", ["e1", "e2"]) == {"e1"}
    assert store.random_samples.all_for("cn") == {"e1"} and store.random_samples.all_for("other") == set()


def test_unlabelled_ok_excludes_labelled_and_failed(store):
    for i, name in enumerate(["theft_a", "delivery_a", "perception_failed", "birds_feeder"]):
        add_event(store, f"c{i}", 1000 + i)
        store.traces.put(f"c{i}", trace(name, f"c{i}"), mode="fast")
    store.concepts.create("cn", "n", None, 0.1)
    store.labels.put("cn", "c0", "pos", "example", 3.0)
    assert [c for c, _ in store.traces.unlabelled_ok("cn")] == ["c3", "c1"]
    assert store.traces.unlabelled_ok_ids("cn") == ["c3", "c1"]
    assert set(store.traces.primary_ok_for(["c0", "c2", "c3"])) == {"c0", "c3"}
    assert [c for c, _ in store.traces.list_primary_ok()] == ["c3", "c1", "c0"]


# ------------------------------------------------------------------------------------------ runs / rules / firings
def test_runs_and_run_events(store):
    store.concepts.create("cn", "n", None, 0.1)
    run = store.runs.create("r1", "cn")
    assert store.runs.running_for_concept("cn").id == "r1" and run.status == "running"
    for i in (1, 2, 3):
        store.runs.append_event("r1", i, "sketch_proposed", {"seq": i, "type": "sketch_proposed", "at_ms": i}, i)
    assert [e["seq"] for e in store.runs.events("r1", after_seq=1)] == [2, 3] and store.runs.last_seq("r1") == 3
    with pytest.raises(sqlite3.IntegrityError):
        store.runs.append_event("r1", 2, "x", {}, 1)                             # (run_id, seq) is the key
    store.runs.finish("r1", "failed", "boom")
    r = store.runs.get("r1")
    assert (r.status, r.error) == ("failed", "boom") and r.finished_at_ms and store.runs.running_for_concept("cn") is None
    store.runs.create("r2", "cn")
    assert store.runs.fail_stale() == 1 and store.runs.get("r2").status == "failed"


def _rule(store, rid, mdl, margin, dsl="d"):
    return store.rules.insert(rule_id=rid, concept_id="cn", run_id=None, sketch_text="s", dsl_text=dsl + rid,
                              ast_json="{}", english="e", holes={"b": 1.5}, margin=margin, mdl=mdl,
                              violated_clip_ids=["c1"], actions=("ui", "slack"))


def test_rules_ranked_by_mdl_then_margin_with_actions(store):
    store.concepts.create("cn", "n", None, 0.1)
    _rule(store, "r1", 20, 0.2)
    _rule(store, "r2", 20, 0.4)
    _rule(store, "r3", 10, 0.1)
    assert [r.id for r in store.rules.list_for_concept("cn")] == ["r3", "r2", "r1"]
    r = store.rules.get("r1")
    assert r.holes == {"b": 1.5} and r.violated_clip_ids == ["c1"] and r.actions == ("slack", "ui") and r.tau is None
    store.rules.update("r1", status="retired")
    assert "r1" not in [x.id for x in store.rules.list_for_concept("cn")]
    assert "r1" in [x.id for x in store.rules.list_for_concept("cn", include_retired=True)]
    store.rules.set_calibration("r2", tau=0.3, delta=0.12, calibration={"alpha": 0.1})
    got = store.rules.get("r2")
    assert (got.tau, got.delta, got.calibration) == (0.3, 0.12, {"alpha": 0.1})
    with pytest.raises(ValueError):
        store.rules.update("r2", margin=9)                                       # only lifecycle columns are updatable
    assert store.rules.supersede_candidates("cn", ["r2"]) == 1                    # r3 retired, r2 kept, r1 already retired
    assert store.rules.get("r3").status == "retired" and store.rules.get("r2").status == "candidate"


def test_firing_upsert_is_unique_per_rule_and_event(store):
    add_event(store, "e1")
    store.concepts.create("cn", "n", None, 0.1)
    _rule(store, "r1", 1, 1)
    base = {"id": "f1", "rule_id": "r1", "event_id": "e1", "stage": 1, "score": 0.2, "tau": 0.0, "fired": False,
            "witness": None, "actions": [], "created_at_ms": 5}
    assert store.firings.upsert(base) == "f1"
    again = {**base, "id": "f-other", "stage": 2, "score": 0.4, "fired": True, "witness": {"score": 0.4},
             "actions": [{"action": "ui", "status": "ok", "detail": None}], "created_at_ms": 9}
    assert store.firings.upsert(again) == "f1"                                    # same (rule, event): the row is updated
    (f,) = store.firings.list()
    assert (f["id"], f["stage"], f["fired"], f["witness"]) == ("f1", 2, True, {"score": 0.4}) and f["actions"] == []
    assert store.firings.exists("r1", "e1") and not store.firings.exists("r1", "e2")
    store.firings.add_action("f1", "slack", "failed", "HTTP 500")
    assert store.firings.get("f1")["actions"] == [{"action": "slack", "status": "failed", "detail": "HTTP 500"}]
    with pytest.raises(sqlite3.IntegrityError):
        store.firings.upsert({**base, "id": "fx", "rule_id": "nope", "event_id": "e1"})


# ------------------------------------------------------------------------------------------ A's protocols
def test_token_store_roundtrip_and_auth_manager(store):
    assert store.auth.load() is None
    store.auth.save(StoredAuth(mode="playground", access_token="tok", issued_at_ms=1, expires_at_ms=2, updated_at_ms=3))
    store.auth.save(StoredAuth(mode="playground", access_token="tok2", issued_at_ms=5, expires_at_ms=6, updated_at_ms=7))
    got = store.auth.load()
    assert (got.access_token, got.issued_at_ms, got.expires_at_ms) == ("tok2", 5, 6)
    assert store.query_one("SELECT COUNT(*) FROM ring_auth")[0] == 1                # single row
    assert "tok2" not in repr(got)                                                  # A's repr hides the token
    store.auth.clear()
    assert store.auth.load() is None


def test_auth_manager_persists_through_the_store(store):
    from .helpers_store import fresh_jwt
    mgr = AuthManager(store.auth)
    mgr.set_playground_token(fresh_jwt())
    again = AuthManager(store.auth)                                                 # "restart"
    again._bootstrap(None)
    assert again.status().connected is True and again.status().mode == "playground"


def test_webhook_deduper_claim_is_insert_or_ignore(store):
    assert store.webhooks.claim("req-1", "motion_detected") is True
    assert store.webhooks.claim("req-1", "motion_detected") is False
    assert store.webhooks.claim("req-2") is True
    store.webhooks.release("req-1")
    assert store.webhooks.claim("req-1") is True


def test_process_delivery_uses_the_store_as_deduper(store):
    body = b'{"meta":{"request_id":"r-9"},"data":{"type":"button_press"}}'
    hdr = {"X-Signature": sign_body(body, "k")}
    assert process_delivery(body, hdr, "k", store.webhooks).status == "accepted"
    assert process_delivery(body, hdr, "k", store.webhooks).status == "duplicate"
    assert process_delivery(body, {"X-Signature": "sha256=00"}, "k", store.webhooks).status == "rejected"
    assert process_delivery(body, hdr, "k", InMemoryDeduper()).status == "accepted"      # same protocol, other backend


def test_cost_ledger_totals(store):
    store.cost.add("perception_fast", model_alias="a", clip_id="c", tokens_in=100, tokens_out=10, latency_ms=5)
    store.cost.add("perception_fast", tokens_in=50, tokens_out=5)
    store.cost.add("sketch", run_id="r", tokens_in=7)
    t = store.cost.totals()
    assert t["perception_fast"] == {"calls": 2, "tokens_in": 150, "tokens_out": 15}
    assert t["sketch"] == {"calls": 1, "tokens_in": 7, "tokens_out": 0}
    with pytest.raises(sqlite3.IntegrityError):
        store.cost.add("lunch")


# ------------------------------------------------------------------------------------------ threads
def test_concurrent_writers_and_readers(store):
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for i in range(40):
                add_event(store, f"t{n}-{i}", n * 1000 + i)
                store.cost.add("perception_fast", tokens_in=1)
        except BaseException as e:      # noqa: BLE001
            errors.append(e)

    def reader() -> None:
        try:
            for _ in range(60):
                store.events.list_view(limit=50)
                store.cost.totals()
        except BaseException as e:      # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)] + [threading.Thread(target=reader) for _ in range(3)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert not errors and store.events.count() == 160 and store.cost.totals()["perception_fast"]["tokens_in"] == 160
