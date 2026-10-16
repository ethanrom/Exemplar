# Devpost submission text

Copy-ready text for the Devpost form. Fields that depend on the final upload are marked `<…>`.

## Project name

**Exemplar**

## Tagline (one line)

Teach your Ring camera new detectors by example: readable rules, a proven false-alarm rate, and an explanation for every alert.

## Track and mini challenge

- **Primary track:** Ring
- **Mini challenge:** AWS Builder
  - **AWS services used and how** (also in the product feedback answer): Amazon Bedrock with two Claude models called through the Converse API via application inference profiles (the fast model reads each clip into symbolic facts with forced tool use; the strong model reasons inside the synthesis agent and re-checks borderline events); the Strands Agents SDK, which runs the counterexample-guided rule-synthesis loop as a real tool-calling agent (`typecheck`, `solve_sketch`, `evaluate`, `fetch_counterexamples`, `submit_sketches`); AWS Open Data (MEVA on S3, anonymous access) for evaluation data. Detail and code pointers: [`FEEDBACK.md`](FEEDBACK.md#5-aws-services-used-in-detail).

## Links

- Code: `<GitHub repository URL>` (MIT license; setup and run instructions in the README)
- Demo video (under 3 minutes): `<YouTube or Vimeo URL>`
- Product feedback: [`docs/FEEDBACK.md`](FEEDBACK.md)
- Friction log (51 entries): [`docs/FRICTION_LOG.md`](FRICTION_LOG.md)

## Description

### Inspiration: the problem

Every household cares about something different. People's real questions are specific:

- "A package was taken by someone who isn't the one who delivered it."
- "A car is idling at my loading dock for more than two minutes."
- "Someone came to the door but didn't ring the bell."

These are questions about what happens over time, not just what appears in a frame. Prompting a vision model with a sentence can sometimes work, but it gives no idea how often it will be wrong until it has already spammed you, it cannot explain why it fired, and it costs a model call for every rule on every event.

### What it does

You show Exemplar one to three clips and say "alert me about things like *this*". Exemplar:

1. **Learns a readable rule.** For example *"There is a vehicle v such that v is in the driveway"*, or *"There is a person p and a package k such that p picks up k, and then within 0 to 20 s p leaves the porch."* The rule is shown in plain English and in a small temporal-logic language, and the English comes from a deterministic printer, not from an LLM paraphrase.
2. **Asks you one good question.** It samples a committee of rules that are all consistent with your examples and asks about the clip they disagree on most ("should this one count?"). In our run the committee had 1,206 members and the question was the theft window of the "Thief stealing our package" footage, at p = 0.50.
3. **Proves the rule before it goes live.** It backtests on your event history, then calibrates the firing threshold with conformal prediction on randomly sampled labels, so the false-alarm rate is at most the alpha you choose, and reports recall with a confidence interval.
4. **Runs it live on Ring.** On the Ring Developer Playground, the engine polls history, downloads each simulated event's clip, perceives it and scores the deployed rules. A package event fired only the package rule (with a witness: the moments and the margin that made it true), a vehicle event fired only the vehicle rule, and the bird events fired neither, at about $0.0015 per watched event. Events near a rule's decision boundary can be re-checked by a stronger model; clear matches and clear misses cost almost nothing.

Teaching is fast and forgiving. From Playground clips the agent and Z3 produced rules in 15 to 21 seconds. When perception called the same box "porch" instead of "steps" and the first rule missed one package event, labelling that one example and re-teaching (21 s) produced a rule that no longer cared about the zone name.

Cost does not grow with the number of rules. Perception runs once per event ($0.00179 on average over 1,005 clips) and each rule is then scored on the cached trace in about 0.05 to 0.1 ms with no model call. Asking a vision model per rule costs $0.0133 per rule per event on the same frames, so ten rules cost about 74 times as much ([chart](eval/cost_vs_rules.md)).

### How we built it

- **Ring.** A Python engine calls the Ring API server-side: devices with `include=status,capabilities,configurations`, event history with cursor pagination and `event_types` filters, event-scoped video and image download (303 to a pre-signed URL, with 416/425 backoff), WHEP live view through a hardened server proxy, signed webhooks (HMAC-SHA256 over the raw body, constant-time compare, `meta.request_id` dedupe, lifecycle events), OAuth app mode with PKCE and refresh rotation, and Chime playback behind a flag. The web app is a Next.js 15 fork of the `ring-api-helloworld` sample with a WCAG 2.2 AA interface.
- **Perception.** Claude (fast model) on Amazon Bedrock reads 16 frames per clip through the Converse API with forced tool use and returns typed entities and per-frame facts with confidence. The result is validated against an ontology and cached as a symbolic trace.
- **Program synthesis, not prompting.** A Strands agent (strong model) proposes rule sketches with numeric holes; Z3 solves the holes exactly as a MaxSMT problem (so noisy perception cannot make a rule impossible) with a max-margin objective; counterexamples go back to the agent (CEGIS); candidates are ranked by description length.
- **Quantitative logic.** Rules are Signal Temporal Logic formulas with a real-valued robustness margin, which drives rule choice, the escalation band and calibration. The semantics are specified operator by operator in [`docs/DSL.md`](DSL.md).
- **Honest statistics.** Calibration uses only randomly sampled labels (actively chosen clips would void the guarantee), exact rational arithmetic for the conformal rank, and recall intervals from Clopper-Pearson.
- **Verification.** The Z3 encoding and the solver are checked on 3,850 randomly generated cases (against an independent NumPy evaluator and an exhaustive search) with no mismatch, and 7 of 7 deliberately planted encoder bugs are caught by that check; the conformal bound is checked by a 100,000-draw simulation including heavy ties; there are more than 840 engine tests, 207 evaluation tests and 22 webhook tests, and the API contract is enforced against a mock (33 of 33 operations).

### Challenges we ran into

- **A sandbox is not a real camera.** Playground events arrive as `on_demand` with no sub-type, 27 to 44 seconds after they start, and the package clip loops six seconds of the source footage with no thief in it. We built the live rules around what the clips contain and told the theft story from the full CC BY source footage uploaded through our own `upload` source.
- **Perception is noisy.** MaxSMT soft constraints, a "perception suspect?" flag, escalation to the strong model, and a cache keyed by event rather than by bytes (Ring re-renders the watermark on every download) keep the system stable.
- **Making the solver fast and correct.** Building Z3 formulas through z3py cost more than solving them, so we construct n-ary connectives through the C API (3.5 s became 0.2 s). Time is integer milliseconds so window edges agree between the solver and the evaluators.
- **New-model quirks on Bedrock.** `temperature` is rejected, and the fast and strong models differ in how they accept forced tool use and thinking settings. We found a reliable recipe for each and wrote them into the friction log.

### Accomplishments that we're proud of

- A full live loop on the Ring Developer Playground: history, clip download, perception, rules, witnesses, and a cost meter.
- Rules learned from a handful of clips in seconds, with a single well-chosen question and a statistical guarantee on false alarms.
- A cost curve that stays flat as rules are added.
- Rigor that goes beyond a demo: differential testing of the solver, property tests of the logic, a simulation of the conformal bound, signed-webhook fixtures, and an accessibility scan with zero violations.
- 51 documented friction-log entries and detailed product feedback on every tool.

### What we learned

Let the LLM write structure and let a solver fit the numbers: it gives exact, explainable answers and keeps model calls to one per event. Spell out the semantics of a logic before building on it; most of our hard bugs were boundary conventions, not code. And a sandbox teaches as much as a device does, provided you log everything it does differently.

### What's next

- Host the synthesis agent on Amazon Bedrock AgentCore Runtime and compare Amazon Nova's native video input as a perception option.
- Richer facts (motion and state changes such as stopping, dwelling and getting out of a vehicle) for business scenes like loading docks and short-term rentals.
- Run on a real Ring device with OAuth app mode, and distribute as a web app through the Ring Appstore.
- Hit-and-run sampling for a larger, better-mixed rule committee.

## Built with

Ring API · Ring Developer Playground · Amazon Bedrock · Claude (Anthropic) · Strands Agents SDK · AWS Open Data (S3, MEVA) · Z3 (`z3-solver`) · Python · FastAPI · NumPy · SciPy · Pydantic · Lark · SQLite · boto3 · httpx · ffmpeg (`imageio-ffmpeg`) · Hypothesis · Next.js · React · TypeScript · Tailwind CSS · WebRTC (WHEP) · Server-Sent Events · Node.js · uv · axe-core

## What was built during the submission period

Exemplar is a new project, started inside the submission period (first commit 2026-10-15). The only pre-existing code is the MIT-licensed `AmazonAppDev/ring-api-helloworld` sample, imported unmodified in its own commit (`76100aa`) and then extended: we replaced its webhook receiver and WHEP session handling with verified, hardened versions, kept its live-view hook and video-processor plug-in system, and added the Exemplar interface, the engine and the evaluation tooling. See [`apps/web/UPSTREAM.md`](../apps/web/UPSTREAM.md).

## Image gallery and media

Suggested uploads: `docs/img/home.png`, `docs/img/teach.png`, `docs/img/rule.png`, `docs/img/live.png`, `docs/img/evidence.png`, and `docs/eval/cost_vs_rules.svg` (export a PNG for Devpost).

## Testing instructions for judges

The README has the full steps. In short: run the engine and the web app, paste a Ring Developer Playground token on the Connect screen, click Simulate in the Playground, and teach and deploy a rule. Running the live loop needs Amazon Bedrock access to two Claude models. Without credentials, `uv run --project engine python -m exemplar.api.seed --fixtures` loads twelve hand-written traces so every screen can be explored without any model call, and the demo video shows the complete loop.

## Attributions

- `apps/web` is derived from **ring-api-helloworld** (MIT, © 2026 Amazon).
- "Thief stealing our package" by **frollard**, <https://www.youtube.com/watch?v=TfTFu8lGrwk>, CC BY 4.0. It is also the source of the Playground's package clip. We cut it into short windows and do not redistribute it.
- **MEVA** (Kitware, Inc. and IARPA), CC BY 4.0, accessed 2026-10-15 from <https://registry.opendata.aws/mevadata>. Corona et al., WACV 2021.
