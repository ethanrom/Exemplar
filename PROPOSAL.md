# Exemplar — teach your Ring camera new detectors by example

**Hackathon:** Build, Ship, Shape: Amazon Developer Hackathon. Deadline **Fri Oct 23 2026, 12:00 PT**.
**Primary track:** Ring. **Mini challenge:** AWS Builder.

## The problem
A Ring camera understands four fixed things: person, vehicle, package, other motion. People's real questions are more specific:

- "A package was taken by someone who isn't the one who delivered it."
- "A car is idling at my loading dock for more than two minutes."
- "Someone came to the door but didn't ring the bell."

Today, a customer's options for questions like these are:

- **Motion zones:** too blunt to express any of them.
- **Prompting a vision LLM with a sentence:** gives no idea how often it will be wrong until it has already spammed you, can't explain why it fired, and costs a model call on every frame or event.

## The idea
You show Exemplar one to three clips and say "alert me about things like *this*". Exemplar:

1. **Learns a readable rule.** For example: *"a person is on the porch, then picks up a package, then leaves carrying it within 20 s, and was there less than 30 s."* The rule appears in plain English and in a small temporal-logic language.
2. **Asks you exactly one smart question.** It picks the past clip that best splits the rules still consistent with your examples ("Should this one count?"), so each answer halves the remaining doubt.
3. **Proves the rule before it goes live.** It backtests the rule on your event history and shows matches, misses, and a **calibrated false-alarm rate with a statistical guarantee**.
4. **Runs it live** on new Ring events. Each firing comes with a timeline explaining which facts satisfied which part of the rule. Events close to the decision boundary go to a stronger model. Events that clearly match or clearly don't cost almost nothing.

## How it works
```
Ring event (webhook / history / live view)
  → clip download (MP4) → frame sampling (ffmpeg)
  → PERCEPTION: Claude on Amazon Bedrock → per-frame symbolic facts with confidence
       present(p1), in_zone(p1, porch), carrying(p1, k1), picks_up(p1, k1) …
  → TRACE STORE (perception runs once per clip; all logic below re-uses it)

Teach:   examples → LLM proposes rule *sketches* with numeric holes
         → Z3 fills the holes exactly (MaxSMT: tolerates noisy perception, maximises margin)
         → counterexamples fed back (CEGIS loop, orchestrated by a Strands agent)
         → candidates ranked by description length (simplest consistent rule wins)
Ask:     version space of surviving rules → query the clip with maximal disagreement
Prove:   quantitative temporal-logic robustness score per clip
         → conformal calibration on randomly-sampled labels → false-alarm rate ≤ α
Run:     online monitor on new events → fire / escalate / drop → explanation + actions
```

What makes it technically distinctive (and hard to build correctly):

- **Program synthesis, not prompting.** The LLM writes only the rule's structure. An SMT solver (Z3) computes the thresholds that are consistent with every example, or proves that none exist. This is counterexample-guided inductive synthesis (CEGIS), a technique from programming-languages research.
- **Rules that score as well as decide.** In Signal Temporal Logic (STL), a rule doesn't just return yes or no. It returns a real-valued robustness margin saying how strongly it held. That margin drives three things: a max-margin rule choice (an SVM-like idea applied to logic), the escalation band, and calibration.
- **Guarantees that hold up statistically.** The false-alarm threshold is calibrated with conformal prediction, using labels on *randomly* sampled clips. Actively-chosen labels would bias the guarantee, so they are kept for learning only.
- **Explainable by construction.** Every alert includes its witness: the bindings and timestamps that made the rule true. The English rendering comes from a deterministic printer, not from an LLM paraphrase.

**Prior art, stated honestly:** enterprise video platforms (Verkada, Spot AI, Coram) offer natural-language alerts by prompting a vision LLM. Robotics research translates language into temporal logic (nl2spec, Lang2LTL). As far as we know, nothing combines the following on a consumer camera platform:

- learning from examples
- active questioning
- verified backtesting with a false-alarm guarantee
- compiled, explainable monitors

## Ring platform usage
We use a broad slice of the Ring API, because Tech Implementation is scored on how effectively the project uses it:

- **Developer Playground:** the demo simulator, including its simulated package, vehicle and motion events and live view.
- **OAuth:** Playground token mode, plus the full app-integration OAuth flow with refresh-token rotation.
- **Devices:** `GET /v1/devices?include=status,capabilities,configurations`.
- **Event history:** `GET /v1/history/devices/{id}/events`, with cursor pagination and `event_types` filters.
- **Clip download:** `POST /v1/devices/{id}/media/video/download`, with the documented 416/425 retry and backoff.
- **Snapshots:** `POST /v1/devices/{id}/media/image/download`, used for thumbnails.
- **Live view:** WHEP WebRTC through `POST /v1/devices/{id}/media/streaming/whep/sessions`, used for the live trace.
- **Webhooks:**
  - The signature (HMAC-SHA256 `X-Signature`) is verified on the raw request body.
  - We return 200 within 5 s and process asynchronously.
  - Deliveries are deduplicated on `meta.request_id`.
  - Smart-alert `sub_type` acts as a free first filter.
- **Chime audio playback:** used as a rule action (early-access, behind a flag).
- **Ring Appstore MCP docs server:** used during development.

## AWS usage (AWS Builder)
- **Amazon Bedrock (Claude):**
  - the fast model does per-clip perception;
  - the strong model proposes rule sketches and re-checks events near the decision boundary.
- **Strands Agents SDK:** runs the synthesis loop as a real agent. Its tools are typecheck, solve sketch, evaluate, and fetch counterexamples.
- **AWS Open Data (MEVA on S3):** the evaluation corpus.
- **Stretch:** host the agent on Bedrock AgentCore Runtime. Compare against Amazon Nova's native video input as a perception baseline.

## Who it's for
- **Homeowners** with specific questions that Ring's four categories can't express.
- **Small businesses:**
  - loading docks
  - storefronts
  - short-term rentals
  - property managers

  These categories match Ring's own developer docs (business intelligence, home analytics) and the judges' "event-based triggers for app functionality" example.
- **Distribution:** a web app (Ring's preferred partner app type), distributed through the Ring Appstore.

## Evidence we'll show
Every number below was measured; sources are the live run log, the cost ledgers (`data/eval/precompute.jsonl`, `costs.jsonl`) and the test suites.

- **1. Live, on the Ring Playground (the loop).**
  - **Setup:** paste a Playground token, click Simulate, and the engine polls history, downloads each event's clip, runs fast perception and scores the deployed rules.
  - **Two rules taught from Playground clips** by the Strands/Claude agent plus Z3, in 15 to 21 s:
    - package: *"There is a package k such that at every moment within 0 to 19.5 s, k is present"*;
    - vehicle: *"There is a vehicle v such that v is in the driveway"*.
  - **Result:** the package event fires only the package rule (witness: an `always` span from 0.99 to 18.84 s), the vehicle event fires only the vehicle rule, and the bird events fire neither. About $0.0015 per watched event, no escalations.
  - **The teach-by-example moment:** perception once called the box's location "porch" instead of "steps", so the first rule missed. One more labelled example and a 21 s re-teach gave a zone-agnostic rule.
- **2. Teach story on the "Thief stealing our package" footage (CC BY, uploaded through the engine's `upload` source).**
  - The Playground loops only 6 s of this clip, with no thief, so the theft windows come from the full source footage.
  - **Question card:** from a committee of 1,206 consistent rules, the clip they disagree on most is the theft window (p = 0.50). Show the question, the answer, the backtest and the false-alarm guarantee badge.
- **3. Cost scaling** (`docs/eval/cost_vs_rules.svg`). Fast perception costs $0.00179 per event (1,005 clips, p50 15.6 s) and stays flat as rules are added, because every rule is scored on the cached trace (about 0.05 to 0.1 ms, no model call). A strong-model zero-shot call on the same frames costs $0.0133 per rule per event (527 calls), so ten rules cost about 74 times as much.
- **4. Engineering rigor.**
  - About 6,100 randomly generated cases compare the Z3 encoder with an independent NumPy evaluator, with 0 mismatches; 7 of 7 deliberately injected encoder bugs are caught.
  - The conformal false-alarm bound is checked by a 100,000-draw simulation, including heavy ties.
  - More than 840 engine tests, 207 evaluation tests and 22 webhook tests; the API contract is enforced against a mock (33 of 33 operations).
  - An axe-core WCAG 2.2 AA scan of every screen reports 0 violations.
- **Data:** MEVA (CC BY 4.0, AWS Open Data) supplied the footage for the cost and latency measurements. The MEVA accuracy benchmark runs stay in the local evaluation results and are not part of the pitch.

## Demo video (≤ 3 min)
**Proposed plan, to be agreed before recording.** Lead with the Ring Playground working, name the Ring API and the AWS services out loud (not a passing mention), keep the Ring watermark uncovered, attribute the footage on screen, and use only royalty-free music.

| Time | Content |
|---|---|
| 0:00–0:15 | **Problem:** four categories versus specific real-life questions |
| 0:15–0:55 | **Teach on the Playground:** paste the token, click Simulate, label the package event, and watch the agent timeline (sketch, Z3 result, counterexample). The rule appears in plain English in about 20 s, including the "porch" miss and the one-example re-teach |
| 0:55–1:25 | **One good question and the proof:** the frollard theft footage, the question card (committee disagreement, p = 0.50), the backtest and the false-alarm guarantee |
| 1:25–2:05 | **Live:** simulate package, vehicle and bird events. The package event fires only the package rule with its witness timeline, the vehicle event only the vehicle rule, the birds nothing. The cost meter shows about $0.0015 per event |
| 2:05–2:35 | **Under the hood:** facts, sketch, Z3, robustness, conformal; the flat cost-versus-rules chart; the differential-testing and simulation numbers |
| 2:35–2:50 | **Ring API and AWS surface**, with one business example (a vehicle dwelling at a loading dock) |
| 2:50–3:00 | **Close** |

## Risks
| Risk | Mitigation |
|---|---|
| The Playground has one device and three canned clips; the package clip contains no theft | Phase 0 confirmed that history and clip download work (simulated events arrive as `on_demand`). Live rules use what the clips contain. Theft is taught from the CC BY source footage and evaluated on MEVA. Logged in the friction log. |
| Perception noise breaks exact synthesis | MaxSMT soft constraints. A "perception suspect" flag in the UI. Escalation to the strong model. |
| Conformal guarantee needs enough labels | One-click bulk labelling of negatives. The UI states honestly when the guarantee isn't available yet (fewer than ⌈1/α⌉−1 negatives). |
| Scope before the deadline | Parallel workstreams against frozen contracts, and a strict cut list (`PLAN.md` §4) |
