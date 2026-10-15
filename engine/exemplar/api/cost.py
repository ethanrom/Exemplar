"""Cost meter (PLAN.md §2.6): `GET /monitor/cost` -> api.yaml `CostSummary`.

Token counts come from `cost_ledger` (one row per model call, written for every non-cached perception).
Prices are ESTIMATES derived from the Phase 0 spike (PLAN.md §5, row 5): fast ~6.4k in / 1.5k out ~ $0.0014 per
clip, strong ~6.2k in / 1.6k out ~ $0.028 per clip. They are rates per million tokens chosen to reproduce
those two measurements, not Bedrock's price list; override with `PRICE_PER_MTOK` if prices are known.
"""
from __future__ import annotations

from typing import Any

# purpose -> (usd per 1M input tokens, usd per 1M output tokens)
PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "perception_fast": (0.10, 0.50),
    "perception_strong": (2.00, 10.00),
    "sketch": (2.00, 10.00),
    "baseline": (2.00, 10.00),
}


def usd(purpose: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICE_PER_MTOK.get(purpose, PRICE_PER_MTOK["perception_strong"])
    return (tokens_in * pin + tokens_out * pout) / 1e6


def summarize(totals: dict[str, dict[str, int]], stage_counts: dict[int, int], events: int,
              monitor: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a CostSummary. Stage counters come from the monitor when it reports them, else from `firings`."""
    t_in = sum(v["tokens_in"] for v in totals.values())
    t_out = sum(v["tokens_out"] for v in totals.values())
    total_usd = sum(usd(p, v["tokens_in"], v["tokens_out"]) for p, v in totals.items())
    if monitor:
        out = {
            "events": int(monitor.get("events", events)),
            "stage0_dropped": int(monitor.get("stage0_dropped", 0)),
            "stage1_scored": int(monitor.get("stage1_scored", 0)),
            "stage2_escalated": int(monitor.get("stage2_escalated", 0)),
        }
    else:
        out = {"events": events, "stage0_dropped": stage_counts.get(0, 0),
               "stage1_scored": stage_counts.get(1, 0), "stage2_escalated": stage_counts.get(2, 0)}
    out.update(tokens_in=t_in, tokens_out=t_out, usd_estimate=round(total_usd, 6),
               per_event_usd=round(total_usd / out["events"], 6) if out["events"] else 0.0)
    return out
