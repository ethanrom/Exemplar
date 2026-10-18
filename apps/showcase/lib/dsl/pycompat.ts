// Python-compatible primitives. The engine's outputs (numbers in text, error messages, rounding of hole
// values) are defined by CPython semantics, so the port reproduces those semantics exactly instead of
// relying on the nearly-equal JavaScript built-ins.

/** Python's `round(x)` for a float: round half to even. Returns a number (an integer value, never -0). */
export function pyRound(x: number): number {
  if (!Number.isFinite(x)) return x;
  const f = Math.floor(x);
  const diff = x - f; // exact for finite doubles
  let r: number;
  if (diff === 0.5) r = f % 2 === 0 ? f : f + 1;
  else r = Math.round(x);
  return r + 0; // -0 -> +0
}

/** x = sign * m * 2^e with m a non-negative BigInt, for a finite double. */
function decompose(x: number): { neg: boolean; m: bigint; e: number } {
  const buf = new DataView(new ArrayBuffer(8));
  buf.setFloat64(0, x);
  const hi = buf.getUint32(0);
  const lo = buf.getUint32(4);
  const neg = (hi >>> 31) === 1;
  const exp = (hi >>> 20) & 0x7ff;
  const frac = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  if (exp === 0) return { neg, m: frac, e: -1074 };
  return { neg, m: frac | (1n << 52n), e: exp - 1075 };
}

/** Python's `f"{x:.3f}"` for a finite float: correctly rounded, ties to even on the exact binary value. */
export function formatFixed3(x: number): string {
  const { neg, m, e } = decompose(x);
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
  const ip = q / 1000n;
  const fp = (q % 1000n).toString().padStart(3, "0");
  return `${neg ? "-" : ""}${ip.toString()}.${fp}`;
}

/** `str(int(x))` for an integral finite float (arbitrary size, as Python ints are unbounded). */
export function intString(x: number): string {
  if (Math.abs(x) < 1e15) return String(x + 0); // +0 turns -0 into 0
  return BigInt(x).toString();
}

/** Python's `repr(float)` (shortest round-trip digits, Python's exponent thresholds and spelling). */
export function pyFloatRepr(x: number): string {
  if (Number.isNaN(x)) return "nan";
  if (x === Infinity) return "inf";
  if (x === -Infinity) return "-inf";
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const neg = x < 0;
  const [mant, expStr] = Math.abs(x).toExponential().split("e");
  const digits = mant.replace(".", "");
  const E = Number(expStr);
  const decpt = E + 1;
  let body: string;
  if (decpt <= -4 || decpt > 16) {
    const ae = Math.abs(E);
    body = `${digits[0]}${digits.length > 1 ? "." + digits.slice(1) : ""}e${E < 0 ? "-" : "+"}${ae < 10 ? "0" : ""}${ae}`;
  } else if (decpt <= 0) {
    body = `0.${"0".repeat(-decpt)}${digits}`;
  } else if (decpt >= digits.length) {
    body = `${digits}${"0".repeat(decpt - digits.length)}.0`;
  } else {
    body = `${digits.slice(0, decpt)}.${digits.slice(decpt)}`;
  }
  return neg ? "-" + body : body;
}

/** Python's `str(float)` is `repr(float)`. */
export const pyFloatStr = pyFloatRepr;

const NON_PRINTABLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]/u;

/** Python's `repr(str)`. */
export function pyReprStr(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const cp = ch.codePointAt(0) as number;
    if (ch === quote || ch === "\\") out += "\\" + ch;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (ch === " ") out += " ";
    else if (NON_PRINTABLE.test(ch)) {
      if (cp < 0x100) out += "\\x" + cp.toString(16).padStart(2, "0");
      else if (cp < 0x10000) out += "\\u" + cp.toString(16).padStart(4, "0");
      else out += "\\U" + cp.toString(16).padStart(8, "0");
    } else out += ch;
  }
  return out + quote;
}

const LINE_BREAKS = /\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]/;

/** Python's `str.splitlines()` (no trailing empty element). */
export function pySplitlines(s: string): string[] {
  const out: string[] = [];
  let rest = s;
  while (rest.length > 0) {
    const m = LINE_BREAKS.exec(rest);
    if (m === null) {
      out.push(rest);
      break;
    }
    out.push(rest.slice(0, m.index));
    rest = rest.slice(m.index + m[0].length);
  }
  return out;
}

/** Length in Unicode code points (Python's `len(str)`). */
export function codePointLength(s: string): number {
  let n = 0;
  for (const _ of s) n += 1;
  return n;
}

/** Python's `" " * n` guard: negative counts give the empty string. */
export function spaces(n: number): string {
  return n > 0 ? " ".repeat(n) : "";
}
