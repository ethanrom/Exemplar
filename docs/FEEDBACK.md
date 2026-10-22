# Product feedback

Exemplar teaches a Ring camera new detectors from a few examples. It reads Ring history and clips through the Ring API (developed against the Ring Developer Playground), turns each clip into facts with Claude on Amazon Bedrock, learns a readable rule with a Strands agent plus the Z3 solver, and watches live events. This is our feedback on every tool, API and SDK we used: what we used it for, what worked, what needs work, how onboarding felt, and whether we would build with it again. Dated, step-by-step reproductions of each problem are in [`FRICTION_LOG.md`](FRICTION_LOG.md); entry ids such as RING-4 point there.

**Summary:** the Ring API's combination of event history, event-scoped media download and WHEP live view is the right primitive for event-based AI apps, and the Playground got us to a real end-to-end loop in the first working session. The biggest levers for developers like us are small: a `sub_type` on history events, a clip length in webhooks, a Playground that emits realistic event types, and clearer error bodies. On AWS, Bedrock and Strands made a two-model, tool-calling agent architecture straightforward; the sharp edges are per-model request rules, latency variance, and the cost of agent tool loops without prompt caching.

Contents: [Ring API](#1-ring-api-apiamazonvisioncom) · [Ring Developer Playground](#2-ring-developer-playground) · [ring-api-helloworld sample](#3-ring-api-helloworld-sample-app) · [Ring Appstore MCP docs server](#4-ring-appstore-mcp-docs-server) · [AWS services (detailed)](#5-aws-services-used-in-detail) · [Amazon Bedrock](#6-amazon-bedrock) · [Strands Agents SDK](#7-strands-agents-sdk) · [AWS Open Data: MEVA](#8-aws-open-data-meva-on-s3) · [Other tools](#9-other-tools) · [Feature requests](#10-feature-requests)

---

## 1. Ring API (`api.amazonvision.com`)

**What we used it for.** Everything Exemplar knows about a camera arrives through it, always from the server side (browser calls are blocked by CORS, and the token is a secret):

| API | Use | Code |
|---|---|---|
| `GET /v1/users/me` | prove the token works | `engine/exemplar/ring/client.py` (`verify_connection`) |
| `GET /v1/devices?include=status,capabilities,configurations`, `…/location` | discover the camera, show its state, find its zone | `client.py` (`list_devices`, `device_location`) |
| `GET /v1/history/devices/{id}/events` with `page[key]` cursors and `event_types` | poll for new events and backtest rules over history | `client.py` (`history`, `history_tagged`), `engine/exemplar/api/ingest.py` |
| `POST /v1/devices/{id}/media/video/download` and `…/image/download` (303 to a pre-signed GET) | the clip for perception, the thumbnail for the UI | `client.py` (`download_video`, `download_snapshot`) |
| `POST …/media/streaming/whep/sessions` (and `DELETE`) | live view in the browser, with 2 fps frame capture for a live fact ticker | `apps/web/app/api/ring/stream/route.ts`, `apps/web/app/hooks/useWebRTCStream.ts`, `apps/web/lib/video-processors/frame-grab.ts` |
| Webhooks (`X-Signature` HMAC-SHA256 over the raw body, `meta.request_id`, lifecycle events) | event-driven path next to polling | `apps/web/app/api/ring/webhook/route.ts`, `apps/web/lib/ring/*`, `engine/exemplar/ring/webhook.py` |
| OAuth app mode (authorization code with PKCE, rotating refresh tokens, account linking, `app-integrations`) | the production auth path | `engine/exemplar/ring/tokens.py` (`OAuthApp`) |
| `POST …/media/audio/playback` (early access) | a Chime rule action, behind a flag | `client.py` (`chime_play`) |

**What worked well.**
- *Event-scoped media is the killer feature.* Being able to ask for "the clip for this event" or a snapshot at a timestamp, with no streaming infrastructure on our side, is what made a learn-from-examples product feasible in a hackathon.
- *The documented retry model is accurate.* The 416/425 "recording not ready" guidance, `Retry-After` on 429, and the 303 to a pre-signed URL (fetched without the bearer token) behaved as written; our client implements them and has mocked 416, 425, 200 sequences.
- *The webhook specification is precise.* The signature recipe (key as UTF-8, raw body bytes, hex, `sha256=` prefix) is unambiguous, and the multi-language samples were all we needed to implement it; our signed fixtures check it in both Python and Node. The lifecycle events (`app_integration_added` and `_removed`) are a good design.
- *History plus consent gating* is a sensible privacy model: an app only sees events from after the user's consent.
- *WHEP just worked* in installed Chrome (H.264 High, 1280x720 at 28 fps, first frame in about 5 s).
- Rate limiting, 5xx and the "never retry 406" guidance made it easy to write a client that stays polite.

**What needs work** (details and reproductions in the friction log):
- History events carry no `sub_type`, although webhooks do, so the free "is it a person?" prefilter needs one query per sub-type (RING-1).
- Webhooks carry a start time but no clip length, and a longer-than-event download silently returns the next events' footage with 200 instead of 206 (RING-11, RING-6).
- Errors: opaque 403 for a malformed body (RING-2), a 303 that precedes an undocumented 422 `GRECO_NO_VALID_KEY` (RING-4), empty 401 bodies (RING-8), and a generic 400 for chime playback on a device without chime slots (RING-13).
- `links.next` is described two ways on the same page, and history events carry undocumented `cv_detections` and `riid` fields (RING-7).
- The pre-signed download can block 12-48 s with no progress signal, which defeats default HTTP client timeouts (RING-5).
- Smaller gaps: no time zone in `location` (RING-10), very long event ids (RING-12), the redirect host region (RING-3).

**Onboarding (zero to hello world).** Smooth. With a Playground token and no app registration we had `users/me`, the device list, history and a downloaded clip working in our first session. The developer docs are well organised (one page per API, with request and response samples), and the error-handling page is genuinely useful when it matches reality. What slowed us down was learning by experiment which behaviours are sandbox-specific (see section 2).

**Would we build with it again?** **Yes.** Event-scoped history and media plus a signed-webhook model is exactly what an event-based AI app needs, and nothing else we know of offers it for consumer cameras. The requests above would turn it from "workable" into "pleasant".

---

## 2. Ring Developer Playground

**What we used it for.** The simulated device that every part of our live demo runs on: the token (30 minutes, read-only), the Simulate Package / Vehicle / Motion buttons, the recorded events in history, the media download for the virtual device, and WHEP live view.

**What worked well.**
- Generating a token takes a click, and it works with every read API we needed. No app registration, no OAuth setup, no hardware.
- The virtual device behaves like a real Doorbell Pro in the API (status, capabilities, configurations, location), so the same code paths run later on a real device.
- Simulated events do land in history with downloadable media and snapshots, and the mandatory watermark is rendered into every frame, which kept our UI honest about not covering it.
- Media recorded under earlier tokens stays downloadable, so history accumulates across sessions and backtests have data to work with.

**What needs work.**
- Every simulated event is an `on_demand` history event with no sub-type, listed 27-44 s after it starts, and the `event_types` filter has no effect on them (PG-2, PG-3). Webhooks are not delivered at all, so none of the webhook code can be driven by the Playground.
- The package clip loops about 6 seconds of the "Thief stealing our package" footage and contains no person and no theft (PG-1). Perception-based apps need the full clip, and a delivery clip as its negative.
- The vehicle clip cuts from a lot to a second camera, which makes a single-vehicle story hard to express (PG-7).
- The media consent boundary (the first token's issue time) is not documented (PG-4), and OAuth app mode cannot be exercised at all (PG-5); `status.online` flips without affecting anything (PG-6).
- The Chime early-access feature cannot be tried because the virtual device has no chime slot (RING-13).

**Onboarding.** The fastest part of the whole project: sign in, generate a token, call the API. The 30-minute expiry is fine for development, and we built a countdown and re-paste prompt into the UI.

**Would we build with it again?** **Yes.** It is what makes a no-hardware Ring demo possible. With sub-typed motion events, a webhook, and the full theft clip it would also let developers rehearse their real event paths.

---

## 3. ring-api-helloworld sample app

**What we used it for.** `apps/web` is a fork of `AmazonAppDev/ring-api-helloworld` (MIT, pinned at commit `76100aa`, kept in git history as an unmodified first commit). We kept its WHEP live-view hook and processor plug-in system, and replaced or extended the rest.

**What worked well.** The WHEP hook worked immediately, and the video-processor registry is a good extension point: our 2 fps frame grabber is a processor. The Python scripts (`list_devices.py`, `event_history.py`, and so on) are an excellent way to see each API's real response in under a minute.

**What needs work.**
- The webhook route does not verify the documented HMAC and accepts every POST when its secret is unset (APP-1), and `DELETE /api/ring/stream` forwards the bearer token to any URL the client names (APP-2). Partners will copy this code, so it matters.
- The Stop button covers the mandatory watermark (APP-3), the palette is not WCAG 2.2 AA (APP-4), and there are small build-hygiene issues (APP-5, APP-6).
- The WHEP hook offers audio as `sendrecv`, although the docs require `recvonly` on every m-line; the Playground accepts it anyway, so it fails silently (APP-7).

**Onboarding.** The README's three steps (token, scripts, web app) are accurate and quick.

**Would we build with it again?** **Yes** as a starting point, with the fixes above applied.

---

## 4. Ring Appstore MCP docs server

**What we used it for.** `https://knowledge.appstore-mcp.ring.amazon.dev/mcp` (tools `search_docs` and `get_doc`) was connected to our coding assistant during development, so it could look up endpoint details, error codes and sample code while writing the client.

**What worked well.** Retrieval quality is good: when re-testing it for this write-up, "webhook X-Signature HMAC verification raw body" returned the exact signature recipe with Python, Node and Java samples, and "history events pagination links.next page[key]" returned the whole event-history page. Each result carries its source path and a relevance score, which let the assistant cite the right page. Having the docs inside the coding loop removed most context switching.

**What needs work.**
- Results are whole document chunks (several thousand characters each), and one query returned three near-duplicate copies of the same signature section from different pages; shorter, de-duplicated snippets with a link to the page would use far less context.
- Some answers inherit contradictions from the docs themselves (for example the two descriptions of `links.next` in RING-7); a "last verified" marker or a changelog would help.
- `followUpQuestions` came back empty in our queries.

**Onboarding.** Adding the server was a three-line MCP configuration (an HTTP URL, no authentication step), which is how it should be.

**Would we use it again?** **Yes.** It is the most direct way to keep an AI coding assistant accurate about a young API.

---

## 5. AWS services used, in detail

Exemplar is a multi-service AWS pipeline, not a single model call. Every integration is exercised at runtime by the code listed here.

| Service | Role in Exemplar | Where in the repository |
|---|---|---|
| **Amazon Bedrock, Claude (fast model)** | Perception: 16 sampled frames per clip in one Converse request, answered through forced tool use with a JSON schema (entities, per-frame predicates with confidence, a summary). Output is validated against the ontology and retried once with the error message. | `engine/exemplar/perception/` (`extract.py`, `prompt.py`, `pipeline.py`) |
| **Amazon Bedrock, Claude (strong model)** | (1) The reasoning inside the synthesis agent; (2) escalation: events that land near a rule's decision boundary are re-perceived with up to 32 frames; (3) the zero-shot reference used in our cost comparison. | `engine/exemplar/agent/llm.py`, `engine/exemplar/monitor/`, `eval/baselines/zero_shot.py` |
| **Strands Agents SDK** | A real agent loop that orchestrates counterexample-guided synthesis: it proposes rule sketches (with numeric holes), calls tools to typecheck, solve with Z3, evaluate on a clip and fetch counterexamples, then submits sketches. Strands' `BedrockModel` talks to Bedrock. | `engine/exemplar/agent/` (`cegis.py`, `tools.py`, `llm.py`, `prompts.py`) |
| **Application inference profiles** | Both models are addressed through application inference profile ARNs, read from the environment (`CLAUDE_AWS_MODEL`, `CLAUDE_AWS_FAST_MODEL`), never from code. | `engine/exemplar/settings.py` |
| **AWS Open Data (S3, anonymous)** | MEVA surveillance video and annotations are the evaluation corpus. | `eval/data/s3.py`, `eval/data/download.py` |

**How the two-model split pays off.** Perception runs once per clip on the fast model and is cached as a symbolic trace. After that, teaching, backtesting, active learning, calibration and scoring need no model call at all. Measured on 1,005 clips (16 frames each): **$0.00179 per clip on average, p50 latency 15.6 s, 995 of 1,005 answers schema-valid on the first attempt and all 1,005 valid after at most one retry.** A strong-model call on the same frames is $0.0133, which is why it is reserved for synthesis and for borderline events. In our live Playground run the cost was about $0.0015 per watched event. [`docs/eval/cost_vs_rules.md`](eval/cost_vs_rules.md) plots cost against the number of rules.

**What worked well on AWS.**
- *Converse with tool use* gave reliable structured output: schema-valid on the first attempt for 99% of 1,005 clips, with a retry path that sends the validation error back as a `toolResult` and works against the real model.
- *Strands* turned the synthesis loop into ordinary Python: tools are decorated functions, the agent keeps the conversation across CEGIS rounds, and swapping a scripted proposer in for tests was easy once we knew the `Model` event shapes. On the live Playground, a rule was taught from Playground clips in 15-21 s.
- *Application inference profiles* made it trivial to keep model identity out of code and to swap models per role.
- *Anonymous S3 access* to MEVA meant no credentials were needed for data.

**What needs work on AWS** (see section 6 and 7 for detail): per-model request rules that differ from the documented recipe (BR-1), latency variance and rare multi-minute stalls (BR-3, BR-4), error messages that embed the model id (BR-5), and agent tool loops that re-send the whole conversation each turn (STR-1).

---

## 6. Amazon Bedrock

**What we used it for.** Converse API calls to two Claude models through application inference profiles: fast model for perception, strong model for the agent, escalation and the zero-shot reference (section 5).

**What worked well.**
- Image input in Converse is straightforward, and 16 frames at 640 px in one request gave good scene understanding for both models (the three Playground clips were described correctly: a package with no person, vehicles, and three bird species).
- Forced tool use on the fast model yields clean JSON against a schema.
- The usage block makes cost accounting exact; our budget guard settles every call on real token counts.
- Throughput was sufficient: 5 parallel calls ran side by side for hours, and no `ThrottlingException` surfaced.

**What needs work.**
- The request rules for the new Claude models differ by model and from the documented recipe: `temperature` is rejected; the fast model accepts a forced tool only with thinking disabled; the strong model rejects both forced tool choice and `thinking: disabled` (BR-1). A per-model parameter matrix on the model card, and error messages that name the supported alternative, would save every new user an hour.
- Latency for an identical request varies from 10 s to 64 s and gets worse with concurrency, with no queue-versus-generation breakdown in `metrics` (BR-3); a handful of calls out of 1,530 hung for over 5 minutes with no error (BR-4); and one `ConnectionClosedError` came back after all retries (BR-2). Typed, documented failure modes would make live monitors safer.
- The model id appears in botocore error text (BR-5), which is easy to leak into logs.

**Onboarding.** Fast once credentials and the two inference profile ARNs were in `.env`. The one real detour was the per-model parameter rules, which we learned from error messages.

**Would we build with it again?** **Yes.** One service gave us vision, tool use, structured output and the agent's reasoning, billed per token with exact usage.

---

## 7. Strands Agents SDK

**What we used it for.** The synthesis agent in `engine/exemplar/agent/`. It uses `Agent`, the `@tool` decorator and `BedrockModel` (strands-agents 1.61); tools are `typecheck`, `solve_sketch`, `evaluate`, `fetch_counterexamples` and `submit_sketches`. The orchestrating loop adds counterexample rounds (up to 4), a cap on agent-initiated solves, and cancellation.

**What worked well.** Small surface, readable code, tools as plain Python with docstrings as schemas. The agent kept the whole conversation across rounds, so later rounds saw earlier counterexamples without any prompt plumbing. Region and credentials passed cleanly through a `boto3.Session`.

**What needs work.**
- The conversation is re-sent on every tool call and `BedrockModel` exposes no prompt-cache switch, so tool-heavy agents cost quadratically; one 40-clip run was 128k input tokens for 2.5k output (STR-1). Prompt-cache support and a cost note in the docs would help most.
- No mock model: testing offline meant implementing `Model` from the source (STR-2). Cancellation needs two hooks (STR-3). `structured_output` cannot be used with a model that rejects forced tool choice (BR-1), so a doc note on that combination would help.

**Onboarding.** A one-tool agent on Bedrock came together quickly (our first test ran in about 4 s); the examples are clear.

**Would we build with it again?** **Yes.** It let us ship a genuine agent loop, rather than a prompt chain, in a few days.

---

## 8. AWS Open Data: MEVA on S3

**What we used it for.** Real outdoor surveillance footage with activity annotations (MEVA, Kitware and IARPA, CC BY 4.0) as the evaluation corpus: 22 videos selected from `mevadata-public-01`, cut into 10-20 s windows with fixed per-camera crops. It also provided the footage for measuring perception cost and latency over 1,005 clips.

**What worked well.** Anonymous S3 access works with plain boto3 and no account. The data is licensed clearly, the annotations are in a sparse-clonable Git repository, and the format (KPF YAML) is documented.

**What needs work.** Download speed from a US-East-1 public bucket was about 1 MB/s (S3-1), the open annotations contain no theft-like activity and activity names changed in 2020 (S3-2), annotation frames can exceed the video length (S3-3), and people in the wide-angle views are only 10-40 px tall (S3-4). A starter subset with lower-resolution proxies and a short "what is actually in the open annotations" note would make the dataset much easier to adopt.

**Onboarding.** Finding the bucket through the AWS Open Data registry was easy; understanding the annotation layout and names took the longest.

**Would we use it again?** **Yes**, for evaluation of surveillance and activity-recognition work. It is not a doorbell dataset, and we treated it as such.

---

## 9. Other tools

- **Z3 (`z3-solver` 5.3):** the heart of rule synthesis (MaxSMT with a margin objective). Excellent for exact, explainable answers. Sharp edges we hit and documented: formula construction cost in z3py (OT-1), `epsilon` in optimisation results over open sets (OT-2), no thread safety in the default context (OT-3). Would use again: yes.
- **Next.js 15 and FastAPI:** a good pairing for a server-side-only Ring integration (the browser never sees a token) with SSE for live updates. Small notes in OT-7 and OT-9.

---

## 10. Feature requests

| # | Request | Why it matters to us | Priority |
|---|---|---|---|
| 1 | Include `sub_type` on history events | Gives a free per-event prefilter without one query per sub-type (RING-1) | Important |
| 2 | Include `end` or `duration` in webhook payloads, and clamp video downloads to the event boundary (206) | Needed to fetch exactly one event's clip from a webhook (RING-6, RING-11) | Important |
| 3 | Playground: emit `motion` events with sub-types, apply `event_types`, and deliver webhooks | Lets developers rehearse the real event paths, which is where most integration bugs live (PG-2, PG-3) | Important |
| 4 | Playground: ship the full "thief" clip plus a delivery clip; a vehicle clip with one vehicle entering and leaving | Package-theft and dwell stories are the natural caretaking and business demos (PG-1, PG-7) | Important |
| 5 | Structured error bodies on 401 and 403, and distinct codes for chime-not-supported and token scope | Developers can tell "expired" from "malformed" from "forbidden" (RING-2, RING-8, RING-13) | Important |
| 6 | Sandbox OAuth client for Playground accounts | Lets partners test the production auth path end to end (PG-5) | Nice-to-have |
| 7 | IANA `time_zone` in the device location | Hour-of-day rules ("motion at 3 am") need local time (RING-10) | Nice-to-have |
| 8 | Document `cv_detections` on history events, and expose Ring's own detections where possible | Apps could start from Ring's detections instead of re-deriving them | Nice-to-have |
| 9 | Bedrock: a per-model parameter matrix (`temperature`, `toolChoice`, `thinking`), a queue-time metric and documented behaviour for abandoned requests | Saves integration time and makes live latency predictable (BR-1, BR-3, BR-4) | Important |
| 10 | Strands: prompt-cache controls on `BedrockModel` and a scripted mock model | Agent cost and offline testing (STR-1, STR-2) | Important |
| 11 | MEVA: a starter subset with lower-resolution proxies and a short note on which activities exist in the open annotations | Faster adoption (S3-1, S3-2) | Nice-to-have |
