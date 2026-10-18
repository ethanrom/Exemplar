// Display helpers. They only format numbers and words that came from the data.

const MINUS = '−'

/** A robustness score or margin: sign and two decimals (the engine rounds its margins to two as well). */
export function fmtScore(value: number): string {
  const rounded = Math.round(value * 100) / 100
  if (rounded === 0) return '0.00'
  return `${rounded > 0 ? '+' : MINUS}${Math.abs(rounded).toFixed(2)}`
}

/** An unsigned two-decimal value such as the firing threshold. */
export function fmtPlain(value: number): string {
  return (Math.round(value * 100) / 100).toFixed(2)
}

/** Milliseconds as seconds with the precision the data has: "0.99 s", "15.99 s", "31.7 s". */
export function fmtSeconds(ms: number, digits = 1): string {
  return `${(ms / 1000).toFixed(digits)} s`
}

/** A window length that is a whole number of seconds in the data prints without decimals ("15 s"). */
export function fmtSpan(startMs: number, endMs: number): string {
  const d = (endMs - startMs) / 1000
  return Number.isInteger(d) ? `${d} s` : `${d.toFixed(2)} s`
}

export function ordinal(n: number): string {
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`
  switch (n % 10) {
    case 1: return `${n}st`
    case 2: return `${n}nd`
    case 3: return `${n}rd`
    default: return `${n}th`
  }
}

/** Fact arguments as the rule language writes them: in_zone(k1, steps). */
export function factText(pred: string, args: string[]): string {
  return `${pred}(${args.join(', ')})`
}

export function pluralise(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many
}

/** A clip length as the data has it: whole seconds print as "32 s", others with one decimal ("19.9 s"). */
export function fmtDuration(ms: number): string {
  const s = ms / 1000
  return Number.isInteger(s) ? `${s} s` : `${s.toFixed(1)} s`
}

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'] as const

/** Small counts in prose ("two of the four negatives"); larger ones stay digits. */
export function words(n: number): string {
  return WORDS[n] ?? String(n)
}

export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
