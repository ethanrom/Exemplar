# Friction notes — Phase 0 (spikes)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion.

## P0-1 Media authorization boundary is undocumented (consent = first Playground token)
- **Task:** download a snapshot / clip from the Playground device for an earlier time.
- **Steps:** `POST /v1/devices/{id}/media/image/download` with `{"type":"at_timestamp","timestamp":…}` for times before/after various tokens' `iat`.
- **Expected:** 416 `MEDIA_NOT_FOUND` (nothing recorded) or the media.
- **Actual:** 403 `TIME_RANGE_NOT_AUTHORIZED` for any time before the **first** Playground token we minted today (06:28 UTC); after it, 416 or 200. Media recorded under earlier tokens stays downloadable with later tokens, and history keeps listing those events. (The planning session first read this as "each token's `iat`" — it isn't.)
- **Severity:** medium (cost us a wrong architectural assumption — "ingest on arrival or lose it" — until re-tested).
- **Workaround:** none needed beyond knowing it; backtests over Playground history work across tokens.
- **Suggestion:** document what consent time a Playground token carries (and whether it resets), and return it (e.g. `consented_at`) from `/v1/users/me`.

## P0-2 Image download with an ISO timestamp gives an opaque 403
- **Task:** request a snapshot with `timestamp` as an ISO-8601 string.
- **Expected:** 400 `INVALID_PAYLOAD` naming the bad field (as `error_handling.md` documents for bad bodies).
- **Actual:** 403 `REQUEST_FORBIDDEN` "invalid request body".
- **Severity:** low.
- **Workaround:** send epoch milliseconds.
- **Suggestion:** return 400 with a field pointer; 403 reads as an auth problem and sends developers down the wrong path.

## P0-3 Media 303 points at an ap-northeast-1 host for a US (CA) device
- **Observation:** the pre-signed `Location` is `download-ap-northeast-1.prod.phoenix.devices.amazon.dev` although the device location is CA/US and the docs show `media.api.amazonvision.com`. Works, but surprising for data-residency reviews.
- **Severity:** low (informational).
- **Suggestion:** document which hosts pre-signed media URLs can come from (needed for egress allow-lists).

## P0-4 Chime playback is not testable from the Playground
- **Task:** spike PLAN.md §5 Q4 — `POST /v1/devices/{id}/media/audio/playback`.
- **Steps:** `GET …/configurations` → `audio.customizable_slots: null`; capabilities `audio.supported_actions: null`. POST `{"data":{"type":"audio","attributes":{"audio_ref":"spike-probe"}}}`.
- **Expected:** 403 (read-only `ava.v1:read` token) or a documented "not supported" error.
- **Actual:** 400 `Validation Error` "The request contains invalid input." — no indication whether the device, the token scope, or the `audio_ref` is the problem.
- **Severity:** medium (Early Access feature can't be exercised at all without staging hardware).
- **Workaround:** Chime action stays behind a flag, unit-tested against a mock (cut-list item 3).
- **Suggestion:** give the Playground virtual device a chime slot, or return `CHIME_NOT_SUPPORTED` / scope errors distinctly.

## P0-5 History events carry no `sub_type`
- **Observation (docs, `event_history.md`):** history events expose only `event_type` (`motion` / `on_demand` / `ding`), `start`, `end`. The smart-alert subtype (human/vehicle/other_motion) is only reachable by re-querying with `event_types=motion.human` etc. Webhooks, by contrast, carry `data.subType` — and the Playground has no webhook delivery.
- **Severity:** medium (our stage-0 sub_type prefilter needs one history query per subtype when polling).
- **Workaround:** the poller queries each `motion.<sub>` filter and tags events by which filter returned them.
- **Suggestion:** include `sub_type` in the history event attributes.

## P0-6 Sample app (`ring-api-helloworld`) notes
- Next.js **15.5** (our plan assumed 14) — we stay on 15.
- Webhook route authenticates with a static Bearer token and parses JSON; it does **not** verify the documented `X-Signature` HMAC over the raw body, and compares secrets with `!==` (not constant-time). Stream A replaces it.
- `DELETE /api/ring/stream` forwards the bearer token to any client-supplied `sessionUrl` (SSRF / token leak). We pin it to the `api.amazonvision.com` WHEP prefix.
- `GET /api/ring/token` returns the access token to any caller.
- **Suggestion:** fix these in the sample since partners will copy it.

## P0-7 Playground simulated events: what actually arrives (spike Q1/Q2 answered)
- **Task:** trigger Simulate Package / Vehicle / Motion; poll `GET /v1/history/devices/{id}/events`; download media.
- **Actual:**
  - Each Simulate click opens a WHEP live session (201) and yields one **`on_demand`** history event (not `motion`/`ding`), visible **27–44 s** after its `start`. Durations: package 31.7 s, vehicle 21.5 s, motion 39.2 s.
  - Video and snapshot download both return 200 after the 303 (`x-media-origin: recording`) as soon as the event is listed — no 416/425 seen.
  - `is_third_party_reviewed` is already `true` on first sight (before we fetched any media).
  - Our own app's live-view session (6 s) also produced an `on_demand` event — 39.2 s long, i.e. the whole canned clip, regardless of session length.
  - Re-downloading the same event returns different bytes each time (the watermark's `Generated-At` is re-rendered per download).
- **Severity:** medium. **Workaround:** treat `on_demand` as the Playground's event type; ingest each event once and cache by event id (not by content hash).
- **Suggestion:** emit `motion` events with the matching `motion.<sub>` subtype for simulated events (and a webhook), so apps can exercise their real event paths.

## P0-8 `event_types` filter has no effect on simulated events
- **Steps:** same history call with `event_types` = `ding`, `motion`, `motion.human`, `motion.vehicle`, `motion.other_motion`, `on_demand`, and none.
- **Expected:** only `on_demand` returns the simulated events.
- **Actual:** every filter, including `ding` and `motion.vehicle`, returned the same `on_demand` events.
- **Severity:** medium (can't use the filter for subtype tagging or prefiltering). **Workaround:** none needed for the Playground; stage-0 prefilter falls back to "no subtype".
- **Suggestion:** apply the filter (or document it's ignored in the sandbox).

## P0-9 The Playground's "package theft" clip doesn't contain the theft
- **Observation:** the downloaded 31.7 s package recording loops ~6 s of the source footage (source camera clock cycles 15:57:38→44 repeatedly; 49 unique frames of ~950). A box sits on the steps; no person appears. The Playground's own player shows the same. Fast and strong perception both report "package, no person".
- **Severity:** high for anyone building package-theft demos on the Playground (the clip is attributed as "Thief stealing our package").
- **Workaround:** demo concepts are built around what the clips contain; theft-style concepts are evaluated on MEVA / CC BY footage.
- **Suggestion:** ship the full clip (person arrives, takes the package, leaves), and ideally a delivery clip as its negative.

## P0-10 WHEP from the forked sample works in Chrome (spike Q3)
- Headless installed Chrome via Playwright: H.264 High (`profile-level-id=64001f`), 1280×720 @ 28 fps, first frame 4.9 s after clicking Start. The live feed replays the most recently simulated canned clip (bird feeder after a Motion simulation).
- Location header of the session includes a long `?location=ava1.ring.whep.location…` query — DELETE must use the full URL.

## P0-11 Transient `RemoteProtocolError` from api.amazonvision.com
- History polling every 4 s died after ~8 min on `httpx.RemoteProtocolError: Server disconnected without sending a response`. **Workaround:** retry transport errors with backoff (stream A's client must, not just 5xx/429).

## P0-12 Bedrock: Claude 5.5-class request-parameter changes (AWS)
- `temperature` → ValidationException "`temperature` is deprecated for this model" (both models; Strands' BedrockModel passes it if set).
- Fast model: forced `toolChoice: {tool}` works only with `thinking: {"type": "disabled"}`.
- Strong model: `thinking: disabled` is rejected — "send `{"type": "between_tools"}` instead"; and forced `toolChoice` `tool`/`any` is rejected outright. **Workaround:** `toolChoice: auto` + "call emit_trace" instruction + validate/retry; it complied first try.
- **Severity:** medium (every structured-output recipe in AWS docs uses forced tool choice). **Suggestion:** document per-model support for `toolChoice`, `thinking` and sampling params on the Bedrock model cards, and surface it in Converse error messages consistently.
