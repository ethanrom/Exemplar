"""Zero-shot baseline: "just ask the strong vision LLM" about every window, on the SAME 16 frames perception uses.

    uv run --project engine python -m eval.baselines.zero_shot [--concept C ...] [--concurrency 3] [--max-usd 12]
                                                              [--subsample auto|F] [--seed 0] [--dry-run]

* Input: the concept's NL description (`eval/data/concepts.yaml`) and the frames from `sample_window(path, 16)`, i.e. the frames
  the fast perception sees (640 px, same timestamps).  Output by tool use: `{"match": bool, "confidence": 0..1}` where
  `confidence` is the model's probability that the described event occurs.  Strong model: `toolChoice: auto` + explicit
  instruction + `thinking: between_tools`, never `temperature`; validated, one retry.
* Run on the calib and test windows of every concept.  The score is `confidence`; the calibrated operating point sets tau on the
  calib negatives at the same alpha as Exemplar (conformal, section 2.5), so both methods get the same false-alarm target.
  The native point (`match == true`) is reported alongside.
* Results are cached per window in `$EXEMPLAR_DATA_DIR/eval/zero_shot/<id>.json` (re-runs are free); every paid call goes to the
  shared cost ledger and the budget guard.  When the full run would not fit the budget, a seeded stratified subset (by
  concept x split x label, nested across fractions) is evaluated and the result rows say so (`subset_fraction`).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from eval.harness import metrics
from eval.harness.budget import DEFAULT_MAX_USD, BudgetGuard, read_ledger, usd
from eval.harness.dataset import N_FRAMES, Window, concept_descriptions, data_dir, eval_dir, load_windows

PROMPT_VERSION = "zs1"
TOOL_NAME = "report_match"
PHASE = "zero_shot"
EST_USD_PER_CALL = 0.03            # reservation per call; observed cost is about 0.012-0.02
DEFAULT_EST_USD = 0.016
BACKOFF_S = (8.0, 30.0)
MAX_TOKENS = 1500
METHOD = "zero_shot_vlm"

SYSTEM = ("You are a careful analyst of security-camera footage. You are given frames sampled uniformly from one short clip, each "
          "preceded by a caption with its time. Decide whether the event described by the user happens anywhere in the clip. "
          "Answer ONLY by calling the report_match tool exactly once. `match` is true iff you believe the event occurs; "
          "`confidence` is your probability (0 to 1) that the event occurs in this clip (0.5 = cannot tell). The camera is a "
          "fixed, cropped view; ignore any watermark or overlay text. Do not identify anyone.")


def tool_config() -> dict[str, Any]:
    schema = {"type": "object", "required": ["match", "confidence"],
              "properties": {"match": {"type": "boolean", "description": "true iff the described event occurs in the clip"},
                             "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                                            "description": "probability (0..1) that the described event occurs"}}}
    return {"tools": [{"toolSpec": {"name": TOOL_NAME, "description": "Report whether the described event occurs.",
                                    "inputSchema": {"json": schema}}}],
            "toolChoice": {"auto": {}}}


MODEL_FIELDS = {"thinking": {"type": "between_tools"}}


def user_content(frames: Sequence[Any], window_ms: int, description: str) -> list[dict[str, Any]]:
    from exemplar.perception.prompt import caption
    content: list[dict[str, Any]] = [{"text": f"Clip window: {window_ms / 1000:.1f} s, {len(frames)} frames (indices 0..{len(frames) - 1})."}]
    for i, fr in enumerate(frames):
        content.append({"text": caption(i, fr.t_ms)})
        content.append({"image": {"format": "jpeg", "source": {"bytes": fr.jpeg}}})
    content.append({"text": f'Event to look for: "{description}"\n\nDoes this event occur in the clip? You MUST respond by calling the '
                            f"{TOOL_NAME} tool exactly once; do not answer in plain text."})
    return content


def validate(payload: Any) -> tuple[Optional[bool], Optional[float], list[str]]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    if not isinstance(payload, dict):
        return None, None, ["the tool input must be a JSON object with `match` and `confidence`"]
    errs, match, conf = [], payload.get("match"), payload.get("confidence")
    if not isinstance(match, bool):
        errs.append("`match` must be a boolean")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0.0 <= conf <= 1.0:
        errs.append("`confidence` must be a number between 0 and 1")
    return (match, float(conf), []) if not errs else (None, None, errs)


class ZeroShotBackendError(RuntimeError):
    """Bedrock call failed (credentials, throttling beyond botocore's retries, dropped connection)."""


@dataclass
class ZeroShotResult:
    id: str
    concept: str
    split: Optional[str]
    label: str
    match: bool
    confidence: float
    status: str                 # "ok" | "invalid" (no valid answer after the retry: scored as no match, confidence 0)
    tokens_in: int
    tokens_out: int
    latency_ms: int
    attempts: int
    usd: float
    model_alias: str
    prompt_version: str = PROMPT_VERSION
    n_frames: int = N_FRAMES

    @property
    def score(self) -> float:
        return self.confidence


def classify(client: Any, *, model_id: str, alias: str, window: Window, frames: Sequence[Any], window_ms: int,
             description: str) -> ZeroShotResult:
    """One window: <= 2 Converse calls (validate, retry once with the error fed back)."""
    from botocore.exceptions import BotoCoreError, ClientError
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content(frames, window_ms, description)}]
    tin = tout = attempts = 0
    t0 = time.perf_counter()
    match: Optional[bool] = None
    conf: Optional[float] = None
    errs: list[str] = []
    for attempt in (1, 2):
        try:
            resp = client.converse(modelId=model_id, system=[{"text": SYSTEM}], messages=messages, toolConfig=tool_config(),
                                   inferenceConfig={"maxTokens": MAX_TOKENS}, additionalModelRequestFields=MODEL_FIELDS)
        except (BotoCoreError, ClientError) as e:
            code = e.response.get("Error", {}).get("Code") if isinstance(e, ClientError) else type(e).__name__
            raise ZeroShotBackendError(f"{code}: {str(e).replace(model_id, '<model>')}"[:400]) from None
        attempts = attempt
        u = resp.get("usage") or {}
        tin, tout = tin + int(u.get("inputTokens", 0)), tout + int(u.get("outputTokens", 0))
        msg = resp.get("output", {}).get("message", {"role": "assistant", "content": []})
        use = next((c["toolUse"] for c in msg.get("content", []) if "toolUse" in c and c["toolUse"].get("name") == TOOL_NAME), None)
        if use is None:
            errs = [f"you did not call the {TOOL_NAME} tool; call it with match and confidence"]
        else:
            match, conf, errs = validate(use.get("input"))
        if not errs:
            break
        fb = "Validation failed:\n" + "\n".join(f"- {e}" for e in errs) + f"\nCall {TOOL_NAME} again."
        uses = [c["toolUse"] for c in msg.get("content", []) if "toolUse" in c]
        user = ({"role": "user", "content": [{"toolResult": {"toolUseId": x["toolUseId"], "status": "error",
                                                              "content": [{"text": fb if i == 0 else "Ignored: call the tool once."}]}}
                                             for i, x in enumerate(uses)]} if uses else {"role": "user", "content": [{"text": fb}]})
        messages += [msg, user]
    lat = int((time.perf_counter() - t0) * 1000)
    ok = not errs and match is not None and conf is not None
    return ZeroShotResult(id=window.id, concept=window.concept, split=window.split, label=window.label,
                          match=bool(match) if ok else False, confidence=float(conf) if ok else 0.0,
                          status="ok" if ok else "invalid", tokens_in=tin, tokens_out=tout, latency_ms=lat, attempts=attempts,
                          usd=round(usd("strong", tin, tout), 6), model_alias=alias)


# ------------------------------------------------------------------ cache
def cache_dir(base: Optional[Path] = None) -> Path:
    d = eval_dir(base) / "zero_shot"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_result(window_id: str, base: Optional[Path] = None) -> Optional[ZeroShotResult]:
    p = cache_dir(base) / f"{window_id}.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("prompt_version") != PROMPT_VERSION:
            return None
        return ZeroShotResult(**d)
    except (OSError, ValueError, TypeError):
        return None


def store_result(res: ZeroShotResult, base: Optional[Path] = None) -> None:
    p = cache_dir(base) / f"{res.id}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(res), indent=1), encoding="utf-8")
    tmp.replace(p)


# ------------------------------------------------------------------ subset selection
def cell_of(w: Window) -> tuple:
    return (w.concept, w.split, w.label)


def stratified_subset(windows: Sequence[Window], frac: float, *, seed: int = 0, min_calib_neg: int = 10) -> list[Window]:
    """Seeded subset stratified by (concept, split, label).  Each cell is shuffled once with its own RNG and a prefix of
    ceil(frac * n) is kept, so subsets for different fractions are nested.  Calib negatives keep at least `min_calib_neg` (the
    conformal guarantee needs >= ceil(1/alpha)-1 of them).  The result is interleaved across cells (one per cell per pass), so
    stopping early at any point leaves a stratified subset."""
    if not 0.0 < frac <= 1.0:
        raise ValueError("frac must be in (0, 1]")
    cells: dict[tuple, list[Window]] = {}
    for w in sorted(windows, key=lambda w: w.id):
        cells.setdefault(cell_of(w), []).append(w)
    ranked: list[tuple[int, tuple, Window]] = []
    for cell in sorted(cells, key=str):
        ws = cells[cell]
        random.Random(f"{seed}|{'|'.join(map(str, cell))}").shuffle(ws)
        keep = math.ceil(frac * len(ws))
        if cell[1] == "calib" and cell[2] == "neg":
            keep = max(keep, min_calib_neg)
        for rank, w in enumerate(ws[: min(len(ws), keep)]):
            ranked.append((rank, cell, w))
    ranked.sort(key=lambda t: (t[0], str(t[1])))
    return [w for _, _, w in ranked]


def fit_fraction(windows: Sequence[Window], *, cached: set[str], est_usd: float, remaining: float, seed: int = 0,
                 safety: float = 1.25) -> float:
    """Largest fraction (steps of 0.05) whose uncached windows fit in `remaining` at `safety * est_usd` each."""
    for pct in range(100, 0, -5):
        sub = stratified_subset(windows, pct / 100, seed=seed)
        n_new = sum(w.id not in cached for w in sub)
        if n_new * est_usd * safety <= remaining:
            return pct / 100
    return 0.05


# ------------------------------------------------------------------ scoring
def build_row(concept: str, results: dict[str, ZeroShotResult], windows: Sequence[Window], *, alpha: float,
              subset_fraction: float = 1.0) -> Optional[dict[str, Any]]:
    """One EvalResults row (k=0, q=0, seed=0) from cached results: calibrated on calib, evaluated on test."""
    cal = [w for w in windows if w.concept == concept and w.split == "calib" and w.id in results]
    tst = [w for w in windows if w.concept == concept and w.split == "test" and w.id in results]
    if not tst:
        return None
    th = metrics.conformal_threshold([results[w.id].score for w in cal if not w.positive], alpha, fallback=0.5)
    t_scores = [results[w.id].score for w in tst]
    t_pos = [w.positive for w in tst]
    c = metrics.confusion(t_scores, t_pos, th.tau)
    m = metrics.prf(c)
    native = metrics.prf(metrics.confusion([1.0 if results[w.id].match else 0.0 for w in tst], t_pos, 0.5))
    lo, hi = metrics.clopper_pearson(c.fp, c.n_neg)
    cal_pos = [results[w.id].score for w in cal if w.positive]
    rec_cal = sum(s > th.tau for s in cal_pos) / len(cal_pos) if cal_pos else None
    lat = [results[w.id].latency_ms for w in tst]
    tok = [results[w.id].tokens_in + results[w.id].tokens_out for w in tst]
    cost = [results[w.id].usd for w in tst]
    return {"concept": concept, "method": METHOD, "k": 0, "q": 0, "seed": 0, **m,
            "tokens_per_event": sum(tok) / len(tok), "usd_per_event": sum(cost) / len(cost),
            "p50_latency_ms": metrics.percentile(lat, 0.5), "escalated_fraction": 0.0,
            "alpha": alpha, "tau": th.tau, "guarantee": th.guarantee, "n_calib_neg": th.n,
            "n_calib_pos": len(cal_pos), "n_test_pos": c.n_pos, "n_test_neg": c.n_neg,
            "false_alarm_ci95_low": lo, "false_alarm_ci95_high": hi, "calib_recall": rec_cal,
            "native_precision": native["precision"], "native_recall": native["recall"], "native_f1": native["f1"],
            "native_false_alarm_rate": native["false_alarm_rate"],
            "invalid_answers": sum(results[w.id].status != "ok" for w in tst + cal),
            "subset_fraction": subset_fraction, "prompt_version": PROMPT_VERSION}


def load_all(windows: Iterable[Window], base: Optional[Path] = None) -> dict[str, ZeroShotResult]:
    out = {}
    for w in windows:
        r = load_result(w.id, base)
        if r is not None:
            out[w.id] = r
    return out


# ------------------------------------------------------------------ run
def run_window(w: Window, *, client: Any, model_id: str, alias: str, descriptions: dict[str, str], guard: BudgetGuard,
               sample: Optional[Callable[..., Any]] = None, sleep: Callable[[float], None] = time.sleep) -> tuple[str, Optional[ZeroShotResult], str]:
    """-> (status, result, error).  status: ok | invalid | budget_stop | backend_error | sampling_error."""
    from exemplar.perception.sampling import DEFAULT_MIN_GAP_S, DEFAULT_WIDTH, MAX_FRAMES_FAST, SamplingError, sample_window
    sample = sample or sample_window
    token = guard.reserve(EST_USD_PER_CALL)
    if token is None:
        return "budget_stop", None, "budget guard: next call would exceed the cap"
    try:
        try:
            win = sample(w.path(), N_FRAMES, min_gap_s=DEFAULT_MIN_GAP_S, width=DEFAULT_WIDTH, roi=None, max_n=MAX_FRAMES_FAST)
        except (SamplingError, ValueError, OSError) as e:
            return "sampling_error", None, f"{type(e).__name__}: {e}"
        err = ""
        for attempt in range(len(BACKOFF_S) + 1):
            try:
                res = classify(client, model_id=model_id, alias=alias, window=w, frames=win.frames, window_ms=win.duration_ms,
                               description=descriptions[w.concept])
            except ZeroShotBackendError as e:
                err = str(e)
                if attempt < len(BACKOFF_S):
                    sleep(BACKOFF_S[attempt])
                    continue
                return "backend_error", None, err
            guard.commit(token, {"phase": PHASE, "id": w.id, "mode": "strong", "model_alias": alias,
                                 "tokens_in": res.tokens_in, "tokens_out": res.tokens_out, "usd": res.usd})
            token = None
            store_result(res)
            return res.status, res, ""
        return "backend_error", None, err
    finally:
        if token is not None:
            guard.release(token)


def main(argv: Optional[Sequence[str]] = None, *, client: Any = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m eval.baselines.zero_shot", description=__doc__.split("\n\n")[0])
    ap.add_argument("--concept", nargs="*", default=None)
    ap.add_argument("--splits", nargs="*", default=["calib", "test"], choices=["calib", "test"])
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--read-timeout", type=int, default=90, help="seconds before a silent Bedrock connection is dropped and retried")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="cap on the cumulative ledger spend (<= 20)")
    ap.add_argument("--subsample", default="auto", help="'auto' (largest fraction that fits the budget), 1 (all) or a fraction in (0,1]")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--alpha", type=float, default=0.1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-write", action="store_true", help="do not merge rows into results.json")
    a = ap.parse_args(argv)

    from eval.harness import results as resmod
    edir = eval_dir()
    windows = load_windows(concepts=a.concept or None, splits=a.splits)
    cached = {w.id for w in windows if load_result(w.id) is not None}
    guard = BudgetGuard(a.max_usd, edir / "costs.jsonl")
    ledger = [r["usd"] for r in read_ledger(edir / "costs.jsonl") if r.get("phase") == PHASE and r.get("usd")]
    est = sum(ledger) / len(ledger) if ledger else DEFAULT_EST_USD
    if a.subsample == "auto":
        frac = fit_fraction(windows, cached=cached, est_usd=est, remaining=guard.remaining(), seed=a.seed)
    else:
        frac = float(a.subsample)
    chosen = stratified_subset(windows, frac, seed=a.seed) if frac < 1.0 else stratified_subset(windows, 1.0, seed=a.seed)
    todo = [w for w in chosen if w.id not in cached]
    print(f"{len(windows)} calib/test windows; subset fraction {frac:.2f} -> {len(chosen)} windows, {len(chosen) - len(todo)} cached, "
          f"{len(todo)} to run; est ${est:.4f}/call; cap ${guard.limit:.2f}, spent ${guard.spent:.4f}", flush=True)
    if frac < 1.0:
        print(f"NOTE: the full baseline does not fit the budget; running a seeded stratified subset (fraction {frac:.2f}).", flush=True)
    if a.dry_run:
        return 0
    if todo:
        from exemplar.settings import get_settings
        st = get_settings()
        if not st.strong_model:
            raise SystemExit("CLAUDE_AWS_MODEL is not configured (.env)")
        alias = st.model_alias or "strong"
        if client is None:
            from exemplar.perception.extract import make_client
            client = make_client(read_timeout=a.read_timeout)
        descriptions = concept_descriptions()
        stop_file, stop = edir / "STOP", threading.Event()
        done, t0, stopped = 0, time.perf_counter(), None
        jl = edir / "zero_shot.jsonl"

        def task(w: Window):
            if stop.is_set() or stop_file.exists():
                stop.set()
                return "skipped_stop", None, ""
            return run_window(w, client=client, model_id=st.strong_model, alias=alias, descriptions=descriptions, guard=guard)

        with ThreadPoolExecutor(max_workers=max(1, a.concurrency)) as pool:
            futs = {pool.submit(task, w): w for w in todo}
            try:
                for fut in as_completed(futs):
                    status, res, err = fut.result()
                    w = futs[fut]
                    if status in ("skipped_stop", "budget_stop"):
                        stop.set()
                        stopped = "budget cap" if status == "budget_stop" else "STOP file"
                        continue
                    done += 1
                    rec = {"id": w.id, "status": status, "error": err, "ts": round(time.time(), 3),
                           **({k: getattr(res, k) for k in ("match", "confidence", "tokens_in", "tokens_out", "latency_ms", "usd")} if res else {})}
                    with jl.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
                    eta = (time.perf_counter() - t0) / done * (len(todo) - done) / 60
                    print(f"[{done:4d}/{len(todo)}] {status:<14} {w.id[:56]:<56} "
                          + (f"match={int(res.match)} conf={res.confidence:.2f} {res.latency_ms / 1000:5.1f}s ${res.usd:.4f}" if res else err[:60])
                          + f" | spent ${guard.spent:.3f} | eta {eta:5.1f} min", flush=True)
            except KeyboardInterrupt:
                stop.set()
                stopped = "interrupted"
                for f in futs:
                    f.cancel()
        if stopped:
            print(f"stopped early ({stopped}); rerun the same command to resume (cached windows are free).", flush=True)

    results = load_all(windows)
    rows = []
    for cid in sorted({w.concept for w in windows}):
        row = build_row(cid, results, windows, alpha=a.alpha, subset_fraction=frac)
        if row:
            rows.append(row)
            print(f"{cid:<22} F1={row['f1']:.3f} P={row['precision']:.3f} R={row['recall']:.3f} FA={row['false_alarm_rate']:.3f} "
                  f"(native F1={row['native_f1']:.3f} FA={row['native_false_alarm_rate']:.3f}) tau={row['tau']:.2f} "
                  f"n_test={row['n_test_pos']}+/{row['n_test_neg']}-", flush=True)
    if rows and not a.no_write:
        resmod.merge_rows(rows, alpha=a.alpha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
