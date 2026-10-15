export const fmtScore = (x: number | null | undefined, digits = 2) =>
  x == null ? '-' : `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(digits)}`

export const fmtNum = (x: number | null | undefined, digits = 2) => (x == null ? '-' : x.toFixed(digits))

export const fmtPct = (x: number | null | undefined, digits = 0) => (x == null ? '-' : `${(x * 100).toFixed(digits)}%`)

export function fmtSeconds(ms: number, digits = 1): string {
  return `${(ms / 1000).toFixed(digits)} s`
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return '-'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s} s`
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`
}

export function fmtCountdown(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function fmtClock(ms: number, withSeconds = true): string {
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(withSeconds ? { second: '2-digit' } : {}) })
}

export function fmtDateTime(ms: number): string {
  return new Date(ms).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function fmtRelative(ms: number, now = Date.now()): string {
  const d = now - ms
  const abs = Math.abs(d)
  const m = Math.round(abs / 60_000)
  const sign = d >= 0 ? 'ago' : 'from now'
  if (abs < 45_000) return d >= 0 ? 'just now' : 'in a moment'
  if (m < 60) return `${m} min ${sign}`
  const h = Math.round(abs / 3_600_000)
  if (h < 48) return `${h} h ${sign}`
  return `${Math.round(abs / 86_400_000)} d ${sign}`
}

export const fmtUsd = (x: number | null | undefined) =>
  x == null ? '-' : x === 0 ? '$0' : x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(3)}`

export const fmtInt = (x: number | null | undefined) => (x == null ? '-' : Math.round(x).toLocaleString())

export const SOURCE_LABEL: Record<string, string> = {
  ring: 'Ring',
  ring_live: 'Ring live',
  upload: 'Upload',
  meva: 'MEVA',
  fixture: 'Fixture',
}

export const KIND_LABEL: Record<string, string> = {
  on_demand: 'Playground (on demand)',
  motion: 'Motion',
  ding: 'Doorbell',
  live: 'Live capture',
  upload: 'Uploaded window',
}

export const SUBTYPE_LABEL: Record<string, string> = {
  human: 'Person',
  vehicle: 'Vehicle',
  package_delivery: 'Package',
  other_motion: 'Other motion',
  motion: 'Motion',
  ding: 'Ring',
  on_demand: 'On demand',
}

/** Minimum number of random negatives for a conformal guarantee at level alpha: ceil(1/alpha) - 1. */
export const negativesNeeded = (alpha: number) => Math.max(0, Math.ceil(1 / alpha - 1e-9) - 1)
