# Friction log

Problems we hit while building Exemplar on the Ring API, the Ring Developer Playground, Amazon Bedrock, the Strands Agents SDK and AWS Open Data, written down as they happened. Each entry gives the task, the steps, expected versus actual behaviour, a severity, the workaround we used and an actionable suggestion. Entries marked **(live)** were reproduced against the Developer Playground on 2026-10-15; the others come from building against the documentation and the SDKs.

**Severity:** *high* = invalidates a design or a demo; *medium* = cost real time or forced a workaround in the product; *low* = confusing, cosmetic or informational.

Entries are grouped by tool. Our own feedback on each tool (what worked, onboarding, would we use it again) is in [`FEEDBACK.md`](FEEDBACK.md).

| Id | Tool | Severity | One line |
|---|---|---|---|
| RING-1 | Ring API | medium | History events carry no `sub_type` |
| RING-2 | Ring API | low | Image download with an ISO timestamp returns an opaque 403 |
| RING-3 | Ring API | low | Media redirect points at an `ap-northeast-1` host for a US device |
| RING-4 | Ring API | medium | `latest_in_range` snapshot passes the POST, then fails with an undocumented 422 (live) |
| RING-5 | Ring API | low-medium | Pre-signed media GET blocks for 12-48 s with no progress signal (live) |
| RING-6 | Ring API | medium | A video longer than the event returns 200 with the next events' footage, not 206 (live) |
| RING-7 | Ring API | low-medium | History: undocumented fields, ambiguous `links.next` contract (live) |
| RING-8 | Ring API | low | 401 responses have an empty body (live) |
| RING-9 | Ring API | low | Transient `Server disconnected` while polling |
| RING-10 | Ring API | low | Device location has no time zone |
| RING-11 | Ring API | medium | Webhook payloads carry a start time but no clip length |
| RING-12 | Ring API | low | History event ids are 140+ characters, only the tail differs |
| RING-13 | Ring API | medium | Chime playback returns a generic 400 and cannot be exercised |
| RING-14 | Ring API | low | WHEP session URL has a long query string that DELETE needs verbatim |
| PG-1 | Playground | high | The package clip is credited as a theft but contains no thief |
| PG-2 | Playground | medium | Simulated events: `on_demand` only, listed 27-44 s late, no webhook (live) |
| PG-3 | Playground | medium | `event_types` filter has no effect on simulated events (live) |
| PG-4 | Playground | medium | Media authorization starts at the first token's consent, undocumented (live) |
| PG-5 | Playground | medium | OAuth app mode cannot be exercised with Playground access |
| PG-6 | Playground | low | `status.online` flips and gates nothing (live) |
| PG-7 | Playground | medium | The vehicle clip does not give a stable single-vehicle story |
| APP-1 | Sample app | medium | Webhook route does not verify the documented HMAC signature |
| APP-2 | Sample app | medium | `DELETE /api/ring/stream` forwards the bearer token to any URL |
| APP-3 | Sample app | medium | The Stop button covers the mandatory Ring watermark |
| APP-4 | Sample app | medium | Not WCAG 2.2 AA out of the box |
| APP-5 | Sample app | low | README badge says Next.js 14, `package.json` pins 15.5; `tsconfig` targets `es5` |
| APP-6 | Sample app | low | Lockfile out of sync; `next-env.d.ts` tracked and rewritten |
| BR-1 | Bedrock | medium | New Claude models: `temperature` rejected, per-model `toolChoice` and `thinking` rules |
| BR-2 | Bedrock | medium | `ConnectionClosedError` after botocore exhausted its retries (live) |
| BR-3 | Bedrock | medium | Same request takes 10 s to 64 s; concurrency makes it worse (live) |
| BR-4 | Bedrock | medium | A few Converse calls hang for 5+ minutes instead of failing (live) |
| BR-5 | Bedrock | low | botocore error messages embed the model id |
| BR-6 | Bedrock | low | Output length, cost and latency vary 18x for the same prompt shape |
| BR-7 | Bedrock | medium | A bare "probability" next to a boolean is read two ways by the model |
| STR-1 | Strands | medium | The whole conversation is re-sent on every tool call; no prompt-cache switch |
| STR-2 | Strands | low | Writing a fake `Model` for offline tests means reading the source |
| STR-3 | Strands | low | Cancelling a run needs two hooks |
| S3-1 | AWS Open Data (MEVA) | medium | About 1 MB/s from a US-East-1 public bucket |
| S3-2 | AWS Open Data (MEVA) | medium | Public annotations contain no theft-like activity; names changed in 2020 |
| S3-3 | AWS Open Data (MEVA) | low | Annotation frames can exceed the video length; indexing base undocumented |
| S3-4 | AWS Open Data (MEVA) | medium | Wide-angle scenes: people 10-40 px tall, fine detail is lost at model resolution |
| OT-1 to OT-10 | Other tooling | low-medium | Z3, Lark, SQLite, FastAPI/SSE, Next.js, ffmpeg, Windows and Git Bash, floating point |

---

## Ring API

### RING-1 History events carry no `sub_type`
<!-- orig: P0-5 -->
- **Task:** use the smart-alert sub-type (human, vehicle, other motion) as a free first filter on each event.
- **Steps:** read the event-history docs, then list events for a device.
- **Expected:** `sub_type` on each history event, as webhooks carry `data.subType`.
- **Actual:** history events expose only `event_type` (`motion`, `on_demand`, `ding`), `start`, `end`. The sub-type is reachable only by re-querying with `event_types=motion.human` and so on.
- **Severity:** medium.
- **Workaround:** the poller queries each `motion.<sub>` filter and tags events by the filter that returned them (`RingClient.history_tagged`).
- **Suggestion:** include `sub_type` in the history event attributes.

### RING-2 Image download with an ISO timestamp returns an opaque 403
<!-- orig: P0-2 -->
- **Task:** request a snapshot with `timestamp` as an ISO-8601 string.
- **Steps:** `POST /v1/devices/{id}/media/image/download` with `{"type":"at_timestamp","timestamp":"2026-10-15T06:30:00Z"}`.
- **Expected:** 400 `INVALID_PAYLOAD` naming the bad field, as the error-handling page documents for bad bodies.
- **Actual:** 403 `REQUEST_FORBIDDEN` "invalid request body". A 403 reads as an authorization problem and sends the developer down the wrong path.
- **Severity:** low.
- **Workaround:** send epoch milliseconds.
- **Suggestion:** return 400 with a field pointer.

### RING-3 Media redirect points at an `ap-northeast-1` host for a US device
<!-- orig: P0-3 -->
- **Task:** download a clip for a device located in CA/US.
- **Observation:** the pre-signed `Location` of the 303 is `download-ap-northeast-1.prod.phoenix.devices.amazon.dev`, while the docs show `media.api.amazonvision.com`. It works, but it is surprising in a data-residency review and for egress allow-lists.
- **Severity:** low (informational).
- **Workaround:** none needed; our client follows the redirect without the bearer token.
- **Suggestion:** document which hosts pre-signed media URLs can come from.

### RING-4 `latest_in_range` snapshot passes the POST, then fails with an undocumented 422 (live)
<!-- orig: A-1 -->
- **Task:** fetch the newest snapshot inside an event window.
- **Steps:** `POST …/media/image/download` with `{"type":"latest_in_range","start_timestamp":…,"end_timestamp":…}` for the window of a known event; also without `end_timestamp`, and with a 25-minute window.
- **Expected:** 303 then 200 `image/jpeg` (as `at_timestamp` gives for the same event), or a documented error.
- **Actual:** 303, so the POST looks successful, then the pre-signed GET answers 422 `GRECO_NO_VALID_KEY` "No valid Greco key available for decryption". The docs list 422 only as `CORRUPT_RECORDING`.
- **Severity:** medium.
- **Workaround:** use `at_timestamp` with the event `start` (10 s tolerance). The client raises `UnprocessableMediaError` with `.code == "GRECO_NO_VALID_KEY"` and does not retry.
- **Suggestion:** document `GRECO_NO_VALID_KEY`, and fail the POST instead of redirecting when the GET cannot succeed.

### RING-5 Pre-signed media GET blocks for 12-48 s with no progress signal (live)
<!-- orig: A-3 -->
- **Task:** download a 20-40 s clip after the 303.
- **Steps:** GET the `Location` URL and time it. Default options: 12-14 s for a 31.7 s clip (1.8 MB), about 4 s for a 40 KB snapshot. With `video_options` (640x360, 5 fps) a 21 s clip took 25.7 s (1.2 MB); a 60 s window took 48.3 s (8.6 MB).
- **Expected:** a quick fetch of a pre-signed object (the docs describe a plain GET with no auth).
- **Actual:** the GET stays open for tens of seconds while the clip is rendered and watermarked. Default client timeouts (httpx 5 s read, many SDK defaults 10-30 s) fail with `ReadTimeout`, which looks like a network fault and triggers retries that restart the render.
- **Severity:** low-medium.
- **Workaround:** 180 s read timeout on the media GET only (30 s on JSON calls); `ReadTimeout` is a retried transport error.
- **Suggestion:** document typical latency and recommended timeouts for the download step, or return 202 with `Retry-After` while the file is produced.

### RING-6 A video longer than the event returns 200 with the next events' footage, not 206 (live)
<!-- orig: A-4 -->
- **Task:** download exactly one event's clip.
- **Steps:** `video/download` with `timestamp = event.start` and `duration = 60000` for a 21.5 s event followed about 30 s later by another simulated event.
- **Expected:** `206 Partial Content` with `x-media-duration` close to the event length (the media-clips page says 206 is returned "when the full requested duration is not available").
- **Actual:** `200` with `x-media-duration: 59751`. The clip silently continues into the next event(s), so a "package" clip would contain the following "bird feeder" footage.
- **Severity:** medium for any perception pipeline.
- **Workaround:** always request `duration = event.end - event.start`; the returned `x-media-duration` is exposed as `MediaResult.media_duration_ms`.
- **Suggestion:** clamp to the event's recording boundary, or document that downloads are continuous-recording windows rather than event-scoped.

### RING-7 History: undocumented fields and an ambiguous `links.next` contract (live)
<!-- orig: A-5 -->
- **Task:** page through `GET /v1/history/devices/{id}/events`.
- **Steps:** unfiltered query (6 events in the Playground account), then `page[key]=<iso>` with a made-up cursor.
- **Expected:** `data[].relationships.source` only, and one clear statement about filters in `links.next`.
- **Actual:** the same page of the docs says `links.next` "includes all original filters plus the pagination cursor" (prose) and, in its sample code, "re-apply filters since links.next only contains the cursor". Each event also carries `relationships.cv_detections.data` (empty here) and `meta.riid` (null), neither documented. The 6-event response has no `links` key at all, and a made-up cursor returns `{"data": []}` with no `links`, so cursor following could not be exercised live. The docs also say `links.next` can be present with empty `data`.
- **Severity:** low (unknown fields are ignorable) to medium (the pagination contract).
- **Workaround:** follow `links.next` verbatim, re-add `event_types` only if the next URL lacks it, and stop on empty `data`, on a page that adds no new ids, at `max_pages`, or when events get older than the cutoff. Covered by mocked pagination tests.
- **Suggestion:** pick one statement about filters in `links.next`; document `cv_detections` and `riid` or drop them from public responses; state the page size.

### RING-8 401 responses have an empty body (live)
<!-- orig: A-6 -->
- **Task:** classify authentication failures.
- **Steps:** `GET /v1/users/me` with a garbage bearer token, and with no `Authorization` header.
- **Expected:** `{"errors":[{"status":"401","title":"Invalid Client"}]}` as the error-handling page documents.
- **Actual:** HTTP 401 with a zero-length body in both cases.
- **Severity:** low.
- **Workaround:** the error mapper treats an empty or non-JSON body as "no code" and relies on the status; a 401 triggers one token refresh when the provider can.
- **Suggestion:** send the documented JSON body, ideally with a code that separates missing, malformed and expired tokens (a "paste a fresh token" prompt needs exactly that distinction).

### RING-9 Transient `Server disconnected` while polling
<!-- orig: P0-11 -->
- **Task:** poll history every 4 s during a long session.
- **Actual:** after about 8 minutes the loop died on `httpx.RemoteProtocolError: Server disconnected without sending a response`.
- **Severity:** low.
- **Workaround:** retry transport errors with backoff, not only 5xx and 429.
- **Suggestion:** document that keep-alive connections can be closed by the service and that clients should retry idempotent GETs.

### RING-10 Device location has no time zone
<!-- orig: H-1 -->
- **Task:** fill `local_hour` and `weekday` for hour-of-day rules ("motion at 3 am"), which needs the device's local time.
- **Steps:** `GET /v1/devices/{id}/location` (live).
- **Expected:** an IANA zone in the location resource.
- **Actual:** only `{"country": "US", "state": "CA"}`.
- **Severity:** low (a silently wrong local hour is the real risk, because hour rules would misfire).
- **Workaround:** a state-to-zone table plus a built-in implementation of the current US DST rules, tested at the boundary hours (`engine/exemplar/api/tz.py`).
- **Suggestion:** return `time_zone` (IANA) in the location attributes.

### RING-11 Webhook payloads carry a start time but no clip length
<!-- orig: H-2 -->
- **Task:** download the clip for a `motion_detected` or `button_press` webhook.
- **Steps:** read the notifications page and our signed fixtures: `data.attributes.timestamp` only.
- **Expected:** an `end` or `duration`, as history events have, so the receiver knows when the recording is complete and how long a video to request.
- **Actual:** only the start. `video/download` needs a `duration`, and asking for more than the event length returns the following events' footage (RING-6), so the length matters. The Playground sends no webhooks, so this could not be tested live.
- **Severity:** medium for real devices.
- **Workaround:** assume a 10 s clip (configurable), wait until start + 10 s + 5 s, and treat the later history hit within 5 s on the same device as the same event.
- **Suggestion:** add `end` or `duration` (or a follow-up `motion_ended` notification), or document the usual recording length.

### RING-12 History event ids are 140+ characters and only their tails differ
<!-- orig: H-3 -->
- **Task:** store a clip per event under a data directory on Windows.
- **Actual:** ids look like `ava1.ring.history.event.<140+ characters>`. Used verbatim as file names they approach `MAX_PATH` (260) under a deep directory; truncating the front makes different events collide because the shared prefix is long.
- **Severity:** low.
- **Workaround:** keep short ids as they are, otherwise a sanitized prefix plus a 12-hex SHA-1 of the whole id.
- **Suggestion:** document the id length bound, or put the unique part first.

### RING-13 Chime playback returns a generic 400 and cannot be exercised
<!-- orig: P0-4, E-1 -->
- **Task:** call `POST /v1/devices/{id}/media/audio/playback` from a rule action.
- **Steps:** `GET …/configurations` shows `audio.customizable_slots: null` and capabilities `audio.supported_actions: null`; POST `{"data":{"type":"audio","attributes":{"audio_ref":"…"}}}`.
- **Expected:** 403 for a read-only token, or a documented "not supported" error.
- **Actual:** 400 `Validation Error` "The request contains invalid input.", with no hint whether the device, the token scope or `audio_ref` is the problem. The format of a real `audio_ref` is not documented for the Playground.
- **Severity:** medium (an early-access feature cannot be exercised without staging hardware).
- **Workaround:** the Chime action sits behind a flag, is tested against a mocked client, and records the failure instead of hiding it.
- **Suggestion:** give the virtual device a chime slot, or return distinct errors (`CHIME_NOT_SUPPORTED`, scope), and document `audio_ref`.

### RING-14 WHEP session URL has a long query string that DELETE needs verbatim
<!-- orig: P0-10 -->
- **Observation:** WHEP from the forked sample works in Chrome (H.264 High `64001f`, 1280x720 at 28 fps, first frame 4.9 s after Start). The `Location` header of the session carries a long `?location=ava1.ring.whep.location…` query; closing the session needs the full URL, which a server proxy must validate (we allow only `https://api.amazonvision.com/v1/devices/<id>/media/streaming/whep/sessions/…`).
- **Severity:** low.
- **Suggestion:** document that the query is part of the session URL.

---

## Ring Developer Playground

### PG-1 The package clip is credited as a theft but contains no thief
<!-- orig: P0-9 -->
- **Task:** build a package-theft demo on the Playground's simulated package event.
- **Steps:** download the 31.7 s recording of a simulated package event and run perception on it.
- **Expected:** the footage behind the credit "Thief stealing our package": a person arrives, takes the box, leaves.
- **Actual:** about 6 s of the source footage loops (the source camera clock cycles 15:57:38 to 15:57:44 repeatedly; 49 unique frames out of about 950). A box sits on snowy steps and no person appears. The Playground's own player shows the same. Fast and strong perception both report "package, no person".
- **Severity:** high for anyone building theft demos on it.
- **Workaround:** live rules are built around what the clips contain ("a package has been sitting on the steps"); the theft story is taught from the full CC BY source footage uploaded through our own `upload` source.
- **Suggestion:** ship the full clip, and ideally a delivery clip as its negative.

### PG-2 Simulated events: `on_demand` only, listed 27-44 s late, no webhook (live)
<!-- orig: P0-7, P0-5, H-8 -->
- **Task:** trigger Simulate Package / Vehicle / Motion and pick the events up through history.
- **Steps:** click Simulate, poll `GET /v1/history/devices/{id}/events`, download media.
- **Actual:**
  - each click opens a WHEP live session (201) and produces one `on_demand` history event (not `motion` or `ding`), listed 27-44 s after its `start`; durations are 31.7 s (package), 21.5 s (vehicle) and 39.2 s (motion);
  - video and snapshot download return 200 after the 303 as soon as the event is listed; no 416/425 was seen;
  - our own app's live-view session (6 s) also produced an `on_demand` event, 39.2 s long, i.e. the whole canned clip regardless of the session length;
  - re-downloading the same event returns different bytes each time (the watermark's `Generated-At` is re-rendered);
  - end to end, a trigger shows up in our library 1-2 minutes later (27-44 s listing delay, 12-25 s download, 10-40 s perception).
- **Severity:** medium.
- **Workaround:** treat `on_demand` as the Playground's event type; ingest each event once and cache by event id, not by content hash; trigger events early when demonstrating.
- **Suggestion:** emit `motion` events with the matching `motion.<sub>` sub-type for simulated events, and send a webhook, so apps can exercise their real event paths.

### PG-3 `event_types` filter has no effect on simulated events (live)
<!-- orig: P0-8 -->
- **Steps:** the same history call with `event_types` = `ding`, `motion`, `motion.human`, `motion.vehicle`, `motion.other_motion`, `on_demand`, and none.
- **Expected:** only `on_demand` returns the simulated events.
- **Actual:** every filter, including `ding` and `motion.vehicle`, returned the same `on_demand` events.
- **Severity:** medium (the filter cannot be used for sub-type tagging or prefiltering in the sandbox).
- **Workaround:** none needed for the Playground; the sub-type prefilter falls back to "no sub-type", and the signed-webhook replay tool exercises sub-type pruning instead.
- **Suggestion:** apply the filter, or document that the sandbox ignores it.

### PG-4 Media authorization starts at the first token's consent, undocumented (live)
<!-- orig: P0-1 -->
- **Task:** download a snapshot or clip for an earlier time.
- **Steps:** `POST …/media/image/download` with `{"type":"at_timestamp","timestamp":…}` for times before and after various tokens' `iat`.
- **Expected:** 416 `MEDIA_NOT_FOUND` (nothing recorded) or the media.
- **Actual:** 403 `TIME_RANGE_NOT_AUTHORIZED` for any time before the first Playground token we minted that day; after it, 416 or 200. Media recorded under earlier tokens stays downloadable with later tokens, and history keeps listing those events. We first assumed the boundary was each token's `iat`, and designed around "ingest on arrival or lose it" until we re-tested.
- **Severity:** medium.
- **Workaround:** none needed beyond knowing it; backtests over Playground history work across tokens.
- **Suggestion:** document what consent time a Playground token carries and whether it resets, and return it (for example `consented_at`) from `/v1/users/me`.

### PG-5 OAuth app mode cannot be exercised with Playground access
<!-- orig: A-2 -->
- **Task:** verify `authorization_code` with PKCE, refresh-token rotation and `app-integrations` POST/PATCH.
- **Steps:** the Playground only hands out a read-only 30-minute access token.
- **Expected:** a sandbox path (a test client, a fake link flow) to run the real token endpoint.
- **Actual:** no `client_id` or `client_secret`, no refresh token and no account-link redirect, so nothing to call. Our `OAuthApp` (exchange, rotating refresh with early refresh, a concurrent-refresh guard, nonce check, POST/PATCH completion) is covered by mocked-HTTP tests only; response shapes are taken from the docs.
- **Severity:** medium (an entire documented authentication path is unverified against the real service).
- **Workaround:** the demo uses the Playground token; the OAuth path ships as code and tests.
- **Suggestion:** a sandbox OAuth client for the Playground account, or a documented test `client_id`, so partners can run exchange and rotation end to end.

### PG-6 `status.online` flips and gates nothing (live)
<!-- orig: A-7 -->
- **Observation:** `GET …/status` returned `online: false` at 06:53 UTC (`reported_at` 06:34:31Z) and `online: true` at 08:13 UTC; WHEP, history and media worked in both states. The device-discovery docs call `online` "the primary indicator for whether live streaming or commands will work".
- **Severity:** low.
- **Workaround:** `online` is informational in our client; nothing is gated on it.
- **Suggestion:** pin the virtual device to `online: true`.

### PG-7 The vehicle clip does not give a stable single-vehicle story
<!-- orig: B-7 -->
- **Task:** teach "a vehicle moves through the lot" from the simulated vehicle event.
- **Actual:** the clip shows parked cars, a car driving past, then a second camera on a driveway. Perception splits it into 5-7 vehicle ids across runs (identity cannot be recovered across the 2-5 s gaps between sampled frames), so movement shows up only as zone changes.
- **Severity:** medium for the demo rule.
- **Workaround:** the deployed rule is the zone-based "there is a vehicle v such that v is in the driveway".
- **Suggestion:** a Playground vehicle clip with one vehicle entering and leaving.

---

## Ring sample app (`AmazonAppDev/ring-api-helloworld` @ `76100aa`)

### APP-1 Webhook route does not verify the documented HMAC signature
<!-- orig: P0-6 -->
- **Task:** receive Ring webhooks with the sample's `/api/webhook` route.
- **Steps:** read the route against the notifications page.
- **Expected:** `X-Signature` verified with HMAC-SHA256 over the raw body, constant-time comparison.
- **Actual:** the route compares a static `Authorization: Bearer` value with `!==` (not constant-time), parses the JSON before anything else, never looks at `X-Signature`, and accepts every POST when `RING_WEBHOOK_SECRET` is unset.
- **Severity:** medium (partners will copy it).
- **Workaround:** we replaced it with `/api/ring/webhook`: raw-body HMAC with a constant-time comparison, `meta.request_id` deduplication, a 200 inside Ring's 5 s window, lifecycle events, and a signed replay tool.
- **Suggestion:** update the sample to the documented verification.

### APP-2 `DELETE /api/ring/stream` forwards the bearer token to any URL
<!-- orig: P0-6 -->
- **Task:** close a WHEP session from the browser through the sample's server route.
- **Actual:** the route sends `Authorization: Bearer <access token>` to whatever `sessionUrl` the client supplies, so any caller can make the server send the token to an arbitrary host.
- **Severity:** medium.
- **Workaround:** we only accept `https://api.amazonvision.com/v1/devices/<id>/media/streaming/whep/sessions/…` (tested).
- **Suggestion:** validate `sessionUrl` against the Ring API origin.

### APP-3 The Stop button covers the mandatory Ring watermark
<!-- orig: F-1 -->
- **Task:** keep the watermark (logo top-left; device id, app name and timestamp top-right) uncovered in the live view.
- **Actual:** the sample renders `Stop` at `absolute top-3 right-3` over the `<video>`, which covers the top-right text, and a full-size `<canvas>` overlay for processor bounding boxes can cover the top-left logo.
- **Severity:** medium (a submission could be flagged for hiding required branding).
- **Workaround:** our controls live in a toolbar under the video, the frame-grab processor draws nothing, and firing notices render beside the video.
- **Suggestion:** move the Stop control out of the video box and add a "keep the top corners clear" note to the processor docs.

### APP-4 Not WCAG 2.2 AA out of the box
<!-- orig: F-2 -->
- **Task:** build an AA-conformant UI from the sample's dark palette.
- **Steps:** compute contrast for the sample's classes and read its markup.
- **Actual:** `text-slate-500` helper text on the dark panels is about 3.6-3.8:1 (4.5:1 needed), and `bg-dash-bg` is used in the loading and error states but not defined in `tailwind.config.js`, so those screens render without a background.
- **Severity:** medium.
- **Workaround:** our own design tokens, checked by `npm run mock:contrast`, and an axe-core scan of every screen (0 violations).
- **Suggestion:** ship the sample with an AA palette, since the requirement applies to every submission built on it.

### APP-5 README badge says Next.js 14, `package.json` pins 15.5; `tsconfig` targets `es5`
<!-- orig: P0-6, F-3 -->
- **Observation:** the README badge reads "Next.js 14" while `package.json` pins `next` 15.5.18. `tsconfig.json` has `"target": "es5"`, so `[...new Set(x)]` and `for..of` over a `Map` fail with TS2802 (five places in our first draft).
- **Severity:** low.
- **Workaround:** `Array.from(...)`.
- **Suggestion:** align the badge and bump the target to `es2017`.

### APP-6 Lockfile out of sync; `next-env.d.ts` tracked and rewritten
<!-- orig: F-4, F-5 -->
- **Actual:** adding one dev dependency made npm normalise a lockfile that was out of sync with `package.json` (stale `busboy`, `streamsearch`, `watchpack` entries), a roughly 200-line unrelated diff. `next build` and `next dev` rewrite the tracked `next-env.d.ts` (adding a `routes.d.ts` reference), so it shows up as modified after every build.
- **Severity:** low.
- **Workaround:** resolve the lockfile once; `git checkout apps/web/next-env.d.ts` before committing.
- **Suggestion:** regenerate the lockfile, untrack `next-env.d.ts` and add it to `.gitignore`.

---

## Amazon Bedrock (Claude via Converse and application inference profiles)

### BR-1 New Claude models: `temperature` rejected, per-model `toolChoice` and `thinking` rules
<!-- orig: P0-12, B-3, D-9 -->
- **Task:** structured output through tool use from the fast and the strong model.
- **Steps:** the usual recipe: forced `toolChoice`, a `temperature`, no thinking settings.
- **Expected:** the recipe in the Bedrock docs works for both models.
- **Actual:**
  - `temperature` is rejected on both models ("`temperature` is deprecated for this model"), and the Strands `BedrockModel` passes it if set;
  - fast model: forced `toolChoice: {tool}` works only together with `thinking: {"type": "disabled"}`;
  - strong model: `thinking: disabled` is rejected ("send `{"type": "between_tools"}` instead") and forced `toolChoice` (`tool` or `any`) is rejected outright, which also makes Strands `structured_output` unusable.
- **Severity:** medium (every structured-output recipe in the AWS docs uses forced tool choice).
- **Workaround:** strong model: `toolChoice: auto` with `thinking: between_tools` and an explicit "you MUST call the emit_trace tool exactly once" instruction, then validate and retry. This was reliable: 6 of 6 live calls (16, 24 and 32 frames) called the tool, and the validate-and-retry round trip (resending the assistant turn with a `toolResult` of status `error`) worked with the real model. Sketches go through an ordinary tool (`submit_sketches`); 7 of 7 live runs called it.
- **Suggestion:** document per-model support for `toolChoice`, `thinking` and sampling parameters on the model cards, make Converse error messages name the supported alternative consistently, and describe `auto` plus an instruction as the recommended structured-output recipe for models that reject forced choice.

### BR-2 `ConnectionClosedError` after botocore exhausted its retries (live)
<!-- orig: B-1 -->
- **Task:** fast-model perception of a 30 s window, 24 images (about 10.5k input tokens), right after a successful 32-frame strong call.
- **Steps:** `bedrock-runtime` `converse` through boto3 with `read_timeout=300` and adaptive retries, 4 attempts.
- **Expected:** a response, or a typed `ThrottlingException` or `ServiceUnavailableException` that says what to do.
- **Actual:** `ConnectionClosedError: Connection was closed before we received a valid response from endpoint URL …` on all 4 attempts (about 90 s). The identical request a minute later succeeded. Seen once in about 45 live calls.
- **Severity:** medium (an unexplained failure with nothing to act on; it may already have been billed).
- **Workaround:** wrap botocore errors in a typed backend error carrying the AWS code so callers can retry or fall back; cache nothing on failure.
- **Suggestion:** return a structured 5xx or throttling error instead of dropping the connection, and document whether input tokens are billed for requests that die this way.

### BR-3 The same request takes 10 s to 64 s; concurrency makes it worse (live)
<!-- orig: B-2, GR-4 -->
- **Task:** budget per-event latency for the live monitor.
- **Observations (fast model, 16 frames, about 7.9k in and 1.3-2.4k out):** sequential calls 10-37 s; 2 concurrent calls 14-20 s each; 4 concurrent calls 36-64 s each; a 24-frame call took 48 s for 1.4k output tokens. Over 1,005 clips at concurrency 3 the p50 was 15.6 s, p90 21.3 s, p99 29.5 s. No `ThrottlingException` surfaced (botocore's adaptive mode may absorb throttling silently, so we cannot tell).
- **Expected:** latency roughly proportional to output tokens.
- **Severity:** medium for a live demo; no effect on correctness.
- **Workaround:** shorter outputs (a prompt change cut output tokens by about 40%), at most 2 concurrent perception calls in the product, a cache for every trace.
- **Suggestion:** expose queue time versus generation time in the Converse `metrics`, and say in the docs when concurrency on an application inference profile is limited.

### BR-4 A few Converse calls hang for 5+ minutes instead of failing (live)
<!-- orig: GR-1 -->
- **Task:** run fast perception over 1,005 windows (about 8k input tokens each) at concurrency 3, and 527 strong-model calls at concurrency 2.
- **Actual:** with a 300 s read timeout, 6 of about 1,530 calls stalled for 311-336 s and then succeeded on the retry (5 fast, 1 strong), with no error in between. Three hit at the same moment, so all three workers were blocked for about 5 minutes. After lowering the client timeout to 90 s, none of the remaining roughly 1,400 calls took longer than 60 s.
- **Severity:** medium (a silent 5-minute stall on one event would be a visible failure in a live monitor).
- **Workaround:** a 90 s read timeout with retries and back-off.
- **Suggestion:** document time-to-first-byte behaviour of application inference profiles, and whether input tokens are billed for a request abandoned after the read timeout (we could not tell; our ledger counts answered calls only).

### BR-5 botocore error messages embed the model id
<!-- orig: B-4 -->
- **Task:** keep model ids and ARNs out of logs.
- **Actual:** `ConnectionClosedError` and `ClientError` messages contain the endpoint URL `…/model/<model-id>/converse`, so anything that logs `str(exc)` leaks the id (ours appeared in a terminal traceback).
- **Severity:** low.
- **Workaround:** replace the id with `<model>` and scrub ARNs and URLs in anything we log or emit.
- **Suggestion:** put the model id in the exception attributes rather than in the message text, or document that it is there.

### BR-6 Output length, cost and latency vary 18x for the same prompt shape
<!-- orig: GR-2 -->
- **Task:** budget the perception pass.
- **Actual:** fast model, 16 frames, 7,956 input tokens every time, but 325 to 5,831 output tokens (median 1,918): the model restates facts in every frame when people and vehicles are present. Cost per clip ranged from $0.0010 to $0.0048 (mean $0.00179); the whole 1,005-clip pass cost $1.80, well under our estimate, because most windows have few entities.
- **Severity:** low (budgeting only).
- **Workaround:** a budget guard that reserves a conservative amount per call and settles on real usage.
- **Suggestion:** none for Bedrock; the lesson is to cap "facts per frame" in the prompt to flatten latency.

### BR-7 A bare "probability" next to a boolean is read two ways by the model
<!-- orig: GR-3 -->
- **Task:** obtain a score from a Claude answer of the form `{"match": bool, "confidence": 0..1}` by tool use.
- **Actual:** the tool was called with a valid schema on every call (one validation retry in 527 calls). But although the field is described as the probability that the event occurs, 50 of 527 answers (9.5%) gave `match=false` together with a high confidence (0.85-0.97), i.e. confidence in the answer. Used literally, confident rejections look like near-certain detections.
- **Severity:** medium for anything that thresholds the score.
- **Workaround:** let `match` fix the direction and read inconsistent pairs as confidence in the answer; raw answers stay cached unchanged.
- **Suggestion (prompting):** ask for a categorical scale ("certainly not" to "certainly yes") or log-odds instead of a bare probability next to a boolean.

---

## Strands Agents SDK (1.61)

### STR-1 The whole conversation is re-sent on every tool call; no prompt-cache switch
<!-- orig: D-6, GR-7 -->
- **Task:** a rule-synthesis agent with tools `typecheck`, `solve_sketch`, `evaluate`, `fetch_counterexamples`, `submit_sketches` on the strong model.
- **Actual:** a 6-clip task message is about 3k tokens and each tool call re-reads it plus the growing history, so cost grows quadratically in tool calls. A 40-clip run was 128k input tokens for 2.5k output (about $0.28); one synthesis run in another test used 105,814 input and 2,350 output tokens ($0.235 at strong-model prices). `BedrockModel` in 1.61 exposes no `cachePoint` switch that we could rely on.
- **Severity:** medium (cost).
- **Workaround:** the system prompt tells the model to try at most 2-3 sketches by hand per round, a per-round cap on agent-initiated solves, at most 6 traces of each label in the task message (the solver still uses all), and the orchestrator, not the model, runs the solves for submitted sketches.
- **Suggestion:** expose `cachePoint` on the system prompt and the first user message through `BedrockModel` config, and document the cost model of tool loops.

### STR-2 Writing a fake `Model` for offline tests means reading the source
<!-- orig: D-7 -->
- **Task:** test the agent and tool plumbing without Bedrock.
- **Actual:** a fake model must implement `update_config`, `get_config`, an async-generator `structured_output`, and `stream` yielding raw Converse stream events (`messageStart`, `contentBlockStart` with `toolUse`, `contentBlockDelta` with a JSON-string `input`, `contentBlockStop`, `messageStop`, `metadata`). We found this by reading the source; the package has no mock model.
- **Severity:** low.
- **Suggestion:** ship a scripted `MockModel` or document the event shapes.

### STR-3 Cancelling a run needs two hooks
<!-- orig: D-8 -->
- **Task:** honour a user's cancel during an LLM turn.
- **Actual:** `Agent.cancel()` stops the loop only at the next safe point, and a tool that merely returns "cancelled" does not stop the model from calling more tools.
- **Severity:** low.
- **Workaround:** tools call `Agent.cancel()` when they see the cancel event, and a watcher thread does the same while the model is streaming.
- **Suggestion:** document the cancellation points and a recommended pattern.

---

## AWS Open Data: MEVA on S3 (`mevadata-public-01`)

### S3-1 About 1 MB/s from a US-East-1 public bucket
<!-- orig: G-1 -->
- **Task:** fetch 22 MEVA clips (3.5 GB) from `s3://mevadata-public-01/drops-123-r13/`.
- **Steps:** anonymous boto3 ranged GETs (1 MiB chunks, 3 parallel files), and an 8-thread parallel-range test on one file.
- **Expected:** tens of MB/s.
- **Actual:** about 1.0 MB/s in total, and extra threads did not help (0.7 MB/s with 8 threads competing). 3.3 GB took 48 minutes.
- **Severity:** medium (blocked dataset preparation for most of an hour; nothing to do with our code).
- **Workaround:** start the download first and build the rest while it runs; the downloader is resumable (`.part` files and Range requests).
- **Suggestion:** document the size per clip (140-340 MB here) and publish a small starter-subset manifest, with lower-resolution proxies.

### S3-2 Public annotations contain no theft-like activity; names changed in 2020
<!-- orig: G-3 -->
- **Task:** choose evaluation concepts from the annotated activities.
- **Steps:** counted activity names over all 456 annotated exterior clips in `kitware/` (2018-03-05 to 2018-03-15).
- **Expected:** at least one theft or abandonment style activity for a package story.
- **Actual:** 34 activity names, none of them `person_steals_object` or `person_abandons_package`; `person_picks_up_object` (296) and `person_puts_down_object` (249) are the closest. Old and new names co-exist in the docs (`person_enters_through_structure` versus `person_enters_scene_through_structure`).
- **Severity:** medium.
- **Workaround:** coarse concepts for the benchmark, and the theft story told from separate CC BY footage.
- **Suggestion:** state in the dataset README which activity names are present in the open annotations.

### S3-3 Annotation frames can exceed the video length; indexing base undocumented
<!-- orig: G-4 -->
- **Observation:** a few activities end at frame 9059 in 300 s (9,000-frame) videos, and several videos are slightly longer than 300 s. Frame indexing is 0-based (299 of the 769 annotated clips have an activity starting at frame 0; a 1-based scheme would never produce 0).
- **Severity:** low.
- **Workaround:** instances ending after the measured video duration are skipped and counted.
- **Suggestion:** document the indexing base and that annotations can run past the clip end.

### S3-4 Wide-angle scenes: people 10-40 px tall, fine detail is lost at model resolution
<!-- orig: G-5, B-6 -->
- **Task:** choose one close-up crop per camera, then perceive it with a vision model.
- **Actual:** actions are spread over parking lots, so the union of the actor boxes of all concept activities covers essentially the whole 1920x1080 frame, and people are 10-40 px tall. A full frame at 640 px wide gave two people "on the sidewalk" and one SUV with no `near(person, vehicle)`; a fixed native-resolution crop around the open-door SUV gave `near(p, v1)` in every frame.
- **Severity:** medium for doorbell-style perception benchmarks.
- **Workaround:** the densest fixed 960x540 window per camera, chosen from training videos only.
- **Suggestion (for users of the dataset):** treat it as a stress test of coarse concepts; a real doorbell view needs a different source.

---

## Other tooling

Compact entries for the general-purpose tools we hit problems with.

### OT-1 z3py: building the formula was slower than solving it
<!-- orig: D-1 -->
- **Task:** encode 40 clips x 24 frames of a `then` sketch into a Z3 DAG. **Expected:** construction negligible next to `Optimize.check()` (60-400 ms). **Actual:** 2-8 s of pure Python per solve in `z3.And`/`z3.Or` (about 1 ms per call) and `get_id()`. **Severity:** medium. **Workaround:** build n-ary connectives through the C API (`Z3_mk_and` / `Z3_mk_or` over a ctypes array), fold Python booleans before touching Z3, de-duplicate by `x.ast.value`; 3.5 s became 0.2 s. **Suggestion:** a documented fast path for bulk term construction.

### OT-2 z3 `Optimize`: open bounds return `epsilon` and the model is an arbitrary interior point
<!-- orig: D-2 -->
- **Task:** minimum and maximum of each hole over a feasible set. **Steps:** constraints `0 <= a <= 1, not (a <= 0), a <= 1/2`, `minimize(a)`. **Expected:** the infimum 0 or the value 1/2. **Actual:** `sat`, model `a = 1/2`, and `handle.lower()` is the symbolic term `epsilon`; reading the model silently produced a box that missed a quarter of the feasible region (found by an exhaustive-search property test). **Severity:** medium (silent wrong answer). **Workaround:** read `handle.lower()` / `handle.upper()` and evaluate with `epsilon = 0`; never read the extremum from `model()`. **Suggestion:** document the `epsilon` terms.

### OT-3 z3: the default context is not thread-safe, and `timeout` bounds one `check()` only
<!-- orig: D-4, D-5 -->
- **Task:** run synthesis in a worker thread while another component queries holes; keep "10 s per sketch" honest. **Actual:** the global context is shared and unsynchronised, so concurrent use corrupts state; the `timeout` option bounds `check()` but not term construction or the several `check()` calls of a margin climb (one sketch took 11.7 s end to end with a 10 s timeout). **Severity:** low-medium. **Workaround:** one `z3.Context()` per solve; one deadline for the whole solve with each `check()` getting what is left. **Suggestion:** say both prominently in the z3py guide.

### OT-4 Lark LALR: `not (` is lexed as a predicate name
<!-- orig: C-1, C-2 -->
- **Task:** parse `exists p: Person: not (present(p) or facing_camera(p))`. **Actual:** `UnexpectedToken: Token('LPAR', '(')`, because a priority-2 terminal for "a name followed by `(`" beats the `NOT` keyword in the contextual lexer. Separately, the `expected` set after an LALR reduction is an over-approximation, which gave wrong hints for the LLM feedback loop. **Severity:** medium (LLM sketches often write `not (a or b)`). **Workaround:** a `lexer_callbacks` hook that re-tags `not`, and `interactive_parser.accepts()` for exact expected tokens. **Suggestion:** document keyword-versus-identifier priority in the contextual lexer.

### OT-5 Windows and Git Bash: paths, line endings, time zones, scratch files
<!-- orig: F-7, G-2, C-3, D-10, H-1, E-2 -->
- **Actual:** Git Bash rewrites arguments that start with `/` (`node script.mjs http://host /rule` became `C:/Program Files/Git/rule`; `git sparse-checkout add "/annotation/…"` stored a mangled pattern and silently matched nothing); Python text-mode writes CRLF into LF-normalised repositories; `/tmp` in Git Bash is not the `/tmp` Python sees; `zoneinfo` raises `ZoneInfoNotFoundError` because Windows has no IANA database unless `tzdata` is installed; `import scipy.stats` took 40-77 s on a busy machine with real-time scanning on. **Severity:** low-medium. **Workaround:** `MSYS_NO_PATHCONV=1`, `open(p, "w", encoding="utf-8", newline="\n")`, fixed Windows scratch paths, a built-in DST implementation, and `scipy.special.betaincinv` instead of `scipy.stats`. **Suggestion:** cone-mode examples in dataset READMEs; make `tzdata` a hard dependency of cross-platform packages.

### OT-6 SQLite `INSERT OR IGNORE` also ignores CHECK and NOT NULL violations
<!-- orig: H-4 -->
- **Task:** deduplicate webhook deliveries and events. **Actual:** `INSERT OR IGNORE INTO events (source) VALUES ('cctv')` reports success with zero rows, so a bad `source` looks like a duplicate event. **Severity:** low. **Workaround:** `INSERT … ON CONFLICT(<pk>) DO NOTHING`, which still raises on CHECK and FK errors (tested).

### OT-7 Starlette `TestClient` cannot observe an open SSE stream; sse-starlette's keep-alive is a comment; FastAPI 0.143 hides included routes
<!-- orig: H-5, H-6, H-7 -->
- **Actual:** `TestClient.stream(...)` runs the app to completion before returning the first byte, so a live stream hangs the test; `EventSourceResponse(ping=15)` sends `: ping - <timestamp>` comment lines, which `EventSource` listeners never see (our API contract promises `event: ping`); `app.routes` holds opaque `_IncludedRouter` objects without `.path`. **Severity:** low. **Workaround:** run the app on a real uvicorn server in a thread for live-stream tests; `ping_message_factory` returning `ServerSentEvent(event="ping", data="{}")`; compare `app.openapi()["paths"]` with the contract. **Suggestion:** mention `ping_message_factory` next to the `ping` parameter.

### OT-8 imageio-ffmpeg `count_frames_and_secs` decodes the whole file
<!-- orig: B-5 -->
- **Actual:** 4.2 s for a 102 s 1080p clip (it runs `ffmpeg -i f -vf null -f null -`); parsing the `Duration:` line of `ffmpeg -i f` takes about 50 ms and gives the same value. **Severity:** low. **Workaround:** parse the header, fall back to the full count only when the container reports no duration. **Suggestion:** document the cost or add a header-only probe.

### OT-9 Frontend tooling: stray `.sr-only` text widened phones, axe-core "label in name", Next dev compile time
<!-- orig: F-6, F-8, F-7 -->
- **Actual:** absolutely positioned screen-reader text inside an `overflow-x:auto` wrapper escaped the clip and gave a 761 px scroll width at 390 px (flaky, only after data loaded); axe-core 4.x flagged a thumbnail button named "View details: …" that also contained the clip duration ("22 s") as a WCAG 2.5.3 label-in-name mismatch; the first `next dev` compile after an edit took 30-50 s, which made `networkidle` waits flaky. **Severity:** low. **Workaround:** `relative` on every scroll container holding visually hidden text and a screenshot check that fails on horizontal overflow; keep visible text out of the labelled button; run screenshot scripts against `next start`.

### OT-10 Float arithmetic in the conformal rank
<!-- orig: E-spec-1 -->
- **Task:** compute `k = ceil((n+1)(1-alpha))` for the false-alarm threshold. **Actual:** `150 * (1 - 0.18)` is `123.00000000000001`, so `math.ceil` gives 124 instead of 123 (alpha 0.18, n 149); 288 such (alpha, n) pairs exist for alpha in 0.01..0.99 and n < 500. **Severity:** medium (an off-by-one rank changes the guarantee). **Workaround:** exact `Fraction(repr(alpha))` arithmetic, tested against a 100,000-draw simulation. **Suggestion:** conformal-prediction tutorials that show `np.ceil((n+1)*(1-alpha))` should warn about this.
