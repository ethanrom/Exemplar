// Split-conformal false-alarm calibration and the recall confidence interval.
//
// Port of engine/exemplar/calibrate/conformal.py (semantics: docs/DSL.md, internal/PLAN.md 2.5):
//   k = ceil((n + 1) * (1 - alpha)), computed with exact rational arithmetic on the decimal the caller wrote;
//   tau_alpha = the k-th smallest of the n random-negative scores; tau = max(tau_alpha, 0); fire iff score > tau;
//   no finite rank (k > n)  ->  tau = 0, no guarantee, message "guarantee needs >= N random negatives (have n)";
//   delta = clamp(IQR / 2, 0.05, 0.2) rounded to 3 places, 0.1 below 8 negatives;
//   recall of `score > tau` on the random positives with a Clopper-Pearson 95% interval.
//
// Pure and deterministic; no imports.

export const DEFAULT_DELTA = 0.1;
export const DELTA_MIN = 0.05;
export const DELTA_MAX = 0.2;
export const DELTA_MIN_N = 8; // fewer negatives than this: the spread is meaningless, use DEFAULT_DELTA

/** api.yaml `Calibration` (+ `tau_alpha`, the raw quantile before the floor at 0). */
export interface Calibration {
  readonly alpha: number;
  readonly n_random_neg: number;
  readonly n_random_pos: number;
  /** ceil((n+1)(1-alpha)); null when k > n (no guarantee). */
  readonly k: number | null;
  /** The decision threshold: fire iff score > tau. */
  readonly tau: number;
  readonly guarantee: boolean;
  readonly message: string | null;
  /** Escalation band half-width. */
  readonly delta: number;
  readonly recall: number | null;
  readonly recall_ci95: readonly [number, number] | null;
  readonly tau_alpha: number | null;
}

// ----------------------------------------------------------------------------- exact rationals

interface Frac {
  readonly p: bigint; // numerator
  readonly q: bigint; // denominator, > 0
}

/**
 * The decimal of a finite double as an exact fraction. Python does `Fraction(repr(alpha))`; JavaScript's
 * `String(x)` yields the same shortest round-trip digits (plain or exponent notation), so parsing it gives the same
 * rational.
 */
export function decimalFraction(x: number): Frac {
  const s = String(x);
  const m = /^(-?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i.exec(s);
  if (m === null) throw new RangeError(`not a finite decimal: ${s}`);
  const [, sign, ip, fp = "", ex = "0"] = m;
  let p = BigInt(ip + fp);
  let e = Number(ex) - fp.length;
  let q = 1n;
  if (e >= 0) p *= 10n ** BigInt(e);
  else q = 10n ** BigInt(-e);
  if (sign === "-") p = -p;
  return { p, q };
}

function ceilDiv(a: bigint, b: bigint): bigint {
  // b > 0
  const d = a / b;
  const r = a % b;
  return r > 0n ? d + 1n : d;
}

function alphaFraction(alpha: number): Frac {
  const a = Number(alpha);
  if (!(Number.isFinite(a) && a > 0 && a < 1)) throw new RangeError(`alpha must be in (0, 1), got ${alpha}`);
  return decimalFraction(a);
}

/** k = ceil((n + 1) * (1 - alpha)), computed exactly. */
export function conformalRank(n: number, alpha: number): number {
  if (!Number.isInteger(n) || n < 0) throw new RangeError("n must be a non-negative integer");
  const { p, q } = alphaFraction(alpha);
  return Number(ceilDiv(BigInt(n + 1) * (q - p), q));
}

/** ceil(1/alpha) - 1: the fewest random negatives for which a threshold with the guarantee exists. */
export function minNegatives(alpha: number): number {
  const { p, q } = alphaFraction(alpha);
  return Number(ceilDiv(q, p)) - 1;
}

// ----------------------------------------------------------------------------- Python / NumPy numerics

/** Python's `round(x, 3)`: the correctly rounded decimal of the exact binary value, ties to even. */
export function pyRound3(x: number): number {
  if (!Number.isFinite(x)) return x;
  const buf = new DataView(new ArrayBuffer(8));
  buf.setFloat64(0, x);
  const hi = buf.getUint32(0);
  const lo = buf.getUint32(4);
  const neg = hi >>> 31 === 1;
  const exp = (hi >>> 20) & 0x7ff;
  const frac = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  const m = exp === 0 ? frac : frac | (1n << 52n);
  const e = exp === 0 ? -1074 : exp - 1075;
  const num = m * 1000n;
  let q: bigint;
  if (e >= 0) {
    q = num << BigInt(e);
  } else {
    const sh = BigInt(-e);
    q = num >> sh;
    const rem = num & ((1n << sh) - 1n);
    const half = 1n << (sh - 1n);
    if (rem > half || (rem === half && (q & 1n) === 1n)) q += 1n;
  }
  const v = Number(q) / 1000; // q < 2^53 for the values used here; a single correctly rounded division
  return neg ? -v : v;
}

/** numpy.percentile(sorted, [25, 75]) with the default 'linear' method, on already-sorted data. */
function percentileLinear(sorted: readonly number[], pct: number): number {
  const n = sorted.length;
  const virtual = (n - 1) * (pct / 100);
  const prev = Math.floor(virtual);
  const next = Math.min(prev + 1, n - 1);
  const gamma = virtual - prev;
  const a = sorted[prev] as number;
  const b = sorted[next] as number;
  // numpy _lerp
  const diff = b - a;
  let r = a + diff * gamma;
  if (gamma >= 0.5) r = b - diff * (1 - gamma);
  return r;
}

/** Half-width of the stage-2 escalation band around tau: clamp(IQR / 2, 0.05, 0.2), rounded to 3 places. */
export function escalationDelta(negScores: readonly number[]): number {
  if (negScores.length < DELTA_MIN_N) return DEFAULT_DELTA;
  const s = [...negScores].map(Number).sort((x, y) => x - y);
  const q1 = percentileLinear(s, 25);
  const q3 = percentileLinear(s, 75);
  return pyRound3(Math.min(Math.max(0.5 * (q3 - q1), DELTA_MIN), DELTA_MAX));
}

// ----------------------------------------------------------------------------- Beta distribution

// ln Gamma (Lanczos, g = 607/128, 15 terms; Numerical Recipes 3rd ed.), accurate to ~1e-15.
const LANCZOS = [
  57.1562356658629235, -59.5979603554754912, 14.1360979747417471, -0.491913816097620199, 0.339946499848118887e-4,
  0.465236289270485756e-4, -0.983744753048795646e-4, 0.158088703224912494e-3, -0.210264441724104883e-3,
  0.217439618115212643e-3, -0.164318106536763890e-3, 0.844182239838527433e-4, -0.261908384015814087e-4,
  0.368991826595316234e-5,
];

function lnGamma(x: number): number {
  let y = x;
  let tmp = x + 5.24218750000000000;
  tmp = (x + 0.5) * Math.log(tmp) - tmp;
  let ser = 0.999999999999997092;
  for (const c of LANCZOS) ser += c / ++y;
  return tmp + Math.log((2.5066282746310005 * ser) / x);
}

/** Continued fraction for the incomplete beta function (modified Lentz). */
function betacf(a: number, b: number, x: number): number {
  const FPMIN = 1e-300;
  const EPS = 1e-16;
  const qab = a + b;
  const qap = a + 1;
  const qam = a - 1;
  let c = 1;
  let d = 1 - (qab * x) / qap;
  if (Math.abs(d) < FPMIN) d = FPMIN;
  d = 1 / d;
  let h = d;
  for (let m = 1; m <= 5000; m++) {
    const m2 = 2 * m;
    let aa = (m * (b - m) * x) / ((qam + m2) * (a + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < FPMIN) d = FPMIN;
    c = 1 + aa / c;
    if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d;
    h *= d * c;
    aa = (-(a + m) * (qab + m) * x) / ((a + m2) * (qap + m2));
    d = 1 + aa * d;
    if (Math.abs(d) < FPMIN) d = FPMIN;
    c = 1 + aa / c;
    if (Math.abs(c) < FPMIN) c = FPMIN;
    d = 1 / d;
    const del = d * c;
    h *= del;
    if (Math.abs(del - 1) < EPS) break;
  }
  return h;
}

/** Regularised incomplete beta function I_x(a, b). */
export function betainc(a: number, b: number, x: number): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const lnBt = lnGamma(a + b) - lnGamma(a) - lnGamma(b) + a * Math.log(x) + b * Math.log1p(-x);
  const bt = Math.exp(lnBt);
  if (x < (a + 1) / (a + b + 2)) return (bt * betacf(a, b, x)) / a;
  return 1 - (bt * betacf(b, a, 1 - x)) / b;
}

/** The x in [0, 1] with I_x(a, b) = p (scipy.special.betaincinv), by bisection to double resolution. */
export function betaincinv(a: number, b: number, p: number): number {
  if (p <= 0) return 0;
  if (p >= 1) return 1;
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    if (mid === lo || mid === hi) break;
    if (betainc(a, b, mid) < p) lo = mid;
    else hi = mid;
  }
  return (lo + hi) / 2;
}

/**
 * Clopper-Pearson interval for x successes in n trials: exact (beta quantiles), within [0, 1], with lower bound 0
 * for no hits and upper bound 1 for all hits.
 */
export function clopperPearson(x: number, n: number, level = 0.95): readonly [number, number] {
  if (!(level > 0 && level < 1)) throw new RangeError(`level must be in (0, 1), got ${level}`);
  const a = 1.0 - level;
  const lo = x === 0 ? 0.0 : betaincinv(x, n - x + 1, a / 2);
  const hi = x === n ? 1.0 : betaincinv(x + 1, n - x, 1 - a / 2);
  return [lo, hi];
}

/**
 * Recall of `score > tau` on random-labelled positives with a Clopper-Pearson interval; `[null, null]` without
 * positives.
 */
export function recallCi(
  posScores: readonly number[],
  tau: number,
  level = 0.95,
): { recall: number | null; ci: readonly [number, number] | null } {
  if (!(level > 0 && level < 1)) throw new RangeError(`level must be in (0, 1), got ${level}`);
  const n = posScores.length;
  if (n === 0) return { recall: null, ci: null };
  let x = 0;
  for (const s of posScores) if (Number(s) > tau) x += 1;
  return { recall: x / n, ci: clopperPearson(x, n, level) };
}

// ----------------------------------------------------------------------------- the threshold

/**
 * tau_alpha from the scores of random negatives. Fire iff `score > tau`. Returns a Calibration with n_random_pos = 0
 * and no recall; `calibrateScores` fills those in.
 */
export function conformalThreshold(negScores: readonly number[], alpha: number): Calibration {
  const scores = negScores.map(Number).sort((x, y) => x - y);
  for (const s of scores) if (!Number.isFinite(s)) throw new RangeError("negative scores must be finite");
  const n = scores.length;
  const k = conformalRank(n, alpha);
  const delta = escalationDelta(scores);
  if (k > n) {
    const need = minNegatives(alpha);
    return {
      alpha: Number(alpha),
      n_random_neg: n,
      n_random_pos: 0,
      k: null,
      tau: 0.0,
      guarantee: false,
      message: `guarantee needs ≥ ${need} random negatives (have ${n})`,
      delta,
      recall: null,
      recall_ci95: null,
      tau_alpha: null,
    };
  }
  const tauAlpha = scores[k - 1] as number;
  return {
    alpha: Number(alpha),
    n_random_neg: n,
    n_random_pos: 0,
    k,
    tau: Math.max(tauAlpha, 0.0) + 0, // + 0: never -0
    guarantee: true,
    message: null,
    delta,
    recall: null,
    recall_ci95: null,
    tau_alpha: tauAlpha,
  };
}

/** Calibration from already-computed robustness scores of random-labelled positives and negatives. */
export function calibrateScores(posScores: readonly number[], negScores: readonly number[], alpha: number): Calibration {
  const cal = conformalThreshold(negScores, alpha);
  const { recall, ci } = recallCi(posScores, cal.tau);
  return { ...cal, n_random_pos: posScores.length, recall, recall_ci95: ci };
}
