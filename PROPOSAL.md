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
- **Live, on the Ring Playground:**
  1. Teach "a package is on the steps and nobody comes for it" from the simulated package event, then deploy it next to a "vehicle moving through the lot" rule.
  2. A simulated package event fires only the package rule, with its explanation. A vehicle event fires only the vehicle rule. The bird event fires neither.
  3. **The teach story:** package theft, taught from the full CC BY source footage of the Playground's package clip (the Playground loops only its first 6 s, with no thief). The question card asks about a box-only window.
- **Quantitative, on MEVA (CC BY 4.0, real outdoor surveillance, annotated activities):**
  - **Setup:** few-shot learned rules (k = 1 or 3 examples, plus 0–5 active questions) against zero-shot "prompt a vision LLM per event" on the same frames.
  - **Metrics:**
    - F1 at a fixed false-alarm rate
    - whether the measured false-alarm rate actually stays under α
    - model cost per event
    - latency

## Demo video (≤ 3 min)
| Time | Content |
|---|---|
| 0:00–0:20 | **Problem:** four categories versus specific real-life questions |
| 0:20–1:20 | **Teach:** package theft from real porch footage. The rule appears, one question (a box-only window), backtest with the guarantee |
| 1:20–1:50 | **Live on the Playground:** the package event fires the package rule, the vehicle event fires the vehicle rule, birds fire nothing. Explanations, cost meter |
| 1:50–2:25 | **Under the hood:** facts → sketch → Z3 → robustness → conformal; MEVA results chart |
| 2:25–2:50 | **Business example:** a vehicle dwelling at the dock; Ring API and AWS surface |
| 2:50–3:00 | **Close** |

## Risks
| Risk | Mitigation |
|---|---|
| The Playground has one device and three canned clips; the package clip contains no theft | Phase 0 confirmed that history and clip download work (simulated events arrive as `on_demand`). Live rules use what the clips contain. Theft is taught from the CC BY source footage and evaluated on MEVA. Logged in the friction log. |
| Perception noise breaks exact synthesis | MaxSMT soft constraints. A "perception suspect" flag in the UI. Escalation to the strong model. |
| Conformal guarantee needs enough labels | One-click bulk labelling of negatives. The UI states honestly when the guarantee isn't available yet (fewer than ⌈1/α⌉−1 negatives). |
| Scope before the deadline | Parallel workstreams against frozen contracts, and a strict cut list (`PLAN.md` §4) |
