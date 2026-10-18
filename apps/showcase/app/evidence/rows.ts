// The verification table. Every row names its claim ids (rendered verbatim from the published claims), how it was
// measured, the command (from the repository README, "Tests and verification") and the source files.
// Paths are repo-relative and are checked against the repository by components/evidence/paths.test.ts.

export type VerificationRow = {
  id: string
  title: string
  /** Claim ids shown as the row's numbers, in order. Empty when the row has no published number. */
  claims: string[]
  /** One sentence: what the check establishes. */
  establishes: string
  /** How it was measured, a short paragraph each. */
  how: string[]
  /** Commands, run from the repository root unless a line starts with `cd`. */
  commands: string[]
  /** What the command costs to run. */
  runtime?: string
  /** Source files, with a few words on what each holds. */
  files: { path: string; what: string }[]
  /** Extra claim ids shown as small supporting figures. */
  also?: string[]
}

export const README_TESTS_ANCHOR = 'tests-and-verification'

export const ROWS: VerificationRow[] = [
  {
    id: 'encoding',
    title: 'The Z3 encoding agrees with two other ways of computing the answer',
    claims: ['verify.encoding_cases'],
    also: ['verify.encoding_total_dev', 'verify.encoding_split'],
    establishes:
      'Randomly generated rule sketches and traces give the same answer from the Z3 encoding, from a separate evaluator and from a brute-force search.',
    how: [
      'Hypothesis generates sketches, traces and labelled examples. One comparison checks the Z3 encoding against the NumPy evaluator; another checks the solver against an exhaustive search over the same instance.',
      'A third, literal reference implementation of the semantics checks the vectorised evaluator bit for bit.',
      'The command below runs the deep configuration, ten times the default number of cases (about 5 to 7 minutes).',
    ],
    commands: [
      'SYNTH_PROP_SCALE=10 uv run --project engine pytest engine/tests/synth/test_synth_encoding.py engine/tests/synth/test_synth_solve.py',
    ],
    runtime: 'About 5 to 7 minutes',
    files: [
      { path: 'engine/tests/synth/test_synth_encoding.py', what: 'Z3 encoding against the NumPy evaluator' },
      { path: 'engine/tests/synth/test_synth_solve.py', what: 'solver against exhaustive search' },
      { path: 'engine/tests/synth/synth_support.py', what: 'instance generators and the brute-force reference' },
      { path: 'engine/tests/dsl/dsl_reference.py', what: 'the literal reference evaluator' },
    ],
  },
  {
    id: 'planted-bugs',
    title: 'Deliberately planted solver bugs are caught',
    claims: ['verify.planted_bugs'],
    establishes: 'The agreement test above has power: it fails when the encoder is wrong.',
    how: [
      'Each case monkeypatches one realistic bug into the encoder, such as an off-by-one on a window edge, a dropped GE/LE swap or a lost midnight wrap, and checks that the same comparison reports a mismatch.',
      'A control case runs the unmodified encoder through the identical harness and must pass. The streams are derandomised, so the result is the same on every run.',
    ],
    commands: ['uv run --project engine pytest engine/tests/synth/test_synth_mutations.py'],
    runtime: 'About 15 seconds',
    files: [{ path: 'engine/tests/synth/test_synth_mutations.py', what: 'the planted bugs and the control' }],
  },
  {
    id: 'false-alarm-bound',
    title: 'The false-alarm bound holds in simulation',
    claims: ['verify.conformal_draws'],
    establishes:
      'For exchangeable negatives, the chance that a calibrated rule fires on one is at most the chosen level, including when scores tie.',
    how: [
      'Two independent checks. First, an exact enumeration of every calibration outcome of a small discrete distribution with ties everywhere, which must come out at or below the level with no tolerance.',
      'Second, a seeded Monte Carlo simulation: the count of false alarms must not exceed the upper quantile of the matching binomial distribution at 1e-6, so a failure means the bound is violated, not bad luck. A deliberately wrong quantile (k minus 2) fails the same check, which shows the test can fail.',
      'The conformal rank uses exact rational arithmetic, because floating-point rounding of the rank is off by one for some levels.',
    ],
    commands: ['uv run --project engine pytest engine/tests/calibrate/test_calibrate_validity.py'],
    files: [
      { path: 'engine/tests/calibrate/test_calibrate_validity.py', what: 'exact enumeration and the simulation' },
      { path: 'engine/tests/calibrate/test_calibrate_conformal.py', what: 'rank and threshold unit tests' },
      { path: 'engine/exemplar/calibrate/conformal.py', what: 'the implementation under test' },
    ],
  },
  {
    id: 'logic-laws',
    title: 'The rule logic obeys its stated laws',
    claims: [],
    establishes: 'Properties of the rule language hold on generated rules and traces, not just on hand-picked examples.',
    how: [
      'Property tests (Hypothesis) state that the sign of robustness agrees with the boolean result, that negation is an exact duality, and that widening an eventually or then window never decreases robustness.',
      'The semantics are written down operator by operator in docs/DSL.md, and the tests follow that document.',
    ],
    commands: ['uv run --project engine pytest engine/tests/dsl'],
    files: [
      { path: 'engine/tests/dsl/test_dsl_properties.py', what: 'the laws' },
      { path: 'engine/tests/dsl/dsl_strategies.py', what: 'generators for rules and traces' },
      { path: 'docs/DSL.md', what: 'the specified semantics' },
    ],
  },
  {
    id: 'suites',
    title: 'Test suites',
    claims: ['tests.counts'],
    establishes: 'The engine, the evaluation harness and the webhook code each have their own suite.',
    how: [
      'Engine tests cover the rule language, the solver, calibration, the Ring client, the API and the store. Evaluation tests cover the harness and the dataset tooling. Tests that call Bedrock or Ring skip themselves unless credentials are present.',
    ],
    commands: [
      'uv run --project engine pytest engine/tests',
      'uv run --project engine pytest eval/tests',
      'cd apps/web && node --test lib/ring/ring.test.mjs',
    ],
    files: [
      { path: 'engine/tests', what: 'engine suite' },
      { path: 'eval/tests', what: 'evaluation suite' },
      { path: 'apps/web/lib/ring/ring.test.mjs', what: 'webhook and WHEP allow-list tests' },
    ],
  },
  {
    id: 'webhooks',
    title: 'Signed webhooks are verified like production',
    claims: ['tests.webhook_node'],
    establishes:
      'Signed, tampered, re-serialised, unsigned and duplicate payloads are accepted or refused as they should be, in both Python and Node, against the same fixtures.',
    how: [
      'The signature is HMAC-SHA256 over the raw request body, compared in constant time, and deliveries are deduplicated on the request id. The Playground sends no webhooks, so these paths are exercised with signed fixtures and a replay tool.',
    ],
    commands: [
      'cd apps/web && node --test lib/ring/ring.test.mjs',
      'uv run --project engine pytest engine/tests/ring',
    ],
    files: [
      { path: 'apps/web/lib/ring/ring.test.mjs', what: 'Node tests' },
      { path: 'engine/tests/ring/test_webhook.py', what: 'Python tests' },
      { path: 'engine/tests/ring/fixtures', what: 'the shared signed fixtures' },
      { path: 'scripts/send_signed_webhook.py', what: 'replay tool' },
    ],
  },
  {
    id: 'contract',
    title: 'The API contract is enforced against a mock',
    claims: ['contract.api_ops'],
    establishes: 'Every operation of the engine API contract answers with a schema-valid response.',
    how: [
      'The validator boots the mock engine and exercises each operation in the contract, failing on any response or event-stream frame that breaks it. The engine’s own test suite checks that every path and method in the contract is served and schema-valid.',
    ],
    commands: ['cd apps/web && npm run mock:validate'],
    files: [
      { path: 'apps/web/mock/validate.mjs', what: 'the validator' },
      { path: 'engine/exemplar/contracts/api.yaml', what: 'the contract' },
      { path: 'engine/tests/test_contracts.py', what: 'contract checks on the engine side' },
    ],
  },
  {
    id: 'accessibility',
    title: 'Accessibility: automated checks',
    claims: ['a11y.axe'],
    establishes:
      'An axe-core scan of every screen of the Exemplar web app, run against the mock engine, reports no violations. Contrast tokens are checked separately.',
    how: [
      'This is the result of automated checks. Automated scans cover only part of what accessibility needs, so it is not a conformance claim.',
    ],
    commands: [
      'cd apps/web',
      'npm i --prefix mock/.cache/pw playwright-core',
      'npm i --prefix mock/.cache/axe axe-core',
      'npm run dev:mock    # in one terminal; then, in another:',
      'node mock/a11y.mjs',
      'npm run mock:contrast',
    ],
    runtime: 'One-time setup, then a few minutes',
    files: [
      { path: 'apps/web/mock/a11y.mjs', what: 'the axe scan of every screen' },
      { path: 'apps/web/mock/contrast.mjs', what: 'contrast checks on the colour tokens' },
      { path: 'apps/web/mock/keyboard.mjs', what: 'keyboard walkthrough' },
    ],
  },
]
