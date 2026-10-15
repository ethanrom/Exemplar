# Friction notes — Stream A (Ring integration)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion. Items marked (live) were reproduced against the Developer Playground on 2026-10-15; everything else is from building against the docs.

## A-1 `latest_in_range` image download fails on the Playground with an undocumented 422 (live)
- **Task:** fetch "the newest snapshot inside an event window" with `{"type":"latest_in_range","start_timestamp":…,"end_timestamp":…}`.
- **Steps:** `POST …/media/image/download` with `latest_in_range` for the window of a known event (also: without `end_timestamp`, and with a 25-minute window).
- **Expected:** 303, then 200 `image/jpeg` (as `at_timestamp` gives for the same event), or a documented error.
- **Actual:** 303 (the POST looks successful), then the pre-signed GET answers **422** `{"errors":[{"status":"422","code":"GRECO_NO_VALID_KEY","detail":"No valid Greco key available for decryption"}]}`. The docs list 422 only as `CORRUPT_RECORDING`. `at_timestamp` for the same event returns 200.
- **Severity:** medium (a documented search type is unusable on the virtual device and the error gives no hint what a developer can change).
- **Workaround:** use `at_timestamp` with the event `start` (±10 s tolerance). Our client surfaces the failure as `UnprocessableMediaError` with `.code == "GRECO_NO_VALID_KEY"` and does not retry it.
- **Suggestion:** document `GRECO_NO_VALID_KEY` (key-management failure vs. data problem), and make the POST fail instead of 303-ing when the GET cannot succeed.

## A-2 OAuth app mode cannot be exercised with Playground access (design limit)
- **Task:** verify `authorization_code` (+PKCE), refresh-token rotation and `app-integrations` POST/PATCH.
- **Steps:** the Playground only hands out a read-only 30-minute access token; there is no `client_id`/`client_secret`, no refresh token and no account-link redirect.
- **Expected:** some sandbox path (a test client, a fake link flow) to run the real token endpoint.
- **Actual:** nothing to call. `OAuthApp` (exchange, rotating refresh with early refresh, concurrent-refresh guard, nonce check, POST/PATCH completion) is covered by mocked-HTTP tests only; response shapes are taken from the docs (`access_token`, `refresh_token`, `scope`, `expires_in`, `token_type`).
- **Severity:** medium (an entire documented auth path is unverified against the real service).
- **Workaround:** keep it behind the cut-list (code + docs only); the demo uses the Playground token.
- **Suggestion:** a sandbox OAuth client for the Playground account, or a documented test `client_id` so partners can run the token-exchange and rotation end to end.

## A-3 Pre-signed media downloads are slow and block with no progress signal (live)
- **Task:** download a ~20–40 s Playground clip after the 303.
- **Steps:** GET the `Location` URL and time it. Default options: 12–14 s for a 31.7 s clip (1.8 MB), ~4 s for a 40 KB snapshot. With `video_options` (640x360, 5 fps) a 21 s clip took 25.7 s (1.2 MB); a 60 s window took 48.3 s (8.6 MB).
- **Expected:** a quick pre-signed object fetch (the docs describe a plain GET with no auth).
- **Actual:** the GET stays open for tens of seconds while the clip is rendered/watermarked, then returns 200. Default HTTP client timeouts (httpx 5 s read, many SDK defaults 10–30 s) fail with `ReadTimeout`, which looks like a network fault and triggers retries that restart the render.
- **Severity:** low–medium.
- **Workaround:** 180 s read timeout on the media GET only (30 s on JSON calls); `ReadTimeout` is a retried transport error.
- **Suggestion:** document typical latency and recommended timeouts for the download step, or return 202 + `Retry-After` while the file is being produced.

## A-4 Requesting a duration longer than the event returns 200 with the neighbouring events' footage, not 206 (live)
- **Task:** download exactly one event's clip.
- **Steps:** `video/download` with `timestamp = event.start` and `duration = 60000` for a 21.5 s event that is followed ~30 s later by another simulated event.
- **Expected:** `206 Partial Content` with `x-media-duration` ≈ the event length (media_clips.md: "206 … when the full requested duration is not available").
- **Actual:** `200`, `x-media-duration: 59751`: the clip silently continues into the next event(s).
- **Severity:** medium for a perception pipeline (a "package" clip would contain the following "bird feeder" footage).
- **Workaround:** always request `duration = event.end − event.start` (the spike's value; `download_event_video` does this). The returned `x-media-duration` is exposed as `MediaResult.media_duration_ms`.
- **Suggestion:** clamp to the event's recording boundary or document that downloads are continuous-recording windows, not event-scoped.

## A-5 History events carry undocumented fields; `links.next` behaviour is under-specified (live)
- **Task:** page through `GET /v1/history/devices/{id}/events`.
- **Steps:** unfiltered query (6 events in the Playground account); then `page[key]=<iso>` for a made-up cursor.
- **Expected (docs):** `data[].relationships.source` only; `links.next` "includes all original filters plus the pagination cursor" (prose) — but the sample code comment says "re-apply filters since links.next only contains the cursor".
- **Actual:** each event also has `relationships.cv_detections.data` (empty here) and `meta.riid` (null) — neither is documented. The 6-event response has **no `links` key at all**, and a made-up `page[key]` returns `{"data": []}` with no `links`, so cursor following could not be exercised live. The docs also say `links.next` can be present with empty `data`.
- **Severity:** low (we ignore unknown fields) / medium (the pagination contract is ambiguous).
- **Workaround:** the client follows `links.next` verbatim, re-adds `event_types` only if the next URL lacks it, and stops on empty `data`, on a page that adds no new ids, at `max_pages`, or (with `since_ms`) when events get older than the cutoff. Covered by mocked pagination tests.
- **Suggestion:** pick one statement about filters in `links.next`; document `cv_detections`/`riid` or drop them from public responses; state the page size.

## A-6 401 responses have an empty body (live)
- **Task:** classify auth failures.
- **Steps:** `GET /v1/users/me` with a garbage bearer, and with no `Authorization` header.
- **Expected:** `{"errors":[{"status":"401","title":"Invalid Client"}]}` (error_handling.md).
- **Actual:** HTTP 401 with a zero-length body for both.
- **Severity:** low.
- **Workaround:** the error mapper treats an empty/non-JSON body as "no code" and relies on the status; `RingAuthError(status=401)` triggers one token refresh when the provider can.
- **Suggestion:** send the documented JSON body, ideally with a `code` that separates "missing", "malformed" and "expired" tokens (the Playground UI's re-paste prompt needs exactly that distinction).

## A-7 `status.online` flips for the Playground device and does not gate anything (live)
- **Observation:** `GET …/status` returned `online: false` at 06:53 UTC (`reported_at` 06:34:31Z) and `online: true` at 08:13 UTC; WHEP, history and media worked in both states. device_discovery docs call `online` "the primary indicator for whether live streaming or commands will work".
- **Severity:** low. **Workaround:** `RingDevice.online` is informational only; nothing in the client or the sync path is gated on it.
- **Suggestion:** pin the virtual device to `online: true`.

## A-8 Brief vs. forked sample: no `/api/ring/token` route in `ring-api-helloworld@76100aa`
- **Observation:** the planning notes ask to harden `GET /api/ring/token`, but that route does not exist at the forked commit; the sample's real leaks were `DELETE /api/ring/stream` (token sent to any client-supplied URL, P0-6) and the static-bearer `!==` webhook route. We added `/api/ring/token` as the paste-token route (GET returns expiry metadata only, never the token).
- **Severity:** informational. **Suggestion:** none for Ring; keep this note so the README's "what we changed in the sample" list is accurate.
