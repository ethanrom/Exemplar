"""Spend accounting and the budget guard for every model call the evaluation makes.

* One JSONL cost ledger (`$EXEMPLAR_DATA_DIR/eval/costs.jsonl`) shared by precompute, the zero-shot baseline and the
  optional escalation: one line per *paid* call (cached calls are free and are not written).
* `BudgetGuard` refuses to start a call when `spent + in-flight reservations + estimate` would exceed the cap.  The cap is
  cumulative over the whole ledger (not per invocation) and can never exceed `HARD_CAP_USD`.
* Prices are USD per 1M tokens (in, out); only the model alias is ever recorded, never a model id.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

PRICES: dict[str, tuple[float, float]] = {"fast": (0.10, 0.50), "strong": (2.0, 10.0)}
HARD_CAP_USD = 20.0            # the stream's total allowance; --max-usd can only lower it
DEFAULT_MAX_USD = 12.0         # precompute + baseline


def usd(mode: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES[mode]
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


class BudgetExceeded(RuntimeError):
    """The next call would push the cumulative spend over the cap."""


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue          # a torn last line from a killed run
    return rows


def ledger_total(path: Path) -> float:
    return sum(float(r.get("usd", 0.0)) for r in read_ledger(path))


class BudgetGuard:
    """Thread-safe.  `reserve(est)` before a paid call, `commit(token, entry)` with the real usage afterwards
    (or `release(token)` if the call produced nothing billable)."""

    def __init__(self, max_usd: float, ledger_path: Path, *, hard_cap: float = HARD_CAP_USD):
        self.limit = min(float(max_usd), float(hard_cap))
        self.ledger_path = Path(ledger_path)
        self._lock = threading.Lock()
        self._spent = ledger_total(self.ledger_path)
        self._reserved: dict[int, float] = {}
        self._next = 0
        self.session_spent = 0.0

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    @property
    def in_flight(self) -> float:
        with self._lock:
            return sum(self._reserved.values())

    def remaining(self) -> float:
        with self._lock:
            return self.limit - self._spent - sum(self._reserved.values())

    def reserve(self, est_usd: float) -> Optional[int]:
        """A reservation token, or None if the estimate does not fit under the cap (the caller must stop)."""
        with self._lock:
            if self._spent + sum(self._reserved.values()) + est_usd > self.limit + 1e-12:
                return None
            self._next += 1
            self._reserved[self._next] = est_usd
            return self._next

    def release(self, token: int) -> None:
        with self._lock:
            self._reserved.pop(token, None)

    def commit(self, token: Optional[int], entry: dict[str, Any]) -> float:
        """Release the reservation, add the actual `entry["usd"]` to the total and append it to the ledger."""
        cost = float(entry.get("usd", 0.0))
        with self._lock:
            if token is not None:
                self._reserved.pop(token, None)
            self._spent += cost
            self.session_spent += cost
            row = {"ts": round(time.time(), 3), **entry}
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        return cost
