"""Fast perception of every benchmark clip (and the demo windows), cached, resumable, budget-guarded.

    uv run --project engine python -m eval.precompute [--concept C ...] [--splits train calib test] [--concurrency 3]
                                                      [--max-usd 12] [--retry-failed] [--no-frollard] [--dry-run]

* Perception is `exemplar.perception.perceive_detailed` (16 frames, source `meva` / `upload`, empty context); its content-
  addressed cache (`$EXEMPLAR_DATA_DIR/cache/traces/`) makes every re-run free, so "resume" is just "run it again".
* Every attempt is appended to `$EXEMPLAR_DATA_DIR/eval/precompute.jsonl`
  (id, status, tokens, latency, cached, ...); every paid call is also written to `eval/costs.jsonl` by the budget guard.
* `touch $EXEMPLAR_DATA_DIR/eval/STOP` stops dispatching new clips (in-flight ones finish).
* `perception_failed` traces are never cached, so a re-run would pay for them again: they are skipped unless
  `--retry-failed`.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from eval.harness.budget import DEFAULT_MAX_USD, BudgetGuard, usd
from eval.harness.dataset import Window, eval_dir, load_frollard_windows, load_windows
from eval.harness.traces import load_cached, perceive_window

PHASE = "precompute"
EST_USD_PER_CALL = 0.004          # reservation per fast perception call (observed mean ~0.0015, retries included)
BACKOFF_S = (8.0, 30.0)           # waits before the 2nd / 3rd try after a backend error
SPLIT_ORDER = {"test": 0, "calib": 1, "train": 2, None: -1}


def plan(windows: Iterable[Window]) -> list[Window]:
    """Demo windows first (18 clips, useful early), then test, calib, train; stable inside each group."""
    ws = list(windows)
    order = {w.id: i for i, w in enumerate(ws)}
    return sorted(ws, key=lambda w: (SPLIT_ORDER[w.split], order[w.id]))


def read_records(path: Path) -> dict[str, dict[str, Any]]:
    """Latest record per clip id from the jsonl (a torn last line is ignored)."""
    out: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            out[r["id"]] = r
    return out


class Recorder:
    def __init__(self, path: Path):
        self.path, self._lock = path, threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, rec: dict[str, Any]) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def _record(w: Window, status: str, *, cached: bool, res: Any = None, wall_ms: int = 0, error: Optional[str] = None,
            tries: int = 1) -> dict[str, Any]:
    rec: dict[str, Any] = {"id": w.id, "concept": w.concept, "split": w.split, "source": w.source, "status": status,
                           "cached": cached, "tokens_in": 0, "tokens_out": 0, "latency_ms": wall_ms,
                           "perception_latency_ms": 0, "attempts": 0, "usd": 0.0, "tries": tries,
                           "ts": round(time.time(), 3)}
    if res is not None:
        pm = res.trace.perception
        if pm:
            rec.update(tokens_in=pm.tokens_in, tokens_out=pm.tokens_out, perception_latency_ms=pm.latency_ms)
        rec["attempts"] = res.report.attempts
        if not cached:
            rec["usd"] = round(usd("fast", rec["tokens_in"], rec["tokens_out"]), 6)
        if res.trace.status != "ok":
            rec["error"] = (res.trace.error or "")[:300]
    if error:
        rec["error"] = error[:300]
    return rec


def run_one(w: Window, *, client: Any, guard: BudgetGuard, perceive: Callable[..., Any] = perceive_window,
            sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """One paid perception call with the budget reservation, up to three tries on backend errors."""
    from exemplar.perception import PerceptionBackendError, SamplingError

    token = guard.reserve(EST_USD_PER_CALL)
    if token is None:
        return _record(w, "budget_stop", cached=False, error="budget guard: next call would exceed the cap")
    t0 = time.perf_counter()
    last_err = ""
    try:
        for attempt in range(1, len(BACKOFF_S) + 2):
            try:
                res = perceive(w, client=client)
            except PerceptionBackendError as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt <= len(BACKOFF_S):
                    sleep(BACKOFF_S[attempt - 1])
                    continue
                return _record(w, "backend_error", cached=False, error=last_err, tries=attempt,
                               wall_ms=int((time.perf_counter() - t0) * 1000))
            except (SamplingError, ValueError, OSError) as e:
                return _record(w, "sampling_error", cached=False, error=f"{type(e).__name__}: {e}", tries=attempt,
                               wall_ms=int((time.perf_counter() - t0) * 1000))
            wall = int((time.perf_counter() - t0) * 1000)
            rec = _record(w, "ok" if res.trace.status == "ok" else "perception_failed", cached=res.cached, res=res,
                          wall_ms=wall, tries=attempt)
            if not res.cached:
                guard.commit(token, {"phase": PHASE, "id": w.id, "mode": "fast", "model_alias": "fast",
                                     "tokens_in": rec["tokens_in"], "tokens_out": rec["tokens_out"], "usd": rec["usd"]})
                token = None
            return rec
    finally:
        if token is not None:
            guard.release(token)
    return _record(w, "backend_error", cached=False, error=last_err)       # pragma: no cover (loop always returns)


def _pct(xs: Sequence[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def summarize(records: dict[str, dict[str, Any]], ids: Iterable[str]) -> dict[str, Any]:
    rs = [records[i] for i in ids if i in records]
    billed = [r for r in rs if r["status"] in ("ok", "perception_failed")]
    paid = [r for r in billed if not r["cached"]]
    lat = [r["perception_latency_ms"] / 1000 for r in paid if r["perception_latency_ms"]]
    status: dict[str, int] = {}
    for r in rs:
        status[r["status"]] = status.get(r["status"], 0) + 1
    return {"clips": len(rs), "status": status, "tokens_in": sum(r["tokens_in"] for r in billed),
            "tokens_out": sum(r["tokens_out"] for r in billed), "usd": round(sum(r["usd"] for r in rs), 4),
            "paid_calls": len(paid), "latency_s_p50": round(_pct(lat, 0.5), 1) if lat else None,
            "latency_s_p90": round(_pct(lat, 0.9), 1) if lat else None}


def select_windows(args: argparse.Namespace) -> list[Window]:
    ws: list[Window] = []
    if not args.only_frollard:
        ws += load_windows(concepts=args.concept or None, splits=args.splits or None)
    if not args.no_frollard and not args.concept:
        ws += load_frollard_windows()
    ws = plan(ws)
    return ws[: args.limit] if args.limit else ws


def main(argv: Optional[Sequence[str]] = None, *, client: Any = None, perceive: Callable[..., Any] = perceive_window) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m eval.precompute", description=__doc__.split("\n\n")[0])
    ap.add_argument("--concept", nargs="*", default=None, help="restrict to these concepts (default all + demo windows)")
    ap.add_argument("--splits", nargs="*", default=None, choices=["train", "calib", "test"])
    ap.add_argument("--no-frollard", action="store_true")
    ap.add_argument("--only-frollard", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only the first N windows of the plan")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--read-timeout", type=int, default=90,
                    help="seconds before a silent Bedrock connection is dropped and retried (calls take 10-64 s; some hang for minutes)")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="cap on the cumulative ledger spend (<= 20)")
    ap.add_argument("--retry-failed", action="store_true", help="pay again for clips whose last status was perception_failed")
    ap.add_argument("--dry-run", action="store_true", help="count cached / missing clips and exit")
    a = ap.parse_args(argv)

    edir = eval_dir()
    rec_path, stop_file = edir / "precompute.jsonl", edir / "STOP"
    ws = select_windows(a)
    records = read_records(rec_path)
    recorder = Recorder(rec_path)
    guard = BudgetGuard(a.max_usd, edir / "costs.jsonl")

    todo: list[Window] = []
    n_cached = n_skipped = 0
    for w in ws:
        if load_cached(w) is not None:
            n_cached += 1
            if records.get(w.id, {}).get("status") != "ok":
                rec = _record(w, "ok", cached=True)       # a cache hit that predates this ledger
                recorder.write(rec)
                records[w.id] = rec
            continue
        if not a.retry_failed and records.get(w.id, {}).get("status") == "perception_failed":
            n_skipped += 1
            continue
        todo.append(w)
    print(f"{len(ws)} windows planned: {n_cached} cached, {len(todo)} to run, {n_skipped} skipped (perception_failed; "
          f"use --retry-failed); budget cap ${guard.limit:.2f}, spent so far ${guard.spent:.4f}", flush=True)
    if a.dry_run or not todo:
        print("summary:", json.dumps(summarize(records, [w.id for w in ws])))
        return 0
    if client is None:
        from exemplar.perception.extract import make_client
        client = make_client(read_timeout=a.read_timeout)

    done, t_start, stop_reason = 0, time.perf_counter(), None
    stop = threading.Event()

    def task(w: Window) -> dict[str, Any]:
        if stop.is_set() or stop_file.exists():
            stop.set()
            return {"id": w.id, "status": "skipped_stop"}
        return run_one(w, client=client, guard=guard, perceive=perceive)

    with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as pool:
        futs = {pool.submit(task, w): w for w in todo}
        try:
            for fut in as_completed(futs):
                rec = fut.result()
                w = futs[fut]
                if rec["status"] == "skipped_stop":
                    stop_reason = stop_reason or "STOP file"
                    continue
                if rec["status"] == "budget_stop":
                    stop.set()
                    stop_reason = "budget cap"
                    continue
                recorder.write(rec)
                records[w.id] = rec
                done += 1
                eta = (time.perf_counter() - t_start) / done * (len(todo) - done) / 60
                print(f"[{done:4d}/{len(todo)}] {rec['status']:<17} {w.id[:58]:<58} {rec['latency_ms'] / 1000:5.1f}s "
                      f"in={rec['tokens_in']:5d} out={rec['tokens_out']:5d} ${rec['usd']:.4f} | spent ${guard.spent:.3f} "
                      f"| eta {eta:5.1f} min", flush=True)
        except KeyboardInterrupt:
            stop.set()
            stop_reason = "interrupted"
            for f in futs:
                f.cancel()
    s = summarize(records, [w.id for w in ws])
    print("summary:", json.dumps(s))
    if stop_reason:
        print(f"stopped early ({stop_reason}); run the same command again to resume (cached clips are free).", flush=True)
    return 0 if not stop_reason else 3


if __name__ == "__main__":
    raise SystemExit(main())
