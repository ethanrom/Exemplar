# Friction notes — stream B (perception)

Per-stream notes; combined into `docs/FRICTION_LOG.md` in Phase 3. Format per entry: task, steps, expected vs actual, severity, workaround, suggestion. Entries continue the numbering style of `phase0.md` (P0-12 covers the Claude 5.5-class parameter changes; B-3 below is the follow-up).

## B-1 Bedrock Converse: `ConnectionClosedError` after botocore exhausted its retries (fast model, 24 images)
- **Task:** fast-mode perception of a 30 s window, 24 frames (about 10.5k input tokens), following a 32-frame strong call that had just succeeded.
- **Steps:** `bedrock-runtime` `converse` via boto3 with `Config(read_timeout=300, retries={"max_attempts": 4, "mode": "adaptive"})`.
- **Expected:** a response, or a typed `ThrottlingException` / `ServiceUnavailableException` that says what to do.
- **Actual:** `botocore.exceptions.ConnectionClosedError: Connection was closed before we received a valid response from endpoint URL …` on all 4 attempts (about 90 s wasted). The identical request sent again a minute later succeeded. Seen once in about 45 live calls.
- **Severity:** medium (a live monitor sees an unexplained failure with nothing to act on; the call is not idempotent from the caller's point of view, since it may already have been billed).
- **Workaround:** the perception layer wraps botocore errors in `PerceptionBackendError` (with the AWS error code) so callers can retry or fall back; nothing is cached on failure.
- **Suggestion:** return a structured 5xx/throttling error instead of dropping the connection, and document whether input tokens are billed for requests that die like this.

## B-2 Bedrock latency for the same request varies 10 s to 64 s
- **Task:** budget per-event latency for the monitor funnel (PLAN.md §2.6) and the eval p50.
- **Observations (fast model, 16 frames, about 7.9k in / 1.3-2.4k out tokens):** sequential calls 10-37 s; 2 concurrent calls 14-20 s each; 4 concurrent calls 36-64 s each. A 24-frame fast call took 48 s for 1.4k output tokens. Strong model, 24-32 frames: 26-30 s for about 2k output tokens. No `ThrottlingException` was surfaced (botocore's adaptive retry mode may have absorbed throttling silently, so we cannot tell).
- **Expected:** latency roughly proportional to output tokens (the Phase 0 spike measured 10-12 s).
- **Severity:** medium for the live demo and for eval wall-clock time; no effect on correctness.
- **Workaround:** shorter outputs (prompt v2 tells the model that `present(e)` is implied by any other fact about `e`, which cut output tokens by about 40%); samples of one request run concurrently; the eval harness should limit itself to 2 concurrent perception calls and cache every trace.
- **Suggestion:** expose queue time vs generation time in `ConverseMetrics`/`metrics.latencyMs`, and say in the docs when concurrency on an application inference profile is limited.

## B-3 Strong model: forced tool choice rejected, but `auto` + explicit instruction is reliable (follow-up to P0-12)
- **Task:** structured output from the strong model with a tool schema.
- **Steps:** `toolChoice: {"auto": {}}`, `thinking: {"type": "between_tools"}`, final user text "You MUST respond by calling the emit_trace tool exactly once".
- **Actual:** the model called the tool on every one of the 6 live calls (16/24/32 frames, 1 and 2 samples). The validate-and-retry path also works with the real model: the assistant turn (including any reasoning blocks) was resent together with a `toolResult` of status `error`, and the corrected answer came back (live test `test_strong_mode_retry_roundtrip_with_real_model`).
- **Severity:** low now; it was medium at Phase 0.
- **Suggestion:** document `auto` + instruction as the recommended structured-output recipe for models that reject forced choice.

## B-4 botocore errors embed the model id in the message
- **Task:** keep model IDs/ARNs out of logs (project rule).
- **Actual:** `ConnectionClosedError` / `ClientError` messages contain the full endpoint URL, `…/model/<model-id>/converse`, so any code that logs or returns `str(exc)` leaks the id. The fast model id ended up in a terminal traceback during the B-1 incident.
- **Severity:** low.
- **Workaround:** `PerceptionBackendError` replaces the id with `<model>`.
- **Suggestion:** put the model id in the exception attributes, not in the URL text of the message, or document that it is there.

## B-5 `imageio_ffmpeg.count_frames_and_secs` decodes the whole file
- **Task:** get a clip's duration without ffprobe (the plan names `count_frames_and_secs`).
- **Actual:** it runs `ffmpeg -i f -vf null -f null -`, i.e. a full decode: 4.2 s for the 102 s 1080p source clip, 0.4 s for the 16 s MEVA window, 0.2 s for a Playground clip. Parsing the `Duration:` line of `ffmpeg -i f` takes about 50 ms and gives the same value (102.00 s / 31.73 s / 16.00 s).
- **Severity:** low (latency only). **Workaround:** `sampling.probe()` parses the header and falls back to `count_frames_and_secs` only when the container reports no duration (`N/A`).
- **Suggestion:** document the cost, or add a header-only probe to `imageio-ffmpeg`.

## B-6 Wide-angle MEVA frames: the model cannot see hand/vehicle interactions at 640 px
- **Task:** perception of `G339_unloads_280` (1280x720 cut of an MEVA 1080p camera, 16 s).
- **Actual (fast model, prompt v2):** full frame at 640 px wide gave 2 people "on the sidewalk/driveway" and one SUV, no `near(person, vehicle)` at all, and a summary hallucinating "several people". A fixed crop `(0,340,480,270)` around the open-door SUV (native resolution, no upscaling) gave `near(p, v1)` in every frame for two people at the open rear door. This supports the fixed per-camera ROI decision in PLAN.md §3. The crop made the answer about 2x longer (3.9k output tokens), because the model restates the same facts in every frame.
- **Severity:** medium for the MEVA evaluation (concepts must be coarse and crops fixed per camera); no tooling bug.
- **Suggestion (MEVA):** none; this is inherent to the footage.

## B-7 Playground vehicle clip cannot yield a stable "vehicle moves through the lot" fact
- **Observation:** the vehicle clip shows parked cars, a car driving past, then a second camera on a driveway. The model splits it into 5-7 vehicle ids across runs (identity is not recoverable from the 2-5 s gaps between frames), and the ontology has no motion predicate, so movement is visible only as `enters`/`leaves`/`in_zone` changes. Prompt v2 asks for a zone on every vehicle in every frame, which at least yields `in_zone(v, driveway)` over time, but whether a downstream rule such as "a vehicle moves through the lot" can be synthesised from these facts is for streams D/E to find out.
- **Severity:** medium for the demo rule. **Workaround:** none yet. **Suggestion (Ring):** a Playground vehicle clip with one vehicle entering and leaving would be a far better fixture.
