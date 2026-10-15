# Friction notes: stream F (UI)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion.

## F-1 The sample's Stop button sits on top of the Ring watermark
- **Task:** keep the mandatory Ring watermark (logo top-left, device ID + app name + timestamp top-right) uncovered in the live view.
- **Steps:** read `app/page.tsx` of `AmazonAppDev/ring-api-helloworld` @76100aa (the original, before this branch replaced it): the live-view container renders `■ Stop` at `absolute top-3 right-3` over the `<video>`, plus a full-size `<canvas>` overlay for processor bounding boxes.
- **Expected:** the sample respects the watermark rule that the Playground / Appstore review enforces.
- **Actual:** the Stop button covers the top-right watermark text, and any bounding box drawn by a processor can cover the top-left logo.
- **Severity:** medium (a submission could be flagged for hiding required branding).
- **Workaround:** in Exemplar the controls live in a toolbar under the video, the frame-grab processor draws nothing, and the canvas is hidden. Firing notices render beside the video, never over it.
- **Suggestion:** move the sample's Stop control out of the video box, and add a "keep top corners clear" note to the processor docs.

## F-2 The sample is not WCAG 2.2 AA out of the box
- **Task:** build an AA-conformant UI from the sample's dark palette (a stated Ring requirement).
- **Steps:** computed contrast for the sample's classes (`text-slate-500` on `#0F172A` / `#1E293B`, `bg-dash-card`), and read its markup.
- **Expected:** a baseline that passes.
- **Actual:** `text-slate-500` helper text on the dark panels is about 3.6 to 3.8:1 (needs 4.5:1), and `bg-dash-bg` is used in the loading and error states but is not defined in `tailwind.config.js` (so those screens render without a background).
- **Severity:** medium.
- **Workaround:** Exemplar defines its own `ex-*` tokens, checked by `npm run mock:contrast`, and the pages are scanned with axe-core (`mock/a11y.mjs`, 0 violations on all screens).
- **Suggestion:** ship the sample with an AA palette, since the requirement applies to every submission built on it.

## F-3 `tsconfig` target is `es5`, so `[...new Set(x)]` and `for..of` over a Map fail to compile
- **Task:** `npx tsc --noEmit` on the first UI draft.
- **Actual:** TS2802 "Type 'Set<string>' can only be iterated through when using '--downlevelIteration' or a target of es2015 or higher" (five places).
- **Severity:** low. `tsconfig.json` belongs to the sample (`"target": "es5"`, a Next 13 era default).
- **Workaround:** `Array.from(set)` everywhere in `apps/web/app/(exemplar)`.
- **Suggestion:** integrator may bump the target to `es2017` so future code can use normal iteration.

## F-4 `npm install` of one dev dependency rewrote a large part of the sample's lockfile
- **Task:** add `ajv@8` and `yaml` (dev only, for validating the mock engine against `api.yaml`).
- **Actual:** the committed `package-lock.json` was out of sync with `package.json` (stale `busboy`/`streamsearch`/`watchpack` entries); npm normalised it, giving a ~200 line diff unrelated to the change.
- **Severity:** low (noise in the merge; stream A also touches `package.json` / the lockfile, so expect a trivial conflict).
- **Workaround:** none needed; resolve the lockfile at integration with `npm install` on the merged `package.json`.

## F-5 `next build` and `next dev` rewrite the tracked `next-env.d.ts`
- **Actual:** after every build the file gains `/// <reference path="./.next/types/routes.d.ts" />`, which shows up as a modified tracked file.
- **Workaround:** `git checkout apps/web/next-env.d.ts` before committing.
- **Suggestion:** untrack `next-env.d.ts` and add it to `.gitignore` (Next regenerates it).

## F-6 Stray `.sr-only` text widened the whole page on phones
- **Task:** no horizontal scrolling at 390 px.
- **Actual:** `position:absolute` screen-reader text inside an `overflow-x:auto` table wrapper is positioned relative to the nearest *positioned* ancestor, so it escaped the clip, sat at the table's right edge (~760 px) and gave the document a 761 px scroll width. Flaky, because it only showed once the data had loaded.
- **Workaround:** `relative` on every scroll container that holds visually hidden text, plus a `@layer base { .grid { grid-template-columns: minmax(0,1fr) } }` default so wide children cannot stretch implicit grid columns. `mock/screenshots.mjs` now fails on any horizontal overflow at 390 px.

## F-7 Windows / Git Bash gotchas while verifying
- Git Bash rewrites arguments that start with `/` (`node script.mjs http://host /rule` became `C:/Program Files/Git/rule`). Use `MSYS_NO_PATHCONV=1`.
- `curl -F file=@/tmp/x` resolves `/tmp` differently for the Windows curl.exe than for the shell and fails silently with `-s`; use a relative path and `-sS`.
- `next dev` first compile after edits can take 30 to 50 s on this machine, which makes `waitUntil: 'networkidle'` flaky; the screenshot scripts therefore run against `next start` too.
- Port 3000 is usually taken by another worktree's dev server; `npm run dev:mock` honours `PORT` and `MOCK_PORT`.

## F-8 axe-core 4.x flags "Label in name" on thumbnail buttons
- **Actual:** a card thumbnail button named "View details: <summary>" that also contained the clip duration ("22 s") or the "No snapshot" placeholder text failed WCAG 2.5.3 (`label-content-name-mismatch`).
- **Workaround:** keep visible text out of the labelled button (chip rendered as a sibling, placeholder shows an icon only).

---

## Contract gaps and change requests for the integrator (api.yaml is frozen; nothing was invented)

1. **No `PATCH /concepts/{id}`.** `nl_hint` and `alpha` can only be set when the concept is created, so the Teach screen shows the hint read-only. Request: optional PATCH for `name`, `nl_hint`, `alpha`.
2. **No way to skip a question.** `GET /concepts/{id}/question` always returns the single best clip; after the user presses "Skip for now" the UI can only hide it locally. Request: an `exclude=clip_id,...` query parameter (or `POST .../question/skip`).
3. **Last run is not recoverable.** The timeline needs the run id, which only exists in memory after `POST .../teach`; navigating away loses it. Request: `Concept.last_run_id` (or `GET /concepts/{id}/runs?limit=1`) so the Teach screen can replay `/runs/{id}/stream`.
4. **Error statuses are mostly undocumented.** Only a few operations list 400/404/409. The UI assumes every non-2xx body is `{error, code}`; please document 400/404 on labels, concepts, runs and rules, and name the `code` for "provenance=random on a clip not drawn by /random-sample" (the mock returns 400 `INVALID_PROVENANCE`).
5. **Calibration need is computed client-side.** The Library shows "4 of 9 random negatives needed" from `Concept.alpha` and `counts.random_neg` using `ceil(1/alpha) - 1`. Request: `Concept.random_neg_needed` (optional) so the arithmetic lives only in the engine. On the Rule screen the engine's `Calibration.message` is shown verbatim, with the same formula as fallback.
6. **What is the firing threshold when `tau_alpha < 0`?** If every random negative scores below 0 the conformal threshold is negative. The mock fires on `score > max(0, tau_alpha)`. Please confirm, and document it next to `Calibration.tau`.
7. **`Backtest` is unpaged.** Fine for a few hundred clips; for MEVA-size libraries add `limit` / `matched_only` parameters.
8. **SSE termination.** The mock keeps run streams open after `done` and the UI closes them itself (EventSource would otherwise reconnect forever). Please state in the contract whether the engine closes the stream after `done`/`error`.
9. **`Witness.spans[].path`.** The UI only uses `path` for indentation depth (`body`, `body.left`, `body.args[1]`); document that each dot-separated segment is one nesting level, and whether atom leaves are included.
