# Integration TODO (integrator-owned)

Status on 2026-10-15 ~10:15 UTC: merged A, B, C, E, F, G-data. Running: D (synth/agent), H (api/store), G-run (eval).

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
