// Numbers shown on the Evidence screen (route /eval). They are measurements from our own runs, written down
// here once, with where each one comes from, so the screen never invents or rounds them on its own.
// Update this file when a measurement is repeated; nothing else on the screen holds a hard-coded figure.

export const COST = {
  /**
   * Zero-shot VLM: one strong-model call per rule, per event. USD per call.
   * Measured: 527 calls in the MEVA evaluation, Amazon Bedrock (strong model).
   */
  zeroShotPerRuleUsd: 0.0133,
  zeroShotCalls: 527,
  /**
   * Exemplar: one fast-model perception per event; every rule is then evaluated on the cached trace with no
   * model call, so the cost does not depend on the number of rules. USD per event.
   * Measured: 1,005 clips, Amazon Bedrock (fast model), p50 latency 15.6 s.
   * Excludes the strong-model re-check of borderline events (0 of the live Playground events needed one).
   */
  exemplarPerEventUsd: 0.00179,
  exemplarClips: 1005,
  exemplarP50LatencyS: 15.6,
  /** x axis of the chart: how many rules are deployed. */
  maxRules: 10,
} as const

export interface Verified {
  value: string
  label: string
  detail: string
  /** Shown with a check mark when the claim is "zero problems". */
  clean?: boolean
}

/** Rigor of the synthesis and calibration code. Counts are from the engine's test suites and simulations. */
export const VERIFIED: Verified[] = [
  {
    value: '6,100+',
    label: 'property-test cases',
    detail: 'The Z3 encoder checked against an independent NumPy evaluator: 0 mismatches.',
    clean: true,
  },
  {
    value: '7 of 7',
    label: 'injected bugs caught',
    detail: 'Encoder bugs we planted on purpose; the differential check failed loudly on every one.',
    clean: true,
  },
  {
    value: '100,000',
    label: 'simulated draws',
    detail: 'The conformal false-alarm bound held in simulation, including with heavy ties in the scores.',
    clean: true,
  },
  {
    value: '840+',
    label: 'automated engine tests',
    detail: 'Parsing, evaluation, synthesis, calibration, the monitor and the API contract.',
  },
]

/** One end-to-end run on the Ring Developer Playground: which simulated event fired which rule. */
export interface LiveRun {
  event: string
  /** Rule ids as columns of `RULES`. */
  fired: { package: boolean; vehicle: boolean }
}

export const PLAYGROUND = {
  rules: [
    { key: 'package', name: 'Package rule', taught: 'a package sits on the steps' },
    { key: 'vehicle', name: 'Vehicle rule', taught: 'a vehicle enters the lot or driveway' },
  ] as const,
  runs: [
    { event: 'Simulated package event', fired: { package: true, vehicle: false } },
    { event: 'Simulated vehicle event', fired: { package: false, vehicle: true } },
    { event: 'Simulated bird event', fired: { package: false, vehicle: false } },
  ] as LiveRun[],
  /** Approximate model cost per live event. */
  usdPerEvent: 0.0014,
  /** How long it took to teach the rules, seconds (range over the two rules). */
  taughtInSeconds: [15, 21] as const,
  strongRechecks: 0,
}

/** USD with enough digits to tell $0.00179 from $0.0133 from $0.133. */
export function fmtCost(x: number): string {
  if (x < 0.01) return `$${x.toPrecision(3)}`
  if (x < 0.1) return `$${x.toFixed(4)}`
  return `$${x.toFixed(3)}`
}
