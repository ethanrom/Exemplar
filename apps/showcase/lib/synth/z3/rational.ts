// Exact rational numbers on BigInt: just what the Z3 encoding needs.
//
//   - `fromDouble` + `limitDenominator`: Python's `Fraction(x).limit_denominator(10**9)` (z3enc.py `_rat`), used for the
//     constant window bounds of a sketch;
//   - `parseSexpr`: the numerals Z3 prints (`2.0`, `(/ 1.0 3.0)`, `(+ 2.0 (* (- 1.0) epsilon))`) as exact fractions,
//     with the infinitesimal `epsilon` set to 0, i.e. the closure of the feasible set (solve.py `_closure_value`);
//   - `toNumber`: the correctly rounded double of the fraction, like Python's `float(Fraction)`.
//
// No dependencies; pure.

export class Fraction {
  readonly n: bigint;
  readonly d: bigint;

  constructor(n: bigint, d: bigint = 1n) {
    if (d === 0n) throw new RangeError("zero denominator");
    if (d < 0n) {
      n = -n;
      d = -d;
    }
    const g = gcd(n < 0n ? -n : n, d);
    this.n = g > 1n ? n / g : n;
    this.d = g > 1n ? d / g : d;
  }

  static of(n: number | bigint): Fraction {
    return new Fraction(BigInt(n));
  }

  add(o: Fraction): Fraction {
    return new Fraction(this.n * o.d + o.n * this.d, this.d * o.d);
  }
  sub(o: Fraction): Fraction {
    return new Fraction(this.n * o.d - o.n * this.d, this.d * o.d);
  }
  mul(o: Fraction): Fraction {
    return new Fraction(this.n * o.n, this.d * o.d);
  }
  div(o: Fraction): Fraction {
    return new Fraction(this.n * o.d, this.d * o.n);
  }
  neg(): Fraction {
    return new Fraction(-this.n, this.d);
  }
  abs(): Fraction {
    return this.n < 0n ? this.neg() : this;
  }
  cmp(o: Fraction): number {
    const l = this.n * o.d;
    const r = o.n * this.d;
    return l < r ? -1 : l > r ? 1 : 0;
  }
  eq(o: Fraction): boolean {
    return this.n === o.n && this.d === o.d;
  }

  /** The nearest double (round half to even), like Python's `float(Fraction)`. */
  toNumber(): number {
    return ratioToNumber(this.n, this.d);
  }

  /** "n/d" (or "n" for an integer): the text Z3's `Real.val` accepts. */
  toString(): string {
    return this.d === 1n ? this.n.toString() : `${this.n}/${this.d}`;
  }
}

function gcd(a: bigint, b: bigint): bigint {
  while (b !== 0n) [a, b] = [b, a % b];
  return a;
}

const bitLength = (x: bigint): number => (x === 0n ? 0 : x.toString(2).length);

/** n/d rounded to the nearest double, ties to even (the value of Python's `n / d` on ints). */
export function ratioToNumber(n: bigint, d: bigint): number {
  if (n === 0n) return 0;
  const neg = n < 0n;
  let a = neg ? -n : n;
  const SAFE = (1n << 53n) - 1n;
  if (a <= SAFE && d <= SAFE) return (neg ? -1 : 1) * (Number(a) / Number(d));
  // scale so the integer quotient has 55..56 significant bits, then round half to even by hand
  const shift = 55 - (bitLength(a) - bitLength(d));
  let num = a;
  let den = d;
  if (shift >= 0) num = a << BigInt(shift);
  else den = d << BigInt(-shift);
  let q = num / den;
  const r = num % den;
  const bl = bitLength(q);
  const drop = bl - 53; // bits to remove (2 or 3)
  const mask = (1n << BigInt(drop)) - 1n;
  const low = q & mask;
  const half = 1n << BigInt(drop - 1);
  q >>= BigInt(drop);
  if (low > half || (low === half && (r !== 0n || (q & 1n) === 1n))) q += 1n;
  const exp = drop - shift;
  const v = Number(q) * 2 ** exp;
  return neg ? -v : v;
}

/** The exact value of a finite double. */
export function fromDouble(x: number): Fraction {
  if (!Number.isFinite(x)) throw new RangeError(`not finite: ${x}`);
  if (Number.isInteger(x) && Math.abs(x) < 2 ** 53) return Fraction.of(x);
  const buf = new DataView(new ArrayBuffer(8));
  buf.setFloat64(0, x);
  const hi = buf.getUint32(0);
  const lo = buf.getUint32(4);
  const neg = hi >>> 31 === 1;
  const exp = (hi >>> 20) & 0x7ff;
  const frac = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  const m = exp === 0 ? frac : frac | (1n << 52n);
  const e = exp === 0 ? -1074 : exp - 1075;
  const mm = neg ? -m : m;
  return e >= 0 ? new Fraction(mm << BigInt(e)) : new Fraction(mm, 1n << BigInt(-e));
}

/** Python's `Fraction.limit_denominator(maxDen)`: the closest fraction whose denominator is at most `maxDen`. */
export function limitDenominator(f: Fraction, maxDen: bigint): Fraction {
  if (f.d <= maxDen) return f;
  let p0 = 0n;
  let q0 = 1n;
  let p1 = 1n;
  let q1 = 0n;
  let n = f.n;
  let d = f.d;
  for (;;) {
    // floor division (n may be negative)
    let a = n / d;
    if (n % d !== 0n && n < 0n !== d < 0n) a -= 1n;
    const q2 = q0 + a * q1;
    if (q2 > maxDen) break;
    [p0, q0, p1, q1] = [p1, q1, p0 + a * p1, q2];
    [n, d] = [d, n - a * d];
  }
  const k = (maxDen - q0) / q1;
  const b1 = new Fraction(p0 + k * p1, q0 + k * q1);
  const b2 = new Fraction(p1, q1);
  const target = f;
  const d1 = b1.sub(target).abs();
  const d2 = b2.sub(target).abs();
  return d2.cmp(d1) <= 0 ? b2 : b1;
}

/** z3enc._rat: the exact rational of a float that is "a decimal with few digits" (0.6 -> 3/5). */
export function ratOf(x: number): Fraction {
  return limitDenominator(fromDouble(x), 1_000_000_000n);
}

/** A decimal numeral such as `12`, `2.5`, `-0.125` (no exponent) as an exact fraction. */
function parseDecimal(tok: string): Fraction | null {
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(tok);
  if (m === null) return null;
  const frac = m[3] ?? "";
  const n = BigInt((m[2] as string) + frac);
  const d = 10n ** BigInt(frac.length);
  return new Fraction(m[1] === "-" ? -n : n, d);
}

/**
 * Numeric value of an optimum or a model value printed by Z3, with the infinitesimal `epsilon` (an open bound such as
 * `a > 0.5`) set to 0. Supports numerals, `+`, `*`, `-` (unary and n-ary) and `/`, like solve.py `_closure_value`.
 */
export function parseSexpr(text: string): Fraction {
  const tok = text.replace(/\(/g, " ( ").replace(/\)/g, " ) ").trim().split(/\s+/);
  let p = 0;
  const read = (): Fraction => {
    const t = tok[p++];
    if (t === undefined) throw new Error(`unexpected end of numeral ${text}`);
    if (t === "(") {
      const op = tok[p++];
      const args: Fraction[] = [];
      while (tok[p] !== ")") {
        if (p >= tok.length) throw new Error(`unbalanced numeral ${text}`);
        args.push(read());
      }
      p++;
      if (op === "+") return args.reduce((a, b) => a.add(b), Fraction.of(0));
      if (op === "*") return args.reduce((a, b) => a.mul(b), Fraction.of(1));
      if (op === "/" && args.length === 2) return (args[0] as Fraction).div(args[1] as Fraction);
      if (op === "-" && args.length >= 1) {
        return args.length === 1 ? (args[0] as Fraction).neg() : args.slice(1).reduce((a, b) => a.sub(b), args[0] as Fraction);
      }
      throw new Error(`unexpected optimum term ${text}`);
    }
    if (t === "epsilon") return Fraction.of(0);
    const dec = parseDecimal(t);
    if (dec === null) throw new Error(`bad numeral ${t} in ${text}`);
    return dec;
  };
  const v = read();
  if (p !== tok.length) throw new Error(`trailing text in numeral ${text}`);
  return v;
}
