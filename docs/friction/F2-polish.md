# Friction notes: stream F2 (UI polish)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion.

## F2-1 Ring's watermark sits in both top corners of every snapshot, which removes the usual places for card controls
- **Task:** a quiet thumbnail grid with a source badge, a duration, a selection checkbox and label controls on every card.
- **Steps:** looked at the Playground snapshots and clips at 640 px and 1280 px wide (logo top-left; device id, app name and timestamp top-right).
- **Expected:** the usual overlay slots (a checkbox top-left, a menu top-right) are free.
- **Actual:** both top corners are taken by the mandatory watermark, on thumbnails as well as on the live view. Any overlay there hides required branding.
- **Severity:** low (a design constraint, not a defect), but easy to violate by habit.
- **Workaround:** every overlay lives on the bottom edge (source tag bottom-left, duration bottom-right). Selection and label controls sit under the picture, in the card footer. `mock/scenes.mjs` draws the mock watermark in the same two corners so the constraint is visible in review.
- **Suggestion:** document the watermark safe area in pixels (or as a fraction of the frame) next to the branding rule, so apps can design to it.

## F2-2 Thumbnails of events that have a snapshot flag but no loadable picture rendered as blank boxes
- **Task:** polish the Library for a real Playground history.
- **Actual:** in the BEFORE capture two Ring events (`has_snapshot: true`) showed an empty dark box, because the `<img>` request to `/events/{id}/snapshot` failed (token already expired at capture time; cause not confirmed beyond that).
- **Severity:** low (cosmetic), but it looks like a bug in a demo.
- **Workaround:** `EventThumb` now falls back to the trace strip (entities as rows, facts as ticks over time) on `onError`, the same designed placeholder that fixtures get, so a missing picture still says something about the clip.
- **Suggestion:** the engine could report `has_snapshot: false` when the cached file is missing, or the snapshot route could return a typed 404 the UI can distinguish from a transport error.

## F2-3 axe-core flags "Label in name" on links whose `aria-label` replaces their visible text
- **Task:** keep `mock/a11y.mjs` at zero violations after the header redesign.
- **Actual:** the token chip showed "Ring · 23 min" but carried `aria-label="Ring Playground token, 23 minutes left. Open Connect."`. WCAG 2.5.3 (`label-content-name-mismatch`) fails because the visible text is not contained in the name. Same family as F-8.
- **Severity:** low.
- **Workaround:** no `aria-label`; the extra context is a visually hidden suffix inside the link, so the accessible name starts with the visible text. The same rule applies to the thumbnail buttons: the trace-strip placeholders contain no visible words, only icons.
- **Suggestion:** none for Ring; a note for future UI work: prefer a hidden suffix over `aria-label` on anything with visible text.

## F2-4 `next dev` and `next start` cannot share one checkout, and `next.config.js` (not ours) has no `distDir` switch
- **Task:** run a real-data UI (port 3001 → engine 8787) and a mock-data UI (port 3002 → mock 8788) side by side for screenshots.
- **Actual:** both servers write `.next/` in the same directory, so a dev server and a production build overwrite each other (the dev server then serves chunks that no longer exist).
- **Workaround:** iterate with one dev server (mock engine), then stop it, `npm run build`, and start two `next start` processes from the same build with different `ENGINE_URL`. They only read `.next/`, so this is safe.
- **Suggestion:** let `next.config.js` read `NEXT_DIST_DIR` so two servers can run from one checkout.

## F2-5 Windows / Git Bash
- A Python patch script passed through a shell heredoc broke on a quote inside the script (`unexpected EOF while looking for matching`) and silently applied nothing. Writing the script to a file first (and checking `git diff`) is reliable.
- `next dev` / `next start` children outlive the shell that started them: stop them by PID (`netstat -ano | grep :3002`, then `taskkill //PID <pid> //T //F`).

## F2-6 Positive: the Ring device image URL works as a plain `<img>`
- `GET /v1/devices` returns `image_url` (`app-content.ring.com/.../DoorbellPro/rvdp_3x.png`), a public CDN asset that needs no token. The Connect screen shows it on the device card, with a camera icon as the fallback.
