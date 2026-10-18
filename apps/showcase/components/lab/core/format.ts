// Small, pure formatting helpers shared by the Lab and How pages (no framework imports: node:test runs this file).

const MINUS = "\u2212"; // U+2212, so a negative score reads as a minus sign, not a hyphen

/** Robustness as the site prints it: signed, 2 decimals (+0.45, −0.50, 0.00). */
export function fmtScore(x: number): string {
  const r = Math.round(Math.abs(x) * 100) / 100;
  if (r === 0) return "0.00";
  return (x > 0 ? "+" : MINUS) + r.toFixed(2);
}

/** Plain number with at most `max` decimals and no trailing zeros (15, 14.87, 0.45). */
export function fmtPlain(x: number, max = 2): string {
  if (!Number.isFinite(x)) return String(x);
  const s = x.toFixed(max);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

/** Milliseconds as seconds with one decimal: "16.0 s". */
export function fmtSec(ms: number): string {
  return (ms / 1000).toFixed(1) + " s";
}

/** Seconds (already in seconds) with up to 3 decimals and the unit: "29.746 s". */
export function fmtSecs(s: number, max = 3): string {
  return fmtPlain(s, max) + " s";
}

/** "1st", "2nd", "3rd", "4th", ... */
export function ordinal(n: number): string {
  const v = n % 100;
  if (v >= 11 && v <= 13) return n + "th";
  const last = n % 10;
  return n + (last === 1 ? "st" : last === 2 ? "nd" : last === 3 ? "rd" : "th");
}

/** Compact byte-free percentage for charts. */
export function pct(x: number, digits = 1): string {
  return (x * 100).toFixed(digits) + "%";
}

/** Clamp. */
export function clamp(x: number, lo: number, hi: number): number {
  return Math.min(Math.max(x, lo), hi);
}
