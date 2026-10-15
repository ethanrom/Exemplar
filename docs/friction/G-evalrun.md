# Friction notes: stream G-run (evaluation harness)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion.

## GR-1 Bedrock Converse calls hang for minutes instead of failing or answering (fast and strong model)
- **Task:** run fast-model perception over 1005 windows (16 frames, about 8k input tokens each) at concurrency 3, and 527 strong-model zero-shot calls at concurrency 2.
- **Steps:** `bedrock-runtime` `converse` through B's `make_client()` (`read_timeout=300`, adaptive retries, 4 attempts).
- **Expected:** a call takes 10-25 s (fast) or 5-15 s (strong, short answer), and a failure comes back as a typed error.
- **Actual:** with the 300 s read timeout, 6 calls out of about 1530 stalled for 311-336 s and then succeeded on the retry (5 fast, 1 strong), no error in
  between. Three of them hit at the same moment, so all three precompute workers were blocked for about 5 minutes. One more call took 95 s after 3 tries.
  After the client timeout was lowered to 90 s, none of the remaining roughly 1400 calls took longer than 60 s.
- **Severity:** medium for the eval wall clock; for the live monitor a 5-minute silent stall on one event would be a visible failure.
- **Workaround:** `--read-timeout 90` (default in `eval.precompute` and `eval.baselines.zero_shot`); precompute also retries backend errors with an
  8 s / 30 s back-off and records `backend_error` for the next resume.
- **Suggestion:** B's `make_client` default of 300 s is too long for calls that normally finish in under 30 s; document the time-to-first-byte behaviour
  of application inference profiles, and whether input tokens are billed for a request abandoned after the read timeout (we could not tell; the ledger counts
  only answered calls).

## GR-2 Same prompt, same frame count: output length (and so cost and latency) varies 18x with scene content
- **Task:** budget the perception pass (PLAN.md section 3 estimated 40-60 USD for the whole eval).
- **Actual:** fast model, 16 frames, 7956 input tokens every time (prompt v2), but 325 to 5831 output tokens (median 1918): the model restates facts in every
  frame when people and vehicles are present. Cost per clip 0.0010 to 0.0048 USD (median 0.0018), perception latency p50 15.6 s, p90 21.3 s, p99 29.5 s.
  All 1005 windows cost 1.80 USD, far below the Phase 0 estimate, because MEVA windows have few entities. The strong-model zero-shot call on the same
  frames costs 0.0133 USD (5.8k in, about 180 out): 7.5x the fast perception, 7.12 USD for 527 windows.
- **Severity:** low (budgeting only). **Workaround:** the budget guard reserves a conservative 0.004 USD per fast call and settles on real usage.
- **Suggestion:** a cap such as "at most N facts per frame" in the perception prompt would flatten latency.

## GR-3 Strong model: `toolChoice: auto` + instruction is reliable, but "confidence" is read two ways
- **Task:** zero-shot baseline with `{"match": bool, "confidence": 0..1}` by tool use (strong model, `thinking: between_tools`, no `temperature`).
- **Actual:** the tool was called with a valid schema on every call (one validation retry in 527 calls, no invalid result). But although the field is
  documented in the schema and the system prompt as "probability that the event occurs", 50 of 527 answers (9.5 %) gave `match=false` together with a high
  confidence (0.85-0.97), i.e. their confidence in the answer. Used literally as a score this would make confident rejections look like near-certain
  detections and unfairly cripple the baseline in the false-alarm calibration.
- **Severity:** medium for evaluation validity. **Workaround:** `ZeroShotResult.score` lets `match` decide the direction and reads inconsistent pairs as
  confidence in the answer (AUC over the 527 windows: 0.77 literal, 0.82 repaired). Documented in `eval/README.md`; the raw answers are cached unchanged.
- **Suggestion:** for calibrated scores ask for a categorical scale ("certainly not ... certainly yes") or log-odds instead of a bare probability next to a boolean.

## GR-4 Throughput: 5 parallel Bedrock calls were fine, latency per call is not predictable
- **Observation:** precompute at concurrency 3 and the baseline at concurrency 2 ran side by side for hours: fast calls 9-25 s (median 15.6 s), strong zero-shot
  calls p50 8.6 s, p90 13.0 s. No `ThrottlingException` surfaced (botocore's adaptive mode may absorb throttling silently, as in B-2). About 8 fast clips per minute.
- **Severity:** low. **Suggestion:** report queue time versus generation time in the Converse metrics.

## GR-5 Merged-stream testing in parallel worktrees needs a hand-made overlay
- **Task:** check that the harness works with D's and E's real modules before they are merged.
- **Steps:** each worktree has its own `engine/.venv` with an editable install of its own `engine/`; `uv run --project engine` therefore never sees the
  other worktrees' packages.
- **Workaround:** copy the packages into a scratch directory outside the repo and put it first on `PYTHONPATH`; this wired `make_services("offline")` to D's
  `TemplateProposer`/`run_cegis` and E's `build_committee`/`select_query`/`calibrate` and ran real-data trials end to end (12-20 s per trial).
- **Suggestion (integrator):** a `scripts/` helper that builds such an overlay from the stream branches would make Phase 2 integration checks one command.

## GR-6 Ontology v1 facts carry almost no signal for "vehicle stops" or "door crossing" on MEVA (finding for the evaluation)
- **Task:** decide whether rules over the cached traces can separate positives from negatives (`python -m eval.trace_probe`, no model call).
- **Actual (987 windows, ROC AUC of one cheap feature, 0.5 = chance):** `vehicle_stop`: every feature 0.49-0.55; `door_crossing`: best is the number of person
  entities (0.71), `enters`/`leaves` facts 0.47; `person_exits_vehicle` and `vehicle_loading`: person count 0.65-0.73, everything else about 0.5. The perception
  summaries describe a static scene ("parked vehicles in the driveway") for a window whose only event is a car coming to a stop; the ontology has no
  motion or "stationary" predicate, and `enters` is almost never asserted. The zero-shot strong model, which sees the pixels, reaches F1 0.42-0.74 at the same
  false-alarm target, so the perception-to-trace step, not synthesis, is the bottleneck on these concepts.
- **Severity:** high for the headline claim. **Workaround:** none inside this stream (contracts and perception are frozen); the harness reports it as measured.
  Candidate levers for the integrator: a MEVA-specific perception prompt that asks for motion between frames (`enters`/`leaves` for every vehicle that appears or
  disappears), an ontology v2 with `moving(entity)` / `stationary(entity)`, or the LLM sketch proposer (the offline template proposer builds rules from clip-level
  `attr` labels such as `dark_suv`, which only memorise the examples).
- **Suggestion:** pick evaluation concepts from the predicates the ontology can express (carrying, picks_up, near, zones) before a time-boxed run.

## GR-7 LLM sketch synthesis is expensive per run with the current agent loop
- **Observation (one smoke run with D's work-in-progress `StrandsProposer`, `person_exits_vehicle`, k=3, q=0):** one synthesis run used 105,814 input and
  2,350 output tokens (0.235 USD at strong-model prices), mostly the conversation re-sent on every tool round. A full `k=3,q=3` configuration is 4 runs per trial, 20
  trials: about 19 USD, more than the stream's whole allowance. The harness therefore defaults to `--proposer offline` and guards `--proposer llm` with a
  0.25 USD reservation per run.
- **Suggestion (D):** prompt caching for the system prompt and example renderings, or one proposal call per round without a tool loop.
