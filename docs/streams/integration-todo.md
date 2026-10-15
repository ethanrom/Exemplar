# Integration TODO (integrator-owned)

## MEVA decision (user, after the X-diag report)
- X-diag (`stream/X-diag`, unmerged; $3.85 spent): neither 1280 px, ontology-v2 motion predicates nor the strong model (n too small) restore signal cheaply. The fast model describes the salient scene and misses the small labelled events.
- **User decision: stop MEVA accuracy work.** Evidence for the submission is the live Playground run, a cost-per-event-vs-number-of-rules chart (measured: fast perception $0.00179/event flat, zero-shot $0.0133 per rule per event), the guarantee simulation, and the differential-testing numbers.
- The Eval screen becomes an "Evidence" screen with those sections; this is in F2's current pass. MEVA rows stay in `data/eval/results.json`.

## PAUSED 2026-10-15 ~13:30 UTC (user request: subagent rate limits), resume here
- **Merged on main:** A, B, C, D, E, F, G-data, H, G-run. Engine suite is 840+ passed, eval suite 207 passed. The live Playground E2E passed (see below).
- **Stopped mid-work, resume via the same worktrees:**
  - `stream/F2-polish` (`D:/kaskara/exemplar-wt/F2-polish`): UI polish, refined dark design system + flow changes (the user chose both). 3 commits + 5 uncommitted paths. The original brief is in the session; restart it with "continue from the current worktree state, re-read your diff first". Before shots: `d:/tmp/exemplar-shots/polish/before/`.
  - `stream/X-diag` (`D:/kaskara/exemplar-wt/X-diag`): MEVA perception-signal diagnostic, train split only, $4 cap. Variants V0 cached / V1 fast@1280 / V2 fast@1280 + ontology v2 (moving, stationary, gets_into, gets_out_of, opens) / V3 strong@640. Only scaffolding so far (1 uncommitted path), $0 spent.
- **MEVA status:** the offline grid finished (120 rows in `data/eval/results.json`). Exemplar F1 is about 0–0.38 against zero-shot's 0.42–0.74, and escalation runs up to 48%, because the perception facts carry no signal (probe AUC about 0.5). Zero-shot baseline cached ($7.12). Eval spend so far is about $9.2 of the $75 cap. Decide after X-diag whether to re-perceive.
- **Presentation framing (user decision):** lead with guarantee validity, cost, explanations and the live demo. Update PROPOSAL.md "Evidence" to match.
- **Servers:** all stopped, ports free. Restart the engine with `cd engine && uv run python -m exemplar.api`. Restart the web app with `cd apps/web && npm run dev` (it needs a `.env.local` holding `ENGINE_URL` + a fresh token pasted on /connect). The seeded demo DB is `data/exemplar.sqlite3`: 2 concepts, 2 deployed rules, real firings.

## When D merges
- [ ] Check E's committee against D's real `hole_box` and `Candidate` (E only tested with fakes). Run `engine/tests/active` with D's types.
- [ ] Check that D exposes `Candidate.sketch` or a parseable `sketch_text` (E parses `sketch_text`).

## When H merges
- [ ] Wire D's `run_cegis` and E's `build_committee`/`select_query`/`calibrate`/`Monitor` into H's `Services` container (they 503 until wired).
- [ ] Monitor: upsert firings per (rule, event); run `process()` in a worker thread; pass `EventInput.trace` with `trace_cached=True` from ingest.
- [ ] Seed a dev DB with `python -m exemplar.api.seed --playground-spike --frollard`.
- [ ] UI against the real engine: `ENGINE_URL=http://127.0.0.1:8787 npm run dev`, then click through all six screens (PLAN Phase 3 step 1).

## Contract gaps from F (decide; additive api.yaml changes only)
1. `PATCH /concepts/{id}` (edit `nl_hint`, `alpha`).
2. Skip/exclude parameter on `GET /concepts/{id}/question`.
3. `Concept.last_run_id` (recover the last run after a reload).
4. Document error bodies (`{error, code}`) for 400/404.
5. The random-negatives-needed count is computed client-side as `⌈1/α⌉−1`. Expose it from `Calibration` or `Concept`?
6. Firing threshold = `max(0, τ_α)`. Confirmed: see `docs/DSL.md` "Calibration details".
7. Backtest paging. Probably not needed at our scale.
8. The engine closes the run SSE after `done`. Document it.
9. Document the `Witness.spans[].path` format in `docs/DSL.md`.

## E2E / live (needs the user: fresh token + Playground clicks)
- [x] **2026-10-15 11:43–11:58 UTC, PLAN §6 end-to-end on the real Playground:**
  - Token pasted through `PUT /api/ring/token`; web and engine both connected. The poller ingested every simulation by itself (history → clip → fast perception).
  - Rules taught with the real strong-model agent in 15–21 s: package "k is present at every moment within 0–19.5 s" (after a re-teach) and vehicle "v is in the driveway".
  - Package event fired only the package rule (score 0.45; witness `always` over 0.99–18.84 s). Vehicle event fired only the vehicle rule. Bird events fired neither. About $0.014 per event, no escalations.
  - **Lesson:** perception's zone label for the same box flips between `steps` and `porch` from run to run. The first rule ("on the steps ≥ 15 s") missed one package event. Adding that miss as a positive and re-teaching gave a zone-agnostic rule. For the demo, teach from at least 2 package recordings, or show this miss-then-re-teach as the story.
- [ ] Live view + frame grab (stream A's processor + F's toggle) against the real engine; the Ring watermark stays visible. Note: our live view is its own WHEP session ("Start live view" on /live); it does not follow the Playground's player, and each session also records an `on_demand` event.
- [ ] Stage-0 pruning shown with `scripts/send_signed_webhook.py --fresh --sub-type vehicle`.

## Eval
- [ ] G-run precompute stats. If perception fails on G336/G339/G436 (people 15–30 px even in the crop), swap to G506/G340: re-select, about 45 min download. **Pre-approved by the user.**
- [ ] Full `python -m eval.run` once D and E have merged. Charts go into `docs/eval/`.

## Housekeeping
- `next dev` children survive `TaskStop` on Windows. Kill orphaned `node ... next dev` processes by PID (`taskkill //PID <pid> //T //F`) before `npm ci`.
- `next-env.d.ts` is rewritten by every build. Restore it with `git checkout -- apps/web/next-env.d.ts` before committing.
- Phase 3: combine `docs/friction/*.md` into `docs/FRICTION_LOG.md`; write `README`, `FEEDBACK` and `DEVPOST`; **discuss the demo video with the user before recording**.
