# eval: the MEVA evaluation run (stream G-run)

Quantitative evidence for Exemplar: **rules learned from k examples and q active questions** versus **asking a strong vision LLM per
event (zero-shot)**, on the same frames, with a **calibrated false-alarm guarantee**. The dataset (windows, splits, ROIs) is
`eval/data/` (see `eval/data/README.md`); this directory holds the runners, baselines, metrics and charts.

| file | what |
|---|---|
| `precompute.py` | fast perception (B) of every manifest clip and the 18 demo windows; cached, resumable, budget-guarded |
| `baselines/zero_shot.py` | zero-shot baseline: strong model, same 16 frames, concept description, `{"match", "confidence"}` by tool use |
| `run.py` | `python -m eval.run`: the Exemplar trials (D synthesis, E active learning and calibration, C robustness) |
| `harness/experiment.py` | the trial protocol with leakage assertions (all D and E calls go through an injected `Services`) |
| `harness/metrics.py` | conformal threshold, precision / recall / F1, false-alarm rate, Clopper-Pearson, escalation band, cost |
| `harness/budget.py` | price table, cost ledger, `BudgetGuard` (hard cap 20 USD) |
| `harness/results.py` | `results.json` merge by (concept, method, k, q, seed) and validation against `EvalResults` in `contracts/api.yaml` |
| `plots/` | `python -m eval.plots`: three SVG charts and a markdown table from `results.json` |
| `tests/run/` | offline tests with fake D / E (`uv run --project engine pytest eval/tests`) |

All large outputs go under `$EXEMPLAR_DATA_DIR/eval/` (gitignored): `precompute.jsonl`, `costs.jsonl`, `zero_shot/<window>.json`,
`zero_shot.jsonl`, `runs/<concept>__k<k>__s<seed>.json` (examples, questions asked and their answers per trial), `results.json`,
`plots/`. The perception cache is B's (`$EXEMPLAR_DATA_DIR/cache/traces/`).

## Protocol

Per concept (4: `vehicle_stop`, `person_exits_vehicle`, `door_crossing`, `vehicle_loading`), `k in {1, 3}`, `q in {0, 3, 5}`, 5 seeds,
`alpha = 0.1`:

1. **Examples.** `k` positives and 2 negatives are drawn (seeded, uniformly) from the concept's **train** windows and become `example`
   labels (weight 3). The positives and the negatives are shuffled independently, so the k=1 example is the first of the k=3
   examples and the negatives do not depend on k.
2. **Synthesis.** D's `run_cegis` proposes and solves sketches; candidates are ranked by MDL, then margin. `--proposer offline`
   uses D's deterministic template proposer (free); `--proposer llm` uses the strong model through Strands (paid, budget-guarded).
   The concept's NL hint (`concepts.yaml`) is passed as `nl_hint` (`--no-hint` to drop it).
3. **Active learning.** For each of `q` rounds, E's `build_committee` over the current candidates and `select_query` over the remaining
   unlabelled **train** windows of the concept; the oracle answers with the ground-truth window label (provenance `active`, weight 3);
   synthesis runs again. Checkpoints for several q values share one active run per (concept, k, seed), so q=3 is the first three
   rounds of q=5.
4. **Calibration.** The top candidate is calibrated with E's `calibrate` on the concept's **calib** windows, all labelled provenance
   `random` (positives and negatives): `tau_alpha` is the k-th smallest calibration-negative score, `k = ceil((n+1)(1-alpha))`;
   fire iff `score > tau`.
5. **Test.** The concept's **test** windows are scored with C's `robustness`; every metric below is measured there.
6. **Leakage is asserted, not assumed.** `assert_no_leak` runs before every synthesis call and every query answer: the ids handed to
   D / E must be train windows of the concept, and the train / calib / test id sets must be pairwise disjoint (`LeakError`
   otherwise). Windows are split by **video** in `eval/data` (no video is in two splits). `perception_failed` train traces are never
   used as examples or questions; on calib / test they score -0.5 (a miss for a positive, a correct reject for a negative), so
   failures hurt Exemplar rather than being dropped.

**Zero-shot baseline** (`method = zero_shot_vlm`, k = q = seed = 0, deterministic): the strong model sees the same 16 frames
(`sample_window(path, 16)`, 640 px, same timestamps and captions as perception) and the concept description, and answers by tool
use. `confidence` is its probability that the event occurs. Two operating points are reported: the **calibrated** one (tau from the
calib negatives' confidences at the same alpha, so both methods get the same false-alarm target; these are the main rows) and the
**native** one (`match == true`, fields `native_*`), which has no guarantee. It is run on the calib and test windows only.

## Metrics (all on the test split, rule or baseline fired iff score > tau)

| field | definition |
|---|---|
| `precision`, `recall`, `f1` | from the confusion matrix at tau; 0 when nothing fires |
| `false_alarm_rate` | false alarms / test negatives; the validity check is that it stays near or below `alpha` (the conformal bound is `P(false alarm) <= alpha` over the draw of the calibration set, so single runs scatter around it; the chart shows a 95 % Clopper-Pearson interval) |
| `tokens_per_event` | mean fast-perception tokens (in + out) per test event, plus synthesis LLM tokens amortised over the test events |
| `usd_per_event` | `usd_perception` (fast model) + `usd_synthesis_amortised` (strong-model synthesis tokens / test events; 0 for the offline proposer) + `usd_escalation_expected` (escalated fraction x mean strong-perception cost); zero-shot: one strong call per event |
| `p50_latency_ms` | median per-event latency: perception wall clock as recorded in the cached trace (+ the strong call for band events when escalation was executed); scoring is sub-millisecond. These were measured with 3-5 concurrent Bedrock calls, so absolute values are pessimistic |
| `escalated_fraction` | share of test events with `abs(score - tau) <= delta` (delta from E's `calibrate`, default 0.1); the monitor would re-perceive those with the strong model. Zero-shot has no funnel (0) |
| `tau`, `delta`, `guarantee`, `n_calib_neg`, `n_test_pos`, `n_test_neg`, `false_alarm_ci95_*`, `rule_dsl`, `rule_english`, `margin`, `q_effective`, `no_rule`, `n_missing_traces` | extra fields (the schema allows them) |

`--escalate` also executes the strong re-perception for band events (32 frames, strong model, cached by B so seeds share it) and adds
`*_escalated` metrics and `escalation_usd_paid`; it is budget-guarded. The conformal bound is about the fast decision; re-scored
events are decided by a different scorer (E documents this), so the escalated numbers are empirical.

## Reproduce

```bash
export PYTHONUTF8=1
export EXEMPLAR_DATA_DIR="D:/kaskara/amazon dev hackathon/data"      # clips from eval/data (download + cut + frollard) live here
export EXEMPLAR_DOTENV="D:/kaskara/amazon dev hackathon/.env"        # Bedrock settings; never commit it

# 1. perception (paid, ~2 USD, 1-2.5 h at concurrency 3; resumable: run the same command again after any stop)
uv run --project engine python -m eval.precompute --concurrency 3 --max-usd 12
# 2. zero-shot baseline (paid, ~7 USD, ~1 h; resumable)
uv run --project engine python -m eval.baselines.zero_shot --concurrency 2 --max-usd 12
# 3. Exemplar rows (free with the offline proposer: it only reads cached traces; needs streams D and E merged)
uv run --project engine python -m eval.run --concept all --k 1 3 --q 0 3 5 --seeds 5 --proposer offline
#    one concept / one config:  python -m eval.run --concept vehicle_stop --k 3 --q 3 --seeds 5
# 4. charts and table -> $EXEMPLAR_DATA_DIR/eval/plots/   (f1_by_concept.svg, validity.svg, cost_latency.svg, results_table.md)
uv run --project engine python -m eval.plots
uv run --project engine pytest eval/tests
```

* **Free re-runs.** Steps 3 and 4 make no model call with the offline proposer; the traces come from B's cache by the same key
  `perceive_detailed` uses (`eval/harness/traces.py::key_for`). A window without a cached trace stops the run
  (`--allow-missing` skips it and counts it in `n_missing_traces`). Trials whose rows are already in `results.json` are skipped
  (`--force` recomputes), so an interrupted run resumes with the same command.
* **Stop gracefully.** `touch $EXEMPLAR_DATA_DIR/eval/STOP` stops precompute and the baseline from dispatching new calls.
* **Budget.** `BudgetGuard` keeps one cumulative ledger (`costs.jsonl`) and refuses a call that would push it over `--max-usd`
  (default 12 for precompute + baseline; never above 20). Reservations cover calls in flight. Only the model alias is recorded.
  Prices: fast 0.10 / 0.50 and strong 2 / 10 USD per million input / output tokens.
* **Concurrency.** Bedrock latency is 10-64 s per fast call and gets worse with many parallel calls; the default is 3. Some calls
  hang for minutes, so the client read timeout is 90 s (`--read-timeout`), after which botocore retries.
* **Subset.** If the full zero-shot baseline would not fit the budget, `--subsample auto` runs a seeded stratified subset (by concept
  x split x label, nested across fractions, at least 10 calib negatives per concept) and writes `subset_fraction` into the rows.

## Fairness and limits (read before quoting a number)

* Both methods see the same frames; Exemplar additionally gets k + q labelled windows and a concept hint, the baseline gets the
  concept description. Both thresholds are calibrated on the same calib windows at the same alpha.
* Test sets are small (13-33 positives, 45-78 negatives per concept). Seeds vary the chosen examples only; the test windows are the
  same in every seed, so the seed spread understates test-sampling noise (the interval on the false-alarm rate accounts for it).
* About half of the negatives are hard negatives (a confuser activity is present), by construction.
* MEVA people are small; G336 / G339 / G436 are far-field views where perception is weak (`eval/data/README.md`).
* Confidence scores of an LLM are coarse (many ties), which makes its conformal threshold conservative.
* The active-learning pool is the concept's own train windows (about 25 % positives), not a mixed event history.

## Attribution

Windows are derived from MEVA (CC BY 4.0, Kitware / IARPA; https://registry.opendata.aws/mevadata) and, for the demo windows, from
"Thief stealing our package" by frollard (CC BY 4.0, https://www.youtube.com/watch?v=TfTFu8lGrwk). Clips are modified (cut, cropped,
scaled, re-encoded). Full notice and the selection method: `eval/data/README.md`.
