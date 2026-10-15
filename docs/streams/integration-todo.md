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
- [ ] PLAN §6 end-to-end on the Playground: package and vehicle rules fire on their own events; the vehicle rule is dropped at stage 1.
- [ ] Live view + frame grab (stream A's processor + F's toggle) against the real engine; the Ring watermark stays visible.
- [ ] Stage-0 pruning shown with `scripts/send_signed_webhook.py --fresh --sub-type vehicle`.

## Eval
- [ ] G-run precompute stats. If perception fails on G336/G339/G436 (people 15–30 px even in the crop), swap to G506/G340: re-select, about 45 min download. **Pre-approved by the user.**
- [ ] Full `python -m eval.run` once D and E have merged. Charts go into `docs/eval/`.

## Housekeeping
- `next dev` children survive `TaskStop` on Windows. Kill orphaned `node ... next dev` processes by PID (`taskkill //PID <pid> //T //F`) before `npm ci`.
- `next-env.d.ts` is rewritten by every build. Restore it with `git checkout -- apps/web/next-env.d.ts` before committing.
- Phase 3: combine `docs/friction/*.md` into `docs/FRICTION_LOG.md`; write `README`, `FEEDBACK` and `DEVPOST`; **discuss the demo video with the user before recording**.
