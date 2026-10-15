"""Budget guard and cost ledger: stops before exceeding the cap, cumulative over the ledger, hard cap of $20."""
import json
import threading

import pytest

from eval.harness import budget
from eval.harness.budget import BudgetGuard, ledger_total, read_ledger, usd


def test_price_table():
    assert usd("fast", 1_000_000, 1_000_000) == pytest.approx(0.10 + 0.50)
    assert usd("strong", 1_000_000, 1_000_000) == pytest.approx(2.0 + 10.0)
    assert usd("fast", 7956, 1692) == pytest.approx(0.0016, abs=1e-4)


def test_reserve_refuses_what_does_not_fit(tmp_path):
    g = BudgetGuard(0.01, tmp_path / "costs.jsonl")
    t1 = g.reserve(0.004)
    t2 = g.reserve(0.004)
    assert t1 and t2
    assert g.reserve(0.004) is None                     # 0.008 reserved + 0.004 > 0.01
    g.release(t2)
    assert g.reserve(0.002) is not None


def test_commit_records_actual_cost_and_frees_the_reservation(tmp_path):
    p = tmp_path / "costs.jsonl"
    g = BudgetGuard(0.01, p)
    t = g.reserve(0.009)
    g.commit(t, {"phase": "x", "id": "a", "usd": 0.001})
    assert g.spent == pytest.approx(0.001) and g.in_flight == 0
    assert g.reserve(0.008) is not None                  # the 0.009 reservation was replaced by the real 0.001
    rows = read_ledger(p)
    assert rows[0]["id"] == "a" and rows[0]["usd"] == 0.001 and "ts" in rows[0]


def test_cap_is_cumulative_over_the_ledger_across_invocations(tmp_path):
    p = tmp_path / "costs.jsonl"
    g1 = BudgetGuard(1.0, p)
    g1.commit(None, {"usd": 0.9})
    g2 = BudgetGuard(1.0, p)                             # a later process sees the earlier spend
    assert g2.spent == pytest.approx(0.9) and g2.reserve(0.2) is None and g2.reserve(0.05) is not None


def test_hard_cap_cannot_be_raised_by_the_flag(tmp_path):
    assert BudgetGuard(100.0, tmp_path / "c.jsonl").limit == budget.HARD_CAP_USD == 20.0
    assert BudgetGuard(12.0, tmp_path / "c.jsonl").limit == 12.0


def test_ledger_survives_a_torn_last_line(tmp_path):
    p = tmp_path / "costs.jsonl"
    p.write_text(json.dumps({"usd": 0.5}) + "\n" + '{"usd": 0.2', encoding="utf-8")
    assert ledger_total(p) == 0.5


def test_concurrent_reservations_never_exceed_the_cap(tmp_path):
    g = BudgetGuard(0.05, tmp_path / "c.jsonl")
    granted = []

    def worker():
        for _ in range(20):
            t = g.reserve(0.004)
            if t is not None:
                granted.append(t)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(granted) == 12                            # floor(0.05 / 0.004)
