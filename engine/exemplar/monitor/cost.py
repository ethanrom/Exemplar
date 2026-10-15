"""Cost meter: per-stage counts and token spend of the monitor (api.yaml `CostSummary`).

Counting rules:

* ``events``: events passed to `Monitor.process`.
* ``stage0_dropped`` / ``stage1_scored`` / ``stage2_escalated``: counted per (rule, event) pair, because the
  funnel is per rule. A pair is *stage1_scored* when a trace was obtained and the rule was scored on it, and
  *stage2_escalated* when its score fell in the band around tau (so ``stage2_escalated / stage1_scored`` is the
  escalated fraction).
* Tokens come from ``Trace.perception`` (`PerceptionMeta`) of the traces the monitor paid for: one fast trace
  per event (shared by all rules) and one strong trace per escalated event. Cached traces and traces handed
  in already paid for (``EventInput.trace_cached``) add no tokens, because the cached `PerceptionMeta` is
  historical.
* ``usd_estimate`` = tokens x the price table (USD per million tokens), ``per_event_usd`` = usd / events.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from exemplar.contracts.trace import PerceptionMeta


@dataclass(frozen=True)
class Prices:
    """USD per million tokens. Defaults are the working estimates for the fast / strong Bedrock models."""

    fast_in: float = 0.10
    fast_out: float = 0.50
    strong_in: float = 2.00
    strong_out: float = 10.00


class CostMeter:
    def __init__(self, prices: Optional[Prices] = None) -> None:
        self.prices = prices or Prices()
        self._lock = threading.Lock()
        self._n = {"events": 0, "stage0_dropped": 0, "stage1_scored": 0, "stage2_escalated": 0}
        self._tok = {"fast_in": 0, "fast_out": 0, "strong_in": 0, "strong_out": 0}

    def add(self, **counts: int) -> None:
        with self._lock:
            for k, v in counts.items():
                self._n[k] += v

    def add_tokens(self, tier: str, meta: Optional[PerceptionMeta]) -> None:
        if meta is None:
            return
        with self._lock:
            self._tok[f"{tier}_in"] += int(meta.tokens_in)
            self._tok[f"{tier}_out"] += int(meta.tokens_out)

    def snapshot(self) -> dict:
        """api.yaml `CostSummary`."""
        with self._lock:
            n, t, p = dict(self._n), dict(self._tok), self.prices
        usd = (t["fast_in"] * p.fast_in + t["fast_out"] * p.fast_out
               + t["strong_in"] * p.strong_in + t["strong_out"] * p.strong_out) / 1e6
        return {**n, "tokens_in": t["fast_in"] + t["strong_in"], "tokens_out": t["fast_out"] + t["strong_out"],
                "usd_estimate": usd, "per_event_usd": usd / n["events"] if n["events"] else 0.0}
