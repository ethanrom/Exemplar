# Friction notes — stream E (active / calibrate / monitor)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion. Stream E makes no live Ring call (the chime action is tested against a mocked `RingClient`) and spent about $0.002 on one opt-in Bedrock smoke test, so these are tooling, spec and interface findings.

## E-1 Chime playback cannot be exercised against the Playground
- **Task:** record the Playground's answer to `chime_play` inside the monitor's `chime` action.
- **Steps:** `ActionRunner(chime=chime_via_ring_client(client), chime_enabled=True)`; fire a rule with `actions=("chime",)`.
- **Expected:** a documented error that says why playback is impossible.
- **Actual:** nothing new beyond P0-4 (400 `Validation Error` "The request contains invalid input.", no hint whether device, scope or `audio_ref` is wrong). The monitor records `failed` with `InvalidPayloadError: ... status=400` and carries on; tested with a respx-mocked 400 and with the real `RingClient` (flag on and off).
- **Severity:** low (demo only needs the failure to be recorded, not hidden).
- **Workaround:** `chime_audio_ref` defaults to the placeholder `"default"` because the real slot id format is undocumented for the Playground.
- **Suggestion:** document what `audio_ref` is and give the virtual device a chime slot.

## E-2 `scipy.stats` import takes 40-77 s on the dev box while three streams run tests
- **Task:** Clopper-Pearson interval via `scipy.stats.beta.ppf`.
- **Steps:** `python -c "import scipy.stats"` in the uv venv with the other Phase 2 streams running pytest (Windows 10, Defender on).
- **Expected:** a couple of seconds.
- **Actual:** 40 s and 77 s on two cold runs; `import exemplar.dsl` alone took 20 s, `pytest --collect-only` over 76 tests 73 s. It was fast (2 s for 100 tests) once the box was idle.
- **Severity:** medium for the edit-test loop, none for correctness.
- **Workaround:** use `scipy.special.betaincinv` (same quantile, a much lighter import) in `calibrate/conformal.py`, `scipy.special.bdtr/bdtrc` in the tests, and call `.venv/Scripts/python.exe -m pytest` directly (skips `uv run`'s environment check).
- **Suggestion:** keep heavy imports (scipy.stats, boto3, strands) out of module import paths of the API process; exclude the repo and `.venv` from Defender real-time scanning.

## E-3 Bash tool heredoc with a quoted delimiter and non-ASCII text failed to parse
- **Task:** write several Python files with `cat > f <<'EOF' ... EOF` in one command.
- **Actual:** `unexpected EOF while looking for matching '''` and nothing was written (the file with `≥` and apostrophes in comments).
- **Severity:** low.
- **Workaround:** use the Write tool for files, or a quoted heredoc feeding `python -` for scripted edits.

## Spec and interface findings (decisions D, H and the integrator should know)
1. **Float `ceil((n+1)(1-alpha))` is wrong in some cases.** `150 * (1 - 0.18)` is `123.00000000000001`, so `math.ceil` gives 124 instead of 123 (alpha 0.18, n 149; 288 such (alpha, n) pairs with alpha in 0.01..0.99, n < 500). `conformal_rank` uses `Fraction(repr(alpha))`, i.e. the decimal the caller wrote.
2. **PLAN §2.5's tau can fall below 0 and then fires on clips the rule does not hold on.** With most random negatives on the -0.5 plateau, `tau_alpha = -0.5` and `score > tau_alpha` accepts every clip that merely has an admissible binding (e.g. a delivery scored -0.45 against the theft rule). `Calibration.tau` is therefore `max(tau_alpha, 0)`; the false-alarm bound still holds (a larger threshold only fires less) and the raw quantile is in `Calibration.tau_alpha`.
3. **The conformal bound covers the stage-1 decision only.** Stage 2 re-scores borderline events with the strong model, a different scorer than the one tau was calibrated on. Expected to be more accurate, but not proved. The false-alarm rate on escalated events should be measured in the MEVA eval, not claimed.
4. **`Candidate.rule` is ambiguous in the interface sheet** (closed rule or sketch?). The committee parses `Candidate.sketch_text` for the sketch and uses `Candidate.holes` as the candidate's own point; it falls back to `Candidate.rule` when the text does not parse.
5. **`select_query(committee, unlabelled)` cannot know which clips are labelled** and has no reference set for the diversity tie-break. Added optional `labelled=` (traces) and `exclude=` (ids) keyword arguments; the two-argument form still works.
6. **`weights ∝ exp(-MDL)` collapses the committee onto the best candidate** once MDLs differ by more than a few bits (each hole costs 8). `build_committee(mdl_temperature=...)` flattens it; the default stays the plan's exp(-MDL).
7. **`hole_box(..., margin=m*)` is the max-margin plateau, a subset of the version space.** The committee therefore understates disagreement. `build_committee(box_margin=0)` samples the whole sign-consistent region; the default follows the spec (each candidate's own margin).
8. **A stage-2 (strong) perception failure keeps the stage-1 decision** instead of dropping the event (the spec says perception failures drop). Rationale: stage 1 is the calibrated decision and an escalation outage should not silently discard borderline true positives. An `error` MonitorEvent and the record message say so.
9. **`FiringRecord`s are produced for dropped events too** (the `firings` table has `UNIQUE(rule_id, event_id)` and a `fired` flag, and stage 0 can only ever be a drop), so `on_firing` is called once per (rule, event), fired or not. H must treat a repeated `(rule_id, event_id)` as an upsert.
