"""Precompute: resumable through the trace cache, budget guard, failure handling, jsonl + ledger records."""
import json

import pytest

from eval import precompute
from eval.harness import traces
from eval.harness.budget import BudgetGuard
from eval.harness.dataset import eval_dir, load_windows
from exemplar.perception import PerceptionBackendError
from exemplar.perception import cache as pcache
from exemplar.perception.pipeline import PerceptionReport, PerceptionResult
from fakes import make_trace, window

ARGS = ["--concept", "vehicle_stop", "--splits", "test", "--no-frollard", "--limit", "4", "--concurrency", "2"]


class FakePerceive:
    """Stands in for perceive_window: stores the trace in B's cache like perceive_detailed does."""

    def __init__(self, data_dir, kind="pos", fail_ids=()):
        self.data_dir, self.kind, self.fail_ids, self.calls = data_dir, kind, set(fail_ids), []

    def __call__(self, w, *, client=None, **kw):
        self.calls.append(w.id)
        if w.id in self.fail_ids:
            return PerceptionResult(make_trace(w.id, "failed", tokens=(7000, 900)), PerceptionReport(attempts=2), cached=False)
        tr = make_trace(w.id, self.kind)
        pcache.store(self.data_dir, traces.key_for(w.id), tr, {})
        return PerceptionResult(tr, PerceptionReport(attempts=1), cached=False)


def records(data_dir):
    return [json.loads(l) for l in (data_dir / "eval" / "precompute.jsonl").read_text(encoding="utf-8").splitlines()]


def test_plan_puts_demo_windows_first_then_test_calib_train():
    ws = [window("t1", "pos", "train"), window("c1", "pos", "calib"), window("x1", "pos", "test"), window("f1", "pos", None)]
    assert [w.id for w in precompute.plan(ws)] == ["f1", "x1", "c1", "t1"]


def test_first_run_calls_perception_and_records_tokens_latency_and_cost(data_dir):
    fake = FakePerceive(data_dir)
    assert precompute.main(ARGS, client=object(), perceive=fake) == 0
    assert len(fake.calls) == 4
    recs = records(data_dir)
    assert len(recs) == 4 and {r["status"] for r in recs} == {"ok"}
    r = recs[0]
    assert r["tokens_in"] == 8000 and r["tokens_out"] == 1500 and r["perception_latency_ms"] == 14000 and r["cached"] is False
    assert r["usd"] == pytest.approx(0.00155) and {"id", "concept", "split", "source", "latency_ms", "ts"} <= set(r)
    ledger = [json.loads(l) for l in (data_dir / "eval" / "costs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(ledger) == 4 and ledger[0]["phase"] == "precompute" and ledger[0]["model_alias"] == "fast"


def test_rerun_is_free_and_does_not_duplicate_records(data_dir):
    precompute.main(ARGS, client=object(), perceive=FakePerceive(data_dir))
    again = FakePerceive(data_dir)
    assert precompute.main(ARGS, client=object(), perceive=again) == 0
    assert again.calls == [] and len(records(data_dir)) == 4
    assert len((data_dir / "eval" / "costs.jsonl").read_text(encoding="utf-8").splitlines()) == 4


def test_resume_only_runs_what_is_missing(data_dir):
    fake = FakePerceive(data_dir)
    precompute.main(ARGS, client=object(), perceive=fake)
    ws = load_windows(concepts=["vehicle_stop"], splits=["test"])
    victim = precompute.plan(ws)[1]
    (pcache.cache_dir(data_dir) / f"{traces.key_for(victim.id)}.json").unlink()
    again = FakePerceive(data_dir)
    precompute.main(ARGS, client=object(), perceive=again)
    assert again.calls == [victim.id]


def test_perception_failed_is_recorded_skipped_on_rerun_and_retried_on_request(data_dir):
    ws = precompute.plan(load_windows(concepts=["vehicle_stop"], splits=["test"]))[:4]
    bad = ws[0].id
    precompute.main(ARGS, client=object(), perceive=FakePerceive(data_dir, fail_ids=[bad]))
    by_id = {r["id"]: r for r in records(data_dir)}
    assert by_id[bad]["status"] == "perception_failed" and by_id[bad]["tokens_in"] == 7000 and by_id[bad]["error"]
    again = FakePerceive(data_dir)
    precompute.main(ARGS, client=object(), perceive=again)
    assert again.calls == []                                                    # not paid for twice
    retry = FakePerceive(data_dir)
    precompute.main(ARGS + ["--retry-failed"], client=object(), perceive=retry)
    assert retry.calls == [bad]


def test_budget_cap_stops_before_any_call(data_dir):
    fake = FakePerceive(data_dir)
    assert precompute.main(ARGS + ["--max-usd", "0"], client=object(), perceive=fake) == 3
    assert fake.calls == [] and not (data_dir / "eval" / "costs.jsonl").exists()


def test_stop_file_halts_dispatch(data_dir):
    (eval_dir() / "STOP").write_text("", encoding="utf-8")
    fake = FakePerceive(data_dir)
    assert precompute.main(ARGS, client=object(), perceive=fake) == 3
    assert fake.calls == []


def test_dry_run_counts_without_calling(data_dir, capsys):
    fake = FakePerceive(data_dir)
    assert precompute.main(ARGS + ["--dry-run"], client=object(), perceive=fake) == 0
    assert fake.calls == [] and "4 to run" in capsys.readouterr().out


def test_run_one_retries_backend_errors_then_succeeds(data_dir):
    w = window("w", "pos", "test", "vehicle_stop")
    guard = BudgetGuard(1.0, data_dir / "c.jsonl")
    attempts = []

    def flaky(win, *, client=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise PerceptionBackendError("ConnectionClosedError: x")
        return PerceptionResult(make_trace(win.id, "pos"), PerceptionReport(attempts=1), cached=False)

    slept = []
    rec = precompute.run_one(w, client=None, guard=guard, perceive=flaky, sleep=slept.append)
    assert rec["status"] == "ok" and rec["tries"] == 3 and slept == list(precompute.BACKOFF_S)
    assert guard.in_flight == 0 and guard.spent == pytest.approx(0.00155)


def test_run_one_reports_a_persistent_backend_error_and_charges_nothing(data_dir):
    w = window("w", "pos", "test", "vehicle_stop")
    guard = BudgetGuard(1.0, data_dir / "c.jsonl")

    def down(win, *, client=None):
        raise PerceptionBackendError("ServiceUnavailableException: x")

    rec = precompute.run_one(w, client=None, guard=guard, perceive=down, sleep=lambda s: None)
    assert rec["status"] == "backend_error" and "ServiceUnavailable" in rec["error"] and guard.spent == 0 and guard.in_flight == 0


def test_summary_statistics():
    recs = {
        "a": {"status": "ok", "cached": False, "tokens_in": 100, "tokens_out": 10, "usd": 0.1, "perception_latency_ms": 10000},
        "b": {"status": "ok", "cached": False, "tokens_in": 100, "tokens_out": 10, "usd": 0.1, "perception_latency_ms": 20000},
        "c": {"status": "perception_failed", "cached": False, "tokens_in": 50, "tokens_out": 5, "usd": 0.05, "perception_latency_ms": 30000},
        "d": {"status": "ok", "cached": True, "tokens_in": 100, "tokens_out": 10, "usd": 0.0, "perception_latency_ms": 5000},
    }
    s = precompute.summarize(recs, list(recs))
    assert s["clips"] == 4 and s["status"] == {"ok": 3, "perception_failed": 1} and s["paid_calls"] == 3
    assert s["tokens_in"] == 350 and s["latency_s_p50"] == 20.0 and s["usd"] == pytest.approx(0.25)
