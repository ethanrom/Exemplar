# Friction notes — Stream H (API + store)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion. Items marked (live) were reproduced against the Developer Playground on 2026-10-15; the rest come from building against the docs and the other streams.

## H-1 Ring device location has no time zone, and Windows has no tz database
- **Task:** fill `TraceContext.local_hour` / `weekday` at ingest (PLAN.md §2.1.6), which needs the device's local time.
- **Steps:** `GET /v1/devices/{id}/location` -> `{"country": "US", "state": "CA"}` (live). Then `zoneinfo.ZoneInfo("America/Los_Angeles")` on the dev host.
- **Expected:** an IANA zone in the location resource, or at least a usable tz database in Python.
- **Actual:** the location carries only `country` and `state`; and `zoneinfo` raises `ZoneInfoNotFoundError` on Windows because the machine has no IANA data and `tzdata` is not a project dependency.
- **Severity:** low (a silent wrong local hour would have been the real cost: hour-of-day rules would misfire).
- **Workaround:** state -> zone table plus a built-in implementation of the current US DST rules (second Sunday of March to first Sunday of November), tested against the boundary hours. `zoneinfo` is used when it works.
- **Suggestion (Ring):** return `time_zone` (IANA) in the location attributes; devices already know it, and "motion at 3 am" rules need it.

## H-2 Webhook events carry a start timestamp but no clip length
- **Task:** download the clip for a `motion_detected` / `button_press` webhook (PLAN.md §2.7: wait for clip end + 5 s, then fetch).
- **Steps:** read `notifications.md` and the signed fixtures: `data.attributes.timestamp` only.
- **Expected:** an `end` / `duration`, as history events have, so the engine knows when the recording is complete and how long a video to request.
- **Actual:** only the start. `POST .../media/video/download` needs a `duration`, and asking for more than the event length returns the next events' footage (A-4), so the length matters.
- **Severity:** medium for real devices (the Playground sends no webhooks, so it was not hit live).
- **Workaround:** assume a 10 s clip (`ApiConfig.webhook_assumed_clip_s`) and let stream A wait until start + 10 s + 5 s. The history poll later finds the real event; a poll hit within 5 s of a webhook event on the same device is treated as the same event and skipped.
- **Suggestion (Ring):** put `end`/`duration` (or a follow-up `motion_ended` notification) in the webhook, or document the usual recording length.

## H-3 Ring history ids are 140+ characters long and only their tails differ
- **Task:** store a clip per event under `data/clips/` on Windows.
- **Actual:** ids look like `ava1.ring.history.event.OZIXHAV...CBUQJNH`. Used verbatim as file names they get close to MAX_PATH (260) under a deep temp directory, and truncating the front (the obvious fix) makes different events collide because the shared prefix is long.
- **Severity:** low. **Workaround:** `file_stem()` keeps short ids as they are and otherwise uses a sanitized prefix plus a 12-hex SHA-1 of the whole id. **Suggestion (Ring):** document the id length bound, or put the unique part first.

## H-4 `INSERT OR IGNORE` hides schema violations
- **Task:** dedupe webhook deliveries and events with `INSERT OR IGNORE` (the interface sheet's recommendation for `WebhookDeduper.claim`).
- **Actual:** SQLite applies OR IGNORE to CHECK and NOT NULL violations too, so `INSERT OR IGNORE INTO events (source) VALUES ('cctv')` reports success with zero rows. A bad `source` would have looked like "duplicate event".
- **Severity:** low. **Workaround:** `INSERT ... ON CONFLICT(<pk>) DO NOTHING` (same behaviour for duplicate keys, but CHECK and FK errors still raise); covered by a test.

## H-5 Starlette's `TestClient` cannot observe an open SSE stream
- **Task:** test `/runs/{id}/stream` and `/monitor/stream` while the run is still going.
- **Actual:** `TestClient.stream(...)` runs the ASGI app to completion before returning the first byte, so a live stream just hangs the test. Replay tests (finished run) work; follow/live tests do not.
- **Severity:** low (test tooling). **Workaround:** the suite runs the app on a real uvicorn server in a thread for those tests (`make_env(serve=True)`) and reads with `httpx.Client.stream`.

## H-6 sse-starlette's default keep-alive is a comment, not `event: ping`
- **Task:** meet api.yaml: "Every stream sends `event: ping` every 15 s".
- **Actual:** `EventSourceResponse(ping=15)` sends `: ping - <timestamp>` comment lines, which `EventSource` listeners never see. **Workaround:** `ping_message_factory` returning `ServerSentEvent(event="ping", data="{}")`. **Suggestion:** mention the factory next to the `ping` parameter in the docs.

## H-7 FastAPI 0.143 hides included routes from `app.routes`
- **Task:** assert that the app serves every path and method in api.yaml.
- **Actual:** `app.routes` contains opaque `_IncludedRouter` objects without `.path` / `.methods`. **Workaround:** compare `app.openapi()["paths"]` with api.yaml (test `test_zz_contract_coverage` goes further and checks each operation was actually answered and schema-validated).

## H-8 (live) Playground import works end to end, with two caveats worth knowing
- Observed 2026-10-15 with the real token: `PUT /ring/auth` -> `verify_connection` (user "Playground User"), `/ring/devices` (one DoorbellPro with snapshot), `POST /ring/sync` imported the newest 3 events, A downloaded video + snapshot (303 -> pre-signed GET) and B traced all three in about 46 s wall clock with 2 concurrent perception calls and about 24k input / 3k output tokens (estimated at $0.004).
- Caveat 1: events seeded from the recorded spike (same ids as the history) are recognised as known, so connecting after `python -m exemplar.api.seed --playground-spike` does not download or perceive them again.
- Caveat 2: the Playground lists a simulated event 27-44 s after it starts, then the engine downloads (12-25 s) and perceives (10-40 s), so a trigger appears in the Library about 1-2 minutes later. The 15 s poll interval is not the bottleneck; the demo should trigger the events early or show the seeded ones.
