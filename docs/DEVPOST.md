# Devpost submission text

Copy-ready text for the Devpost form. Fields that depend on the final upload are marked `<…>`.

## Project name

**Exemplar: Teach Your Ring Camera by Example**

## Tagline (one line)

Teach your Ring camera the alerts that matter to you: show a few clips, get a readable rule with a bounded false-alarm rate, and see exactly why every alert fired.

## Track and mini challenge

- **Primary track:** Ring
- **Mini challenge:** AWS Builder
  - **AWS services used and how:**
    - **Amazon Bedrock** runs two Claude models through the Converse API. A fast model reads each Ring clip once into typed, per-frame facts, using forced tool use. A strong model reasons inside the rule-synthesis agent and re-checks events near a rule's decision boundary.
    - **Strands Agents SDK** runs the counterexample-guided synthesis loop as a real tool-calling agent, with the tools `typecheck`, `solve_sketch`, `evaluate`, `fetch_counterexamples` and `submit_sketches`.
    - **AWS Open Data** (the MEVA dataset on S3, anonymous access) supplied outdoor surveillance footage for evaluation.

    Details and code pointers: [`FEEDBACK.md`](FEEDBACK.md#5-aws-services-used-in-detail).

## Links

- Code: https://github.com/ethanrom/Exemplar (MIT license; setup and run instructions in the README)
- Demo video (under 3 minutes): `<YouTube or Vimeo URL>`
- Product feedback: [`docs/FEEDBACK.md`](FEEDBACK.md)
- Friction log (51 entries): [`docs/FRICTION_LOG.md`](FRICTION_LOG.md)

## Description

### Inspiration

It's 2 p.m. and you're at work. A box is on your porch, and your Ring camera has already sent you a motion alert for the courier, another for a neighbour walking a dog, and another for a car going by. What you actually want to know is simpler: *is that package still sitting there an hour later?*

That gap matters at scale. About 63 million parcels are shipped in the US every day ([Pitney Bowes Parcel Shipping Index 2026](https://www.pitneybowes.com/content/dam/pitneybowes/us/en/shipping-index/dmr-5127-parcel-shipping-index-report-2026-ebook.pdf)), and one in four Americans has had a package stolen ([Security.org, 2025](https://www.security.org/package-theft/annual-report/)).

A Ring camera already tells you when it sees a person, a vehicle or motion. But the moments people care about are specific to their home or business, and they unfold over time:

- a delivery that has been sitting on the steps for a while;
- someone picking a package up off the porch;
- a van parked at the loading dock for longer than it should be.

Every household and every shop wants a different detector, and nobody wants to write code or tune thresholds to get one.

We wanted a Ring app where you teach your camera the way you would explain it to a person: show it a few clips, say "like this, not like that", and get back a detector you can read, test and trust.

### What it does

Exemplar is a web app for Ring customers, designed for the Ring Appstore. It needs read-only access, and every Ring API call happens on the server.

1. **You show examples.** Mark a few clips from your Ring history as "yes, like this" or "no". In our demo, a package left on the steps is a yes; someone carrying a box past, a car and birds at a feeder are no.
2. **Exemplar learns a readable rule.** A Strands agent on Amazon Bedrock drafts the shape of the rule and leaves the numbers blank. The Z3 solver fills them in exactly. In our demo the agent's first draft only looked at the steps, so it missed a clip where the box sat on the porch. That clip came back as a counterexample and the agent revised the rule. Z3 then chose the duration, giving *"There is a package k such that (k is on the steps or k is on the porch) continuously for at least 15 s."* This took under 30 seconds. The English is printed from the rule by code, never paraphrased by a model.
3. **It asks you one good question.** When the candidate rules that fit your examples disagree about a clip, Exemplar shows you that clip and asks "Should this one count?".
4. **It tests the rule before it goes live.** It backtests the rule on your history and sets the firing threshold from randomly sampled clips the rule never trained on. For events like these, the chance of a false alarm is then at most the level you choose (10% by default).
5. **It watches live and explains every alert.** One switch deploys the rule. On the Ring Developer Playground, Exemplar polls event history, downloads each new clip, has Claude read it once, and scores every deployed rule.
   - The package event fired only the package rule, along with the moments that made it true.
   - The vehicle event fired only the vehicle rule.
   - The bird events fired neither.
6. **It learns harder things too.** From real porch footage it learned *"a person picks up a package"* from the steps.

**Who it's for:**
- homeowners who want to know when a delivery has been left out or picked up;
- small businesses watching a loading dock, a storefront or a short-term rental;
- property managers with many cameras and many different questions.

**Why it scales:** Claude on Amazon Bedrock reads each event once, for under two-tenths of a cent: $0.0014–$0.0015 per watched event in our live runs, and $0.0018 on average over 1,005 clips. Every rule after that runs on the cached facts in about a tenth of a millisecond, with no model call. Adding a rule therefore adds almost no cost ([chart](eval/cost_vs_rules.md)), and backtesting a new rule against your whole history is free.

### How we built it

- **Ring API, all server-side:**
  - devices (`include=status,capabilities,configurations`);
  - event history with cursor pagination and `event_types` filters;
  - event-scoped video and snapshot download (a 303 redirect to a pre-signed URL, with 416/425 backoff);
  - WHEP live view through a hardened server proxy;
  - signed webhooks: HMAC-SHA256 over the raw body, constant-time compare, `meta.request_id` deduplication, lifecycle events;
  - the OAuth app-integration flow, with PKCE, refresh-token rotation and account linking;
  - Chime playback as an optional rule action, behind a flag.

  The web app is built on Ring's `ring-api-helloworld` sample.
- **Perception on Amazon Bedrock.** The fast Claude model reads 16 frames per clip through the Converse API with forced tool use. It returns typed entities and per-frame facts with a confidence level. These are validated against an ontology and cached as a symbolic trace.
- **Program synthesis with Strands and Z3.**
  - The strong Claude model, inside a Strands agent, proposes rule sketches with numeric holes.
  - Z3 solves the holes as a MaxSMT problem, so a few noisy examples can't make a rule impossible, and maximises the margin.
  - Clips the rule gets wrong go back to the agent as counterexamples (CEGIS). Candidates are ranked by description length, so the simplest consistent rule comes first.
- **Rules that score as well as decide.** Rules are Signal Temporal Logic formulas with a real-valued robustness margin. The margin drives rule choice, calibration and the "Why it fired" explanation. The semantics are specified operator by operator in [`docs/DSL.md`](DSL.md).
- **Sound statistics.**
  - Conformal calibration uses only randomly sampled labels. Answers to Exemplar's questions train the rule but never touch the guarantee.
  - The conformal rank is computed with exact rational arithmetic.
  - Recall comes with Clopper-Pearson intervals.
- **Cross-checked, not just unit-tested.**
  - 3,850 randomized cases in which the Z3 encoding must agree with a separate evaluator and a brute-force search, with zero mismatches (over 6,000 ran during development).
  - 7 of 7 deliberately planted solver bugs caught.
  - A 100,000-draw simulation of the false-alarm bound.
  - 860+ engine tests, 205 evaluation tests and 22 webhook tests.
  - An API contract enforced against a mock (33 of 33 operations).
  - A WCAG 2.2 AA interface with zero axe-core violations.

### Challenges we ran into

- **Building against a sandbox.** Playground events arrive as `on_demand` recordings with no smart-alert sub-type, so Exemplar perceives every event itself instead of relying on sub-types. The Playground's package clip shows a box on the steps. We built the live rule around it, and taught the pickup rule from the full CC BY source footage through Exemplar's upload source.
- **Perception varies from run to run.** The same box was "on the steps" in one read and "on the porch" in the next. MaxSMT soft constraints, counterexamples and a "perception suspect?" flag absorb this, and teach-by-example turns it into one more example rather than a code change.
- **Making the solver fast and exact.** Building Z3 formulas through the Python bindings cost more than solving them. Building connectives through the C API cut that from 3.5 s to 0.2 s. Time is stored in integer milliseconds so that window edges agree exactly between the solver and the evaluators.
- **New model parameters on Bedrock.** `temperature` is rejected, and the fast and strong models accept tool-choice and thinking settings differently. We found a reliable recipe for each model and documented it in the friction log.

### Accomplishments that we're proud of

- The complete loop on the Ring Developer Playground, in one app: teach, test, deploy, and a live alert that explains itself.
- Readable rules learned from a handful of clips in under 30 seconds, with one well-chosen question.
- A statistically sound false-alarm bound, and a cost per event that stays flat as rules are added.
- Engineering rigor beyond a demo: cross-checked synthesis, property-tested logic, a simulated guarantee, signed-webhook fixtures and an accessible interface.
- 51 friction-log entries and detailed product feedback on every Ring and AWS tool we used.

### What we learned

- **Let the LLM write the structure and let a solver choose the numbers.** You get exact, explainable rules and one model call per event.
- **Write down the semantics of a logic before building on it.** Most of our hard bugs were boundary conventions, not code.
- **A sandbox teaches a lot.** Building against the Playground taught us how Ring events, media and webhooks really behave. We logged everything that surprised us so the next developer doesn't hit it.

### What's next

- Ship through the Ring Appstore, using the OAuth app-integration flow on real devices and webhooks for instant events.
- Richer facts for business scenes, such as vehicles stopping and dwelling, or doors opening, so loading docks and storefronts get richer rules.
- More rule actions: Chime playback (already built, behind a flag), outbound webhooks into business systems, and Slack.
- Host the synthesis agent on Amazon Bedrock AgentCore Runtime, and evaluate Amazon Nova's native video input for perception.

### Try it (for judges)

- **No setup, no credentials:** the hosted showcase at `<showcase URL>` is an interactive replay of a real session. Browse the clips, replay the teach run, and open "Why it fired" and the false-alarm guarantee. There's nothing to install or paste.
- **Run it locally, still with no credentials:** follow the README's Quick start, then run `uv run --project engine python -m exemplar.api.seed --fixtures`. Every screen works, including Teach through the offline rule proposer, and all test suites run.
- **Live on the Ring Developer Playground (optional):** with your own Playground token and Amazon Bedrock access, paste the token on the Connect screen, teach and deploy a rule, then click Simulate in the Playground and watch the Live screen. The demo video shows this loop end to end.

## Built with

Ring API · Ring Developer Playground · Amazon Bedrock · Claude (Anthropic) · Strands Agents SDK · AWS Open Data (S3) · Z3 (`z3-solver`) · Python · FastAPI · NumPy · SciPy · Pydantic · Lark · SQLite · boto3 · httpx · ffmpeg · Hypothesis · Next.js · React · TypeScript · Tailwind CSS · WebRTC (WHEP) · Server-Sent Events · Node.js · uv · axe-core

## What was built during the submission period

Exemplar is a new project, started inside the submission period (first commit 2026-10-15). The only pre-existing code is Ring's MIT-licensed `AmazonAppDev/ring-api-helloworld` sample. We imported it unmodified in its own commit (`76100aa`) and then extended it:

- We replaced its webhook receiver and WHEP session handling with verified, hardened versions.
- We kept its live-view hook and video-processor plug-in system.
- We added the Exemplar interface, the engine and the evaluation tooling.

See [`apps/web/UPSTREAM.md`](../apps/web/UPSTREAM.md).

## Image gallery and media

Suggested uploads: the video thumbnail, then `docs/img/home.png`, `docs/img/teach.png`, `docs/img/rule.png`, `docs/img/live.png`, `docs/img/evidence.png`, and `docs/eval/cost_vs_rules.svg` (export a PNG for Devpost).

## Testing instructions for judges

Use the "Try it (for judges)" section at the end of the description. If the form has a separate testing field, paste that section there too.

## Attributions

- `apps/web` is derived from **ring-api-helloworld** (MIT, © 2026 Amazon).
- "Thief stealing our package" by **frollard**, <https://www.youtube.com/watch?v=TfTFu8lGrwk>, CC BY 4.0. It is also the source of the Playground's package clip. We cut it into short windows and do not redistribute it.
- **MEVA** (Kitware, Inc. and IARPA), CC BY 4.0, accessed 2026-10-15 from <https://registry.opendata.aws/mevadata>. Corona et al., WACV 2021.
