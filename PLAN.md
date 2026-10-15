# Exemplar — Build Plan

Read `PROPOSAL.md` first for the what and why. This file covers how to build it.

**Deadline:** Oct 23 2026, 12:00 PT. Aim to submit by **09:00 PT Oct 23**, leaving a buffer.

**Dev host:** Windows 10, using the Git Bash shell.

## 0. Hard constraints
- **Ring API is server-side only.** The API base is `https://api.amazonvision.com` and browser calls are blocked by CORS. OAuth goes through `https://oauth.ring.com/oauth/token`. Only US devices are supported, and there is no official SDK, so we use plain HTTP.
- **The Developer Playground** is at `developer.amazon.com/ring/console/playground` and is the simulator shown in the demo. Its constraints:
  - one virtual device
  - three canned clips, identical on every run (Phase 0 spike, §5):
    - **package:** a box on snowy steps, ~6 s of source footage looped to 31.7 s. **No person and no theft.**
    - **vehicle:** cars driving through a lot, then a second camera on a driveway (21.5 s)
    - **motion:** birds at a feeder (39.2 s)
  - each simulation is a WHEP live session that is recorded as an **`on_demand`** history event (no `sub_type`)
  - a read-only token that lasts 30 minutes (`ava.v1:read`)
  - no webhook delivery
  - no custom footage (third-party CC BY footage enters through the engine's `upload` source instead, never as a Ring event)
- **Every frame** carries the mandatory Ring watermark: logo top-left, device ID, app name and timestamp top-right.
- **Content policy:**
  - no facial recognition of non-enrolled people
  - no cross-property tracking
  - no life-safety use
  - must meet WCAG 2.2 AA

  Exemplar does no face ID at all.
- **Secrets** live in `.env`, and the variable names are already set:
  - `CLAUDE_AWS_ACCESS_KEY`, `CLAUDE_AWS_SECRET_KEY`, `CLAUDE_AWS_REGION`
  - `CLAUDE_AWS_MODEL` (strong) and `CLAUDE_AWS_FAST_MODEL` (fast), both Bedrock application inference profile ARNs
  - `CLAUDE_AWS_MODEL_ALIAS`
  - `OPENAI_API_KEY`

  Never hard-code model IDs or keys. Add `.env` to `.gitignore` before the first commit.
- **The repo needs to show the following at runtime:**
  - the Ring API being called (imports and entry points, not just README mentions)
  - an OSS license file (MIT)
  - setup and run instructions
- **Attribution:** fork `AmazonAppDev/ring-api-helloworld` (MIT) and keep its license notice. The Playground's package clip is "Thief stealing our package" by frollard (CC BY 4.0), so credit it in the README and video. MEVA is CC BY 4.0, so credit it too.

## 1. Architecture
```
apps/web   (Next.js 15 + TS, forked from ring-api-helloworld @76100aa)
  - Ring auth (Playground token paste + OAuth app mode), WHEP live view, webhook route (HMAC), UI
  - talks to engine via REST + SSE
engine/    (Python 3.11+, FastAPI)  package: exemplar
  ring/        httpx client: devices, history (cursor), clip download (416/425 backoff), snapshot,
               chime playback, webhook verify + dedupe; Playground and OAuth token providers
  perception/  ffmpeg frame sampling; Bedrock Claude structured extraction; content-hash cache
  dsl/         AST, parser, typechecker, deterministic English printer, boolean + robustness evaluators
  synth/       sketch proposal (LLM), Z3 hole solving (MaxSMT + max-margin), MDL ranking
  active/      committee sampling over version space, disagreement query selection
  calibrate/   conformal threshold, recall CI
  monitor/     online scoring, funnel (sub_type prefilter → fast → escalate), actions, witnesses
  agent/       Strands agent = CEGIS orchestrator (tools wrap synth/dsl/eval)
  store/       SQLite: events, clips, traces, labels(+provenance: example|active|random), rules
  api/         FastAPI routes + SSE
eval/      MEVA subset prep, benchmark harness, baselines, plots
docs/      FEEDBACK.md, FRICTION_LOG.md, DSL.md (semantics), DEVPOST.md
```
**Key principle:** perception runs once per clip, and its output (the trace) is cached. Synthesis, backtesting, active learning and calibration all work on traces only, which makes them fast, cheap and repeatable.

## 2. Component specs (where correctness matters)

### 2.1 Perception → trace
1. **Frame sampling.** Sample N ≤ 24 frames uniformly, at least 0.5 s apart. Resize to 640 px wide (MEVA: fixed per-camera ROI crop first, see §3). Keep the exact timestamps as **integer ms** (`Frame.t_ms`; see `docs/DSL.md` for why). ffmpeg comes from `imageio-ffmpeg` (no system install). Cache traces by event/clip id + sampling params + prompt version — **not** by clip bytes, because Ring re-renders the watermark on every download.
2. **Prompting.** Send the frames to `CLAUDE_AWS_FAST_MODEL` in one request. Caption each frame `Frame i (t=…s)`.
   Bedrock parameters for these models (spike 5): **never send `temperature`** (rejected). Fast model: `toolChoice: {tool}` + `thinking: {"type": "disabled"}`. Strong model: forced tool choice is rejected, so use `toolChoice: {auto}` + an explicit "call emit_trace" instruction + `thinking: {"type": "between_tools"}`, then validate and retry.
3. **Output format.** Force JSON by tool-use with a schema. Fields:
   - `entities`: `{id, type ∈ {person, vehicle, package, animal, object}, attrs: [open-vocab labels such as delivery_uniform, hi_vis, hoodie]}`. IDs must stay consistent across frames.
   - `frames[i]`: a list of `{pred, args, conf ∈ {low, med, high}}`. Predicates are asserted per frame.
   - `summary`: one sentence.
4. **Ontology v1.** Every predicate is typed:

   | Predicate | Arguments |
   |---|---|
   | `present` | Entity |
   | `in_zone` | Entity, Zone |
   | `near` | Entity, Entity |
   | `carrying` | Person, Package\|Object |
   | `picks_up` | Person, Package\|Object |
   | `puts_down` | Person, Package\|Object |
   | `rings_bell` | Person |
   | `enters` | Entity, Zone |
   | `leaves` | Entity, Zone |
   | `facing_camera` | Person |
   | `attr` | Entity, Label |

   `Zone ∈ {door, porch, steps, yard, driveway, sidewalk, street, dock}`.
5. **Signal values.** `s_pred(args)(t_i)` is the confidence when the predicate is asserted (low = 0.6, med = 0.8, high = 0.95) and 0.05 when it isn't.
6. **Context signals:**
   - Ring `sub_type` (`human`, `vehicle`, `package_delivery`, `other_motion`)
   - local hour
   - weekday
   - device ID
7. **Validation.** Check the output against the schema and the ontology. If it fails, retry once with the error message, then mark the trace `perception_failed`.
8. **Escalation mode.** Use `CLAUDE_AWS_MODEL` with up to 32 frames, and optionally average 2 self-consistency samples.

### 2.2 DSL and semantics (document fully in `docs/DSL.md`)
```
rule     := 'exists' var ':' Type (',' var ':' Type)* ':' phi  ['when' ctx ('and' ctx)*]
phi      := atom | 'not' phi | phi 'and' phi | phi 'or' phi
          | 'eventually' '[' a ',' b ']' phi | 'always' '[' a ',' b ']' phi
          | phi 'then' '[' a ',' b ']' phi          # ψ occurs within [a,b] s after φ
          | 'holds_for' '>=' d phi                   # φ holds continuously for ≥ d s
atom     := pred '(' args ')'
ctx      := 'hour' 'in' '[' h1 ',' h2 ']' | 'subtype' '=' S | 'device' '=' D
a,b,d,h1,h2 := number | hole '?name'
```

**Quantitative robustness** follows Donzé–Maler, on the discrete sample grid `t_0 … t_{T−1}` with the clamp `C = 0.5`:
- `ρ(atom, t) = s(t) − 0.5`
- `ρ(¬φ) = −ρ(φ)`
- `∧` is min and `∨` is max
- `ρ(eventually[a,b] φ, t)` is the max of `ρ(φ, t')` over `t' ∈ [t+a, t+b]`. An empty window gives `−C`.
- `ρ(always[a,b] φ, t)` is the min of `ρ(φ, t')` over `t' ∈ [t+a, t+b]`. An empty window gives `−C`, a deliberately non-vacuous choice that must be documented.
- `ρ(φ then[a,b] ψ, t)` is the max over `t1 ≥ t` of `min(ρ(φ, t1), max over t2 ∈ [t1+a, t1+b] of ρ(ψ, t2))`.
- `ρ(holds_for ≥ d φ, t)` is the max over `t1 ≥ t` with `t1 + d ≤ t_end` of `min over t2 ∈ [t1, t1+d] of ρ(φ, t2)`.
- `exists` takes the max over type-correct bindings of the clip's entities. Each clip has at most a few entities, so enumerating them is fine.
- Context atoms are crisp (`±C`) and combine with `∧`.

**Clip score:** `score(rule, clip) = max over t of ρ(phi, t)`. The rule matches when `score > 0`.

**Required implementations:**
1. A plain boolean evaluator.
2. A NumPy robustness evaluator.
3. **Property tests** (`hypothesis`), all of which must pass:
   - The sign of robustness agrees with the boolean result whenever `ρ ≠ 0`.
   - `¬` duality holds.
   - Widening an `eventually` window never decreases ρ.
   - Widening an `always` window never increases ρ.
4. **A deterministic English printer** that maps the AST to a sentence. The UI shows this printer's output. An LLM never paraphrases rules.

### 2.3 Synthesis (CEGIS, Z3, MaxSMT, max-margin)
- **Sketch proposal.** The Strands agent, using `CLAUDE_AWS_MODEL`, receives compact text renderings of the positive and negative traces plus an optional NL hint. It returns up to K = 6 sketches in the DSL, with holes for time bounds, durations and hours. Each sketch is typechecked, and rejected sketches go back to the agent with the error.
- **Hole solving (`synth/z3enc.py`).** For one sketch, use the margin variable `m ≥ 0` and the holes `H` (reals in seconds, bounded to `[0, clip_len]`, with `a ≤ b`). Define two predicates recursively, memoised on `(subformula, t)` so Z3 builds a DAG:
  - `GE(φ, t)` means `ρ(φ, t) ≥ m`
  - `LE(φ, t)` means `ρ(φ, t) ≤ −m`

  The cases are:

  | Construct | GE | LE |
  |---|---|---|
  | atom | `c ≥ m` (c is a constant) | `c ≤ −m` |
  | `∧` | both GE | either LE |
  | `∨` | either GE | both LE |
  | `¬φ` | `LE(φ)` | `GE(φ)` |
  | `eventually[a,b]` | OR over t' of (`a ≤ t'−t ≤ b` ∧ GE) | AND over t' of (in window → LE) |
  | `always` | the dual of `eventually` | the dual of `eventually` |

  - `then` and `holds_for` are expanded the same way.
  - `exists` is an OR over bindings for GE and an AND for LE.
  - The top level is an OR over t for GE and an AND over t for LE.
  - Positive example i gets the soft constraint `GE(top)`, and negative example i gets `LE(top)`. The weight is 1, or 3 for user-confirmed labels.
  - **Lexicographic objective (`z3.Optimize`):** first minimise the weight of violated soft constraints, then maximise `m`. Set a 10 s timeout per sketch.
  - **Temporal-slack placement (replaces "prefer tighter windows", decided after spike 6).** With the satisfied set and `m*` fixed, compute each hole's feasible interval `[lo_h, hi_h]` by Z3 min/max (the same box §2.4 uses). Then place each hole: lower window bounds (`a`) take `0` when feasible, otherwise the interval centre; every other hole (`b`, `d`, hours) takes the interval centre. Snap to a 0.5 s grid (integers for hours) and re-verify with the NumPy evaluator (labels agree, ρ ≥ m* − ε). If the point fails, step back along the segment from the Z3 model point towards it until it passes. This keeps rules taught from one clip from matching only that clip's exact timing.
  - **Return:**
    - `sat` or `unsat`
    - the hole values
    - `m`
    - the IDs of violated examples, which are the counterexamples and are surfaced as "perception suspect?"
- **Differential check (mandatory).** Re-evaluate every solved rule with the NumPy evaluator. Labels must agree, and the robustness must be at least `m − ε`. A mismatch is an encoder bug, so fail loudly. Add this check to the tests.
- **CEGIS loop.** The agent gets the counterexample traces back and revises sketches. Stop when K candidates are consistent, or after 4 rounds.
- **Ranking.** `MDL = nodes·log2(|ops|) + 8·#holes + λ·violations`. Sort by MDL ascending, then `m` descending.
- **Performance guard.** Cap traces at T ≤ 24 and the solve set at about 40 labelled clips. If Z3 times out, fall back to a grid search over hole values on 0.5 s steps using the NumPy evaluator.

### 2.4 Active learning
- **Committee.** For each of the top sketches:
  1. Bound the feasible hole box by Z3 min/max per hole, with the soft constraints fixed to their satisfied set.
  2. Rejection-sample 200 points in the box, keeping only those that are consistent under the NumPy evaluator.
  3. If acceptance falls below 5%, use Z3 models with blocking clauses instead. Hit-and-run sampling is a stretch goal.
- **Weights.** Weight each member by `exp(−MDL)`.
- **Query.** For each unlabelled history clip u, compute `p(u)` as the weighted fraction of members that match it. Ask about the clip that minimises `|p − 0.5|`, then the most diverse among near-ties. Show `p` in the UI as "your rules disagree on this one".
- **Provenance.** Store labels with provenance `active`. These labels are used for synthesis only, never for calibration.

### 2.5 Calibration (conformal, honest)
- **Calibration set.** Use only labels with provenance `random`, meaning clips sampled uniformly from history and labelled by the user. The UI offers "label 10 random clips" and bulk-negative.
- **Threshold.** Take the negatives' scores `s_1…s_n`. Set `τ_α` to the k-th smallest, with `k = ⌈(n+1)(1−α)⌉`. Fire only when `score > τ_α`. This guarantees `P(false alarm) ≤ α` for exchangeable negatives.
- **Too few labels.** If `k > n`, show "guarantee needs ≥ ⌈1/α⌉−1 random negatives (have n)" and fire on `score > 0` without the guarantee badge.
- **Recall.** Report recall on the random-labelled positives with a Clopper–Pearson 95% CI.
- **Why the provenance rule matters.** Actively chosen clips are not exchangeable with deployment events, so including them would void the guarantee. Explain this in `docs/DSL.md` and in the video.

### 2.6 Online monitor and funnel
For each new event, from a webhook or by polling history:
1. **Stage 0, free.** If the rule's types make the Ring `sub_type` impossible (for example, the rule needs a person and the event is `vehicle`), drop the event.
2. **Stage 1.** Run fast perception, then compute the score.
3. **Stage 2.** If `|score − τ| ≤ δ`, escalate to strong perception and re-score. δ is set from the calibration-set score spread, defaulting to 0.1.
4. **Fire or drop.**

**On fire:**
- Emit the witness: argmax bindings, the times chosen for each temporal operator, and the margin. Store it and push it over SSE.
- Run the actions:
  - UI notification
  - optional Slack or webhook-out
  - Chime `POST /v1/devices/{id}/media/audio/playback` behind a flag (early access; expect 403 in the Playground and log it in the friction log)

**Cost meter:** track per-stage counts and token spend.

### 2.7 Ring integration details
- **Token providers:**
  - `PlaygroundToken`: read from env or pasted, valid 30 minutes. The UI shows a countdown and a re-paste prompt.
  - `OAuthApp`: token exchange URL, account link URL, refresh rotation. Build it even if the demo only uses the Playground, and document it.
- **History:** follow `page[key]` cursors (stop on empty `data`, `links.next` can still be present) and filter with `event_types=motion.human,motion.vehicle,ding,...`. Playground caveats (spike): simulated events are `on_demand` and appear 27–44 s after `start`, and the `event_types` filter is ignored, so `sub_type` is unknown and stage 0 can't prune them.
- **Transport:** retry transport errors (`RemoteProtocolError` "Server disconnected" was seen while polling), 429 (`Retry-After`), 500 and 503 with backoff. Never retry 406 (IP block).
- **Clip download:**
  - wait until clip end + 5 s;
  - retry 416 and 425 with exponential backoff for about 2 minutes;
  - follow the 303 redirect to the pre-signed URL **without** the bearer token (the host is `download-<region>.prod.phoenix.devices.amazon.dev`).
- **Webhooks (`apps/web/app/api/ring/webhook`):**
  - verify `X-Signature: sha256=<hex>` with HMAC-SHA256 over the **raw body**, using a constant-time comparison;
  - return 200 in under 5 s and enqueue the event to the engine;
  - deduplicate on `meta.request_id`;
  - handle the lifecycle events `app_integration_added` and `app_integration_removed`.

  Test with signed fixture payloads, and add a `scripts/send_signed_webhook` replay tool.
- **Live view:** reuse the sample app's browser WHEP. A frame-grab plugin captures 2 fps from the `<video>` element and posts the frames to the engine for the live trace ticker. This is also the fallback "clip" source if Playground clip download doesn't work for the virtual device.
- **During development:** add the Ring Appstore MCP docs server, `https://knowledge.appstore-mcp.ring.amazon.dev/mcp` (tools `search_docs` and `get_doc`).

### 2.8 UI (WCAG 2.2 AA)
1. **Connect:** token paste with countdown, or OAuth.
2. **Library:** event grid with snapshot thumbnails, filters, label chips (+ / − / ?), bulk-negative, and "label 10 random".
3. **Teach:** selected examples feed a live agent timeline (sketch proposed, Z3 sat or unsat, counterexample). It shows candidate rules (English plus DSL, MDL, margin) and the question card.
4. **Rule:** backtest matches with witness timelines, calibration badge (α, n, τ), recall CI, cost per event, and a Deploy toggle.
5. **Live:** the Playground WHEP view, a live fact ticker, rule monitors lighting up with witnesses, and an action log.
6. **Eval:** MEVA results charts. Use the dataviz skill for these.

## 3. Evaluation (MEVA)
- **Source:** the `mevadata-public-01` S3 bucket (AWS Open Data, CC BY 4.0). Annotations come from `gitlab.kitware.com/meva/meva-data-repo` under `annotation/DIVA-phase-2/MEVA/`.
- **Subset:** take about 15–25 five-minute outdoor videos from `drops-123-r13/` (AVI, H.264, 30 fps, 1920×1080/1072, 140–260 MB each; anonymous S3, us-east-1). Exterior EO cameras: G300, G301, G328, G336, G339, G340, G341, G424, G436, G505, G506, G509, G638, G639 (skip G474–G479, thermal 352×240). Annotations: `annotation/DIVA-phase-2/MEVA/kitware/<date>/<hour>/<clip>.activities.yml` (KPF YAML; `timespan[0].tsr0 = [f0, f1]` in frames). Names were renamed in 2020 — `person_enters_scene_through_structure`, not `person_enters_through_structure`.
- **Phase 0 observations (2018-03-07 hour 11, 24 exterior files):** plenty of `vehicle_stops`/`vehicle_starts` (81 each), `person_enters/exits_scene_through_structure` (134/157), `person_picks_up_object`/`puts_down_object` (51/55), `person_exits_vehicle` (30), `person_unloads_vehicle` (20); **no** `person_steals_object` or `person_abandons_package` in that hour. Activities are 1–10 s long. People are 10–40 px tall in the full frame, so the fast model at 640 px sees "a person near an SUV with open doors" but no hand-object facts.
- **Consequences:** use a **fixed ROI crop per camera** (chosen once per camera view, never per activity, so it stays unbiased) at native resolution, to approximate a doorbell field of view; prefer coarse concepts (vehicle dwell, entering/exiting through a door, getting out of a vehicle, loading/unloading at a vehicle).
- **Concepts:** 3–4 target concepts, each mapped to a pair of activities.
- **Clips:**
  - positives are annotated activity windows with ±random padding, 10–20 s long;
  - negatives are random windows without that activity, including hard negatives (other activities);
  - a train pool, a random calibration split and a test split are separated by video, not by clip, to prevent leakage.
- **Protocol:** k ∈ {1, 3} positive examples plus 0–2 negatives, with an active budget q ∈ {0, 3, 5}, and α = 0.1. Repeat 5 times with random seeds.
- **Baselines:**
  1. **Zero-shot VLM:** `CLAUDE_AWS_MODEL` on the same frames, prompted with the concept's NL description.
  2. **Stretch:** kNN on SigLIP or CLIP clip embeddings from the k examples.
  3. **Stretch:** Amazon Nova with native video input.
- **Metrics:**
  - F1 and precision/recall at τ_α
  - the empirical false-alarm rate against α, which is the validity check
  - model cost per event (tokens)
  - p50 latency
  - the fraction of events escalated
- **Reproducibility:** run with `python -m eval.run --concept <c> --k 3 --q 3 --seeds 5`. Cache all perception results so re-runs are free.
- **Budget:** estimate the token cost during the Phase 0 spikes, using Bedrock pricing, before running the full eval, and cap it. AWS credit codes are gone, so the user pays.

## 4. Build organisation (parallel workstreams)
Parallel Sonnet subagents build the project. Each works on its own branch or worktree and owns a separate set of paths. Dependencies set the order, not dates.

### Phase 0: sequential, one agent, on `main`
- **Repo init:**
  - `.gitignore` covering `.env` and the hackathon txt files
  - MIT `LICENSE`
  - fork the sample into `apps/web`
  - the `engine/` package skeleton
- **Spikes:** see §5.
- **Contracts** in `engine/exemplar/contracts/`, frozen before any branching. Only the integrator changes them.

  | File | Defines |
  |---|---|
  | `trace.py` | the pydantic `Trace`: entities, per-frame facts with confidence, timestamps, context (§2.1) |
  | `dsl_ast.py` | AST node types and the DSL text grammar (§2.2) |
  | `labels.py` | `Label {clip_id, value, provenance ∈ example\|active\|random, weight}` |
  | `api.yaml` | engine REST endpoints and SSE event types, consumed by `apps/web` |
  | `schema.sql` | the SQLite tables |
  | `engine/tests/fixtures/` | about 10 hand-written traces (package theft, delivery, vehicle dwell, empty scene) plus signed webhook payloads |

### Phase 1: parallel, branched from the contracts
| Stream | Owns | Builds | Tests against |
|---|---|---|---|
| A Ring | `engine/exemplar/ring/`, `apps/web/app/api/ring/` | client, token providers, history, clip, snapshot and chime calls, webhook verify and dedupe, live frame-grab plugin | mocked HTTP, signed fixtures, the Playground |
| B Perception | `engine/exemplar/perception/` | ffmpeg sampling, Bedrock extraction to `Trace`, cache, escalation mode | Playground clips, 2 MEVA clips |
| C DSL | `engine/exemplar/dsl/`, `docs/DSL.md` | parser, typechecker, printer, boolean and robustness evaluators, property tests | fixtures |
| F UI | `apps/web/app/(exemplar)/` | all §2.8 screens against a mock engine generated from `api.yaml` | mock server |
| G Eval-data | `eval/data/` | MEVA download, clip cutting, splits by video | MEVA annotations |

### Phase 2: parallel, once C is merged (D and E need its evaluator)
| Stream | Owns | Builds |
|---|---|---|
| D Synthesis | `engine/exemplar/synth/`, `engine/exemplar/agent/` | Z3 encoder, MaxSMT and margin, differential test, MDL, Strands CEGIS agent |
| E Decide | `engine/exemplar/active/`, `calibrate/`, `monitor/` | committee and query selection, conformal threshold and CI, funnel, witnesses, actions |
| H API | `engine/exemplar/api/`, `engine/exemplar/store/` | the FastAPI routes and SSE implementing `api.yaml`, wiring A–E together |
| G Eval-run | `eval/` (excluding `eval/data/`) | harness and baselines once B is merged; charts once D and E are merged |

### Phase 3: integration, one agent
1. Switch the UI from the mock to the real engine.
2. Run the Playground end-to-end test (§6).
3. Run the full eval.
4. Write `README`, `FEEDBACK` and `DEVPOST`.
5. Make the demo video with the demo-video skill.
6. Do the fresh-clone check.
7. Submit.

### Subagent rules
- Stay inside the paths you own. Contract changes go to the integrator, never onto a branch.
- Merge only with your stream's tests green. Run the full `pytest engine/` after every merge.
- Write friction notes to `docs/friction/<stream>.md`, one file per stream so merges don't conflict. Phase 3 combines them into `docs/FRICTION_LOG.md`.

**Cut list, dropped in this order if behind:**
1. AgentCore hosting
2. the Nova and kNN baselines
3. the Chime action
4. hit-and-run sampling
5. OAuth app mode, keeping it as code and docs only
6. the `hour` and `weekday` context atoms

**Never cut:**
- the Playground live flow
- Z3 synthesis with the differential check
- conformal calibration
- the witness explanations
- one MEVA chart

## 5. Spikes (Phase 0)
Do these before branching and record the results in the friction log.

### Results (Phase 0, 2026-10-15) — details in `docs/friction/phase0.md`, scripts in `scripts/spikes/`
| # | Question | Result |
|---|---|---|
| 1 | Devices and history with a Playground token; do simulated events appear? | **Yes.** `users/me`, `devices?include=…` 200 (one "Playground Device": DoorbellPro, AVC 1080p 16:9, full-frame motion zone, CA/US, `audio.customizable_slots: null`). Each Simulate click → one **`on_demand`** event, listed 27–44 s after `start`. `event_types` filters are ignored (every filter returns them). |
| 2 | Video / image download for the virtual device? | **Yes.** POST → 303 → pre-signed GET (no auth) → 200 `video/mp4` / `image/jpeg`, `x-media-origin: recording`, available as soon as the event is listed. Image body `{"type":"at_timestamp","timestamp":<ms>}` (ISO string → 403 "invalid request body"); video body `{"timestamp":<ms>,"duration":<ms>}`. **Auth boundary = the first Playground token's `iat`** (consent); earlier → 403 `TIME_RANGE_NOT_AUTHORIZED`, later → 416/200, and media from earlier tokens stays downloadable, so Playground history persists across tokens. Re-downloads differ byte-wise (watermark re-rendered). **The package clip loops ~6 s of a box on the steps, with no thief.** |
| 3 | WHEP in the forked sample, Chrome | **Yes.** Headless installed Chrome (Playwright): H.264 High `64001f`, 1280×720 @ 28 fps, first frame 4.9 s. The live feed replays the last simulated clip, and a 6 s session still records the full canned clip as `on_demand`. |
| 4 | Chime | Not testable: no chime slots on the device, and the POST returns **400** Validation Error (not 403). Chime stays behind a flag, tested against a mock. |
| 5 | Bedrock, 16 frames → schema JSON | **Yes, valid on the first attempt.** Fast: 10–12 s, ~6.4k in / 1.2–1.7k out ≈ **$0.0014/clip**. Strong (`toolChoice: auto`): 25 s, 6.2k / 1.6k ≈ **$0.028/clip**. Correct on all 3 Playground clips (package with no person; vehicles; woodpecker/junco/cardinal). Eval estimate ≈ $40–60, **cap $75**. Parameter quirks in §2.1. |
| 6 | Z3 toy `then[?a,?b]`, differential check | **Yes.** Solved in 192 ms (sat, m = 0.30), and the NumPy differential check agrees. Needs integer-ms time (float seconds flip window membership at the boundary) and `m ≤ C`. **Open:** the "tighter window" tiebreak returns exactly the observed gap (`[6, 7]` for gaps of 6 and 7 s), so a single example generalises to nothing. Decision pending (see `docs/DSL.md`). |
| 7 | MEVA download, annotations, cutting | **Yes.** Anonymous S3 works, sparse annotation clone works, `meva_cut.py` works. See §3 for names, counts and the small-object problem (→ fixed ROI crops). |
| 8 | Strands agent with one tool on `BedrockModel` + `.env` ARN | **Yes.** strands-agents 1.61, both models call the tool, ~4 s, ~1.1–1.6k tokens. Pass the region via `boto3.Session` (not `region_name` as well). Don't set `temperature`. The fast model invented `rings_doorbell`, so the sketch prompt must list the ontology and the typechecker must reject unknown predicates. |

### Demo design (decided after the spikes)
- **Live on the Playground:** two rules taught from Playground events. "A package has been sitting on the steps for over N s" fires on the package event. "A vehicle enters the lot or driveway" fires on the vehicle event. The bird event fires neither. (`exists` only ranges over entities in the clip, so "nobody around" can't be written as such; the package-only rule expresses it, because a person would add a `picks_up`.)
- **Teach story, the package theft:** windows cut from the full source clip ("Thief stealing our package" by frollard, CC BY 4.0, youtube.com/watch?v=TfTFu8lGrwk; a person arrives ~12 s in, takes the box at ~18–21 s and leaves) through the engine's `upload` source. Theft windows are positives and box-only windows are natural hard negatives, which drives the "should this one count?" question.
- **Quantitative:** the MEVA chart (§3).

## 6. Verification
- **Unit and property tests:** `pytest engine/` covers the DSL property tests, the Z3-vs-NumPy differential test, the conformal threshold arithmetic, webhook HMAC against valid, tampered and duplicate fixtures, and the clip-download retry logic against a mocked 416→425→200 sequence.
- **End-to-end on the Playground:**
  1. Paste the token, and the device list appears.
  2. Trigger the simulated package and vehicle events. Both arrive as `on_demand` events, and their traces appear.
  3. Teach "a package has been sitting on the steps for over N s" from the package event (the vehicle and bird events are negatives), and get a rule.
  4. Answer one active-learning question, then label random clips for calibration.
  5. Deploy. Teach and deploy "a vehicle enters the lot or driveway" the same way.
  6. Trigger the package event again: the package rule fires with a witness, and the vehicle rule is dropped at stage 1.
  7. Trigger the vehicle event: the vehicle rule fires, and the package rule is dropped at stage 1. Stage 0 can't prune, because Playground events carry no `sub_type`. Stage-0 pruning is shown with the signed webhook fixtures through `scripts/send_signed_webhook`.
  8. Upload the frollard clip, teach "package theft" from its windows, and show the backtest and the question card.
- **Eval:** `python -m eval.run ...` reproduces the charts from cached traces.
- **Fresh-clone check:** follow the README on a clean checkout before recording.

## 7. Submission artifacts
Stage-1 judging is pass/fail, so every item below needs to be present:
- `README.md`: what it is, the architecture diagram, setup with Playground token steps, run commands, and attributions.
- `LICENSE`: MIT.
- `docs/FEEDBACK.md`: for every tool used (Ring API, Playground, the ring-api-helloworld sample, the Ring Appstore MCP, Bedrock, Strands, plus MEVA via AWS Open Data), cover what it was used for, what worked, what needs work, onboarding, and whether we'd use it again. Describe the AWS services in detail, which the AWS Builder entry requires.
- `docs/FRICTION_LOG.md`: for each entry, the task, steps, expected vs actual, severity, workaround and suggestion. This earns up to a 10% bonus.
- `docs/DEVPOST.md`: the description text, "Built with", track Ring, mini AWS Builder.
- **Demo video** under 3 minutes, on YouTube, public, in English. No copyrighted music. Attribute the clip.
- **Submit by 09:00 PT Oct 23.** Make the repo public with MIT, or keep it private and add these collaborators at submission time (invitations expire after 7 days): `chris-trag`, `knmeiss`, `giolaq`, `anishamalde`, `mosesroth`, `emersonsklar`, and `testing@devpost.com`.
