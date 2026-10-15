# Friction notes — Stream D (synthesis: Z3, Strands, Bedrock)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion. All entries were reproduced on Windows 10, Python 3.11, `z3-solver` 5.3.0.0, `strands-agents` 1.61, Bedrock Claude (strong, application inference profile).

## D-1 z3py's `And`/`Or` cost about 1 ms per call, so building the formula was slower than solving it
- **Task:** encode 40 clips x 24 frames x a `then` sketch (PLAN.md section 2.3) into a Z3 DAG.
- **Steps:** `z3.And(*xs)` / `z3.Or(*xs)` / `x.get_id()` for every sub-term, profiled with cProfile.
- **Expected:** formula construction to be negligible next to `Optimize.check()` (60-400 ms here).
- **Actual:** 2-8 s of pure Python in `_coerce_expr_list`, `cast`, `sort` and `Z3_get_ast_id` per solve; the solver itself was the cheap part.
- **Severity:** medium (made the 10 s per-sketch budget unreachable for realistic inputs).
- **Workaround:** build n-ary connectives with the C API (`Z3_mk_and` / `Z3_mk_or` over a ctypes `Ast` array), fold Python booleans before touching Z3, de-duplicate arguments by `x.ast.value` instead of `get_id()`, and cache window atoms. 3.5 s became 0.2 s for the same input.
- **Suggestion (Z3):** a documented fast path for bulk term construction (or skip the sort coercion when all arguments are already `BoolRef`s of one context).

## D-2 `Optimize.minimize/maximize` on a Real with an open feasible bound returns `epsilon`, and the model is an arbitrary interior point
- **Task:** Z3 min/max of every hole over the satisfied set (the hole box, PLAN.md section 2.4).
- **Steps:** constraints `0 <= a <= 1, not (a <= 0), a <= 1/2`, `minimize(a)`.
- **Expected:** the infimum 0, or the value 1/2 closest to it.
- **Actual:** `check()` is `sat`, the model is `a = 1/2`, and `handle.lower()` is the symbolic term `epsilon`. Reading the model silently gave a box that missed a quarter of the feasible region (found by the exhaustive-search property test).
- **Severity:** medium (silent wrong answer).
- **Workaround:** read `handle.lower()` / `handle.upper()` and evaluate the term with `epsilon = 0` (the closure of the feasible set); never read the extremum from `model()`.
- **Suggestion:** document that objective values of open sets carry `epsilon` terms and that the model need not attain the optimum.

## D-3 A symbolic margin variable `m` makes the encoding dense; margins are better walked as constants
- **Task:** lexicographic MaxSMT (violated weight, then max margin) as in the plan.
- **Actual:** with `m` a Z3 real, every absent atom contributes the live constraint `m <= 0.45` to every LE term (AND over all frames), so the formula was dense and Python encoding dominated. Because every robustness value is one of a few constants (`|rho|` is in {0.1, 0.3, 0.45, 0.5}), the margin can be a constant level: MaxSMT at the lowest level gives the minimal violated weight, then the next levels are tried in ascending order with the same weight bound.
- **Severity:** low (design note). **Workaround:** `margin_levels()` in `synth/z3enc.py`, derived from `contracts/ontology.py` so a changed confidence table still works.

## D-4 Z3's default context is not thread-safe
- **Task:** `run_cegis` runs in a worker thread (stream H) while stream E calls `hole_box` from another.
- **Actual:** the z3py global context is shared and unsynchronised; concurrent use corrupts state. **Workaround:** one `z3.Context()` per `Encoder`/solve; all terms are created with that context. **Suggestion:** say so prominently in the z3py guide (it is only in an API note).

## D-5 `Optimize` timeouts are wall-clock for one `check()` only
- **Task:** keep "10 s per sketch" honest.
- **Actual:** the `timeout` option bounds `check()`, not term construction, model evaluation or the several `check()` calls of the margin climb and the hole box. A sketch with 5 holes on 40 noisy clips took 11.7 s end to end with `timeout_s=10` on a loaded machine.
- **Severity:** low-medium. **Workaround:** one deadline for the whole solve (each `check()` gets what is left, at least 0.5 s), a bounded placement step (`PLACEMENT_BUDGET_S`) and a bounded grid fallback (`GRID_BUDGET_S`), all documented in `solve_sketch`.

## D-6 Strands re-sends the whole conversation on every tool call, so tool-using agents cost quadratically in tool calls
- **Task:** CEGIS agent with `typecheck`, `solve_sketch`, `evaluate`, `fetch_counterexamples`, `submit_sketches` on the strong model.
- **Actual:** a 6-clip task is about 3k tokens; each tool call re-reads it, plus the growing history. A 40-clip MEVA run was 128k input tokens for 2.5k output (about $0.28). There is no prompt-caching switch on `BedrockModel` in 1.61 that we could rely on across the Windows setup.
- **Severity:** medium (cost). **Workaround:** the system prompt tells the model to try at most 2-3 sketches by hand per round; a per-round cap on agent-initiated solves (`max_agent_solves_per_round`); at most 6 traces of each label are shown in the task message (the solver still uses all of them); the orchestrator, not the model, runs the solves for submitted sketches.
- **Suggestion (Strands/Bedrock):** expose `cachePoint` on the system prompt and the first user message through `BedrockModel` config, and document the cost model of tool loops.

## D-7 Strands `Model` subclassing for offline tests is under-documented
- **Task:** test the agent/tool plumbing without Bedrock.
- **Actual:** a fake model must implement `update_config`, `get_config`, an async-generator `structured_output` and `stream` yielding raw Converse stream events (`messageStart`, `contentBlockStart` with `toolUse`, `contentBlockDelta` with a JSON string `input`, `contentBlockStop`, `messageStop`, `metadata`). We found this by reading the source; there is no mock model in the package.
- **Severity:** low. **Suggestion:** ship a scripted `MockModel` in `strands.models` or document the event shapes. `tests/agent/test_agent_strands_fake.py` is a working example.

## D-8 Strands cancellation needs two hooks
- **Task:** honour the API's `cancel` event during an LLM turn.
- **Actual:** `Agent.cancel()` stops the loop only at the next safe point, and a tool that merely returns "cancelled" does not stop the model from calling more tools. **Workaround:** tools call `Agent.cancel()` (through a hook on the run state) when they see the event, and a watcher thread does the same while the model is streaming.

## D-9 Bedrock strong model: forced tool choice is rejected, so `structured_output` is unusable
- Known from Phase 0 (P0-12, B-3). The agent therefore submits sketches through an ordinary tool (`submit_sketches`) and the loop salvages `exists ...` lines from prose if the model forgets to call it. Observed behaviour: 7/7 live runs called `submit_sketches`, and in both runs of the package-theft concept the model first sent a hole where a zone literal belongs (`leaves(p, ?z)`); the parser's error message ("expected a variable, zone or label") was enough for the model to fix it in the same turn.

## D-10 Git Bash `/tmp` is not Windows' temp directory
- `uv run python /tmp/x.py` works (the shell rewrites the argument), but `open("/tmp/x.py")` inside Python looks in `C:\tmp`. Scratch files for spikes should go to a fixed Windows path. Severity: low.
