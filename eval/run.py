"""Few-shot Exemplar trials on MEVA (PLAN.md section 3).

    uv run --project engine python -m eval.run --concept vehicle_stop --k 3 --q 3 --seeds 5 [--alpha 0.1]
    uv run --project engine python -m eval.run --concept all --k 1 3 --q 0 3 5 --seeds 5 --proposer offline

Reads cached traces only (run `python -m eval.precompute` first), so it makes no model call unless `--proposer llm` (synthesis
sketches from the strong model) or `--escalate` (strong re-perception of events inside the escalation band) is given; both run
under the budget guard.  Rows are merged into `$EXEMPLAR_DATA_DIR/eval/results.json` (EvalResults, validated); trials whose rows
already exist are skipped, so an interrupted run resumes with the same command (`--force` recomputes).

Protocol per (concept, k, seed): see `eval/harness/experiment.py`.  Train windows feed synthesis and active learning, calib windows
(provenance `random`) feed the conformal threshold, test windows are only scored.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from eval.harness import results as resmod
from eval.harness.budget import DEFAULT_MAX_USD, HARD_CAP_USD, BudgetExceeded, BudgetGuard
from eval.harness.dataset import Window, concept_ids, eval_dir, load_windows
from eval.harness.experiment import Services, TrialConfig, run_trial
from eval.harness.traces import load_cached, perceive_window

STRONG_FRAMES = 32
EST_STRONG_USD = 0.06


def make_services(proposer: str = "offline") -> Services:
    """Wire the real streams C, D and E (imported lazily: D and E may not be merged yet)."""
    try:
        from exemplar.active import build_committee, select_query
        from exemplar.calibrate import calibrate
        from exemplar.contracts.labels import WEIGHT_BULK, Label
        from exemplar.dsl import robustness
        from exemplar.synth import Example
        try:
            from exemplar.agent import run_cegis
        except ImportError:
            from exemplar.agent.cegis import run_cegis
    except ImportError as e:
        raise SystemExit(f"streams D (synth, agent) and E (active, calibrate) must be merged before the Exemplar rows can be "
                         f"computed: {e}\nThe zero-shot baseline and precompute do not need them.")
    if proposer == "offline":
        try:
            from exemplar.agent.templates import TemplateProposer
        except ImportError:
            raise SystemExit("--proposer offline needs D's template proposer (exemplar.agent.templates.TemplateProposer)")
        new = TemplateProposer
    elif proposer == "llm":
        try:
            from exemplar.agent.llm import StrandsProposer
            new = StrandsProposer
        except ImportError:
            new = lambda: None                      # noqa: E731  (model=None: run_cegis builds its own LLM proposer)
    else:
        raise ValueError(f"unknown proposer {proposer!r}")
    return Services(run_cegis=run_cegis, build_committee=build_committee, select_query=select_query, calibrate=calibrate,
                    make_example=Example, make_label=lambda **kw: Label(weight=WEIGHT_BULK, **kw), robustness=robustness,
                    new_proposer=new, proposer_name=proposer)


def load_traces(windows: Sequence[Window]) -> tuple[dict[str, Any], list[str]]:
    """(window id -> cached fast trace, ids without a cached trace)."""
    traces, missing = {}, []
    for w in windows:
        t = load_cached(w)
        if t is None:
            missing.append(w.id)
        else:
            traces[w.id] = t
    return traces, missing


def make_strong_fn(guard: BudgetGuard, client: Any):
    """window -> (strong trace, usd paid now, latency ms).  Strong traces are cached by B, so seeds and (k, q) cells share them."""
    from eval.harness.budget import usd

    def strong(w: Window):
        t0 = time.perf_counter()
        token = guard.reserve(EST_STRONG_USD)
        if token is None:
            raise BudgetExceeded("escalation would exceed the budget cap; rerun with a higher --max-usd (<= 20) or without --escalate")
        try:
            res = perceive_window(w, client=client, mode="strong", n_frames=STRONG_FRAMES)
        except BaseException:
            guard.release(token)
            raise
        pm = res.trace.perception
        paid = 0.0
        if res.cached:
            guard.release(token)
        else:
            paid = usd("strong", pm.tokens_in, pm.tokens_out) if pm else 0.0
            guard.commit(token, {"phase": "escalate", "id": w.id, "mode": "strong", "model_alias": pm.model_alias if pm else "strong",
                                 "tokens_in": pm.tokens_in if pm else 0, "tokens_out": pm.tokens_out if pm else 0, "usd": paid})
        return res.trace, paid, int((time.perf_counter() - t0) * 1000)

    return strong


def existing_keys(path: Optional[Path] = None) -> set[tuple]:
    return {resmod.row_key(r) for r in resmod.load_results(path).get("rows", []) if r.get("method") == "exemplar"}


def main(argv: Optional[Sequence[str]] = None, *, services: Optional[Services] = None, results_path: Optional[Path] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__.split("\n\n")[0])
    ap.add_argument("--concept", nargs="+", default=["all"], help="concept ids or 'all'")
    ap.add_argument("--k", nargs="+", type=int, default=[3], help="positive examples (1, 3)")
    ap.add_argument("--q", nargs="+", type=int, default=[3], help="active questions; several values share one active run per seed")
    ap.add_argument("--seeds", type=int, default=5, help="seeds 0..N-1")
    ap.add_argument("--seed-list", nargs="+", type=int, default=None, help="explicit seeds (overrides --seeds)")
    ap.add_argument("--alpha", type=float, default=0.1)
    ap.add_argument("--n-neg", type=int, default=2, help="negative examples per trial (0-2)")
    ap.add_argument("--proposer", choices=["offline", "llm"], default="offline",
                    help="offline: D's deterministic template proposer (free); llm: strong-model sketches via Strands (paid)")
    ap.add_argument("--no-hint", action="store_true", help="do not pass the concept's NL hint to synthesis")
    ap.add_argument("--solve-timeout", type=float, default=10.0)
    ap.add_argument("--committee-samples", type=int, default=200)
    ap.add_argument("--escalate", action="store_true", help="execute strong re-perception for events inside the escalation band")
    ap.add_argument("--max-usd", type=float, default=HARD_CAP_USD, help="cumulative spend cap for --escalate / --proposer llm (<= 20)")
    ap.add_argument("--allow-missing", action="store_true", help="skip windows without a cached trace instead of stopping")
    ap.add_argument("--force", action="store_true", help="recompute trials whose rows already exist")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)

    if not 0 <= a.n_neg <= 2:
        ap.error("--n-neg must be 0, 1 or 2")
    concepts = concept_ids() if a.concept == ["all"] else a.concept
    unknown = set(concepts) - set(concept_ids())
    if unknown:
        ap.error(f"unknown concept(s): {sorted(unknown)}")
    seeds = a.seed_list if a.seed_list is not None else list(range(a.seeds))
    qs = sorted(set(a.q))
    from eval.data.config import load_concepts
    hints = {cid: c.hint for cid, c in load_concepts().items()}

    windows = load_windows(concepts=concepts)
    traces, missing = load_traces(windows)
    if missing:
        msg = f"{len(missing)} of {len(windows)} windows have no cached fast trace (run `python -m eval.precompute`)"
        if not a.allow_missing:
            print(msg, file=sys.stderr)
            return 2
        print("warning: " + msg + "; they are skipped", file=sys.stderr)
    failed = sum(t.status != "ok" for t in traces.values())
    print(f"{len(traces)} traces loaded ({failed} perception_failed); concepts {concepts}; k={a.k} q={qs} seeds={seeds} alpha={a.alpha}",
          flush=True)
    if a.dry_run:
        return 0

    svc = services or make_services(a.proposer)
    path = Path(results_path) if results_path else None
    done = set() if a.force else existing_keys(path)
    guard, strong_fn = None, None
    if a.escalate:
        guard = BudgetGuard(a.max_usd, eval_dir() / "costs.jsonl")
        from exemplar.perception.extract import make_client
        strong_fn = make_strong_fn(guard, make_client())
    runs_dir = eval_dir() / "runs"
    runs_dir.mkdir(exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    for cid in concepts:
        by_split = {s: [w for w in windows if w.concept == cid and w.split == s] for s in ("train", "calib", "test")}
        cfg = TrialConfig(concept=cid, hint=None if a.no_hint else hints[cid], alpha=a.alpha, train=by_split["train"],
                          calib=by_split["calib"], test=by_split["test"], traces=traces, n_neg=a.n_neg,
                          committee_samples=a.committee_samples, solve_timeout_s=a.solve_timeout, strong_fn=strong_fn,
                          proposer_label=svc.proposer_name)
        for k in a.k:
            for seed in seeds:
                todo_q = [q for q in qs if (cid, "exemplar", k, q, seed) not in done]
                if not todo_q:
                    continue
                t0 = time.perf_counter()
                try:
                    out = run_trial(cfg, k, seed, todo_q, svc)
                except BudgetExceeded as e:
                    print(f"stopped: {e}", file=sys.stderr)
                    return 3
                rows = [r for r in out.rows if r["q"] in todo_q]
                all_rows += rows
                if not a.no_write:
                    resmod.merge_rows(rows, alpha=a.alpha, path=path)
                    (runs_dir / f"{cid}__k{k}__s{seed}.json").write_text(json.dumps(out.log, indent=1), encoding="utf-8")
                for r in rows:
                    print(f"{cid:<22} k={k} q={r['q']} seed={seed} F1={r['f1']:.3f} P={r['precision']:.3f} R={r['recall']:.3f} "
                          f"FA={r['false_alarm_rate']:.3f} tau={r.get('tau', 0):.2f} esc={r['escalated_fraction']:.2f} "
                          f"${r['usd_per_event']:.4f}/ev" + ("" if r.get("guarantee") else " [no guarantee]")
                          + (" [no rule]" if r.get("no_rule") else ""), flush=True)
                print(f"  trial took {time.perf_counter() - t0:.1f}s", flush=True)
    print(f"{len(all_rows)} rows computed" + ("" if a.no_write else f" and merged into {resmod.results_path() if path is None else path}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
