import type { EventSummary } from './types'

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

/** "Oct 13, 2:25 AM": the date with the time of day. */
export const fmtDay = (ms: number) => new Date(ms).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

export const fmtUsd = (x: number | null | undefined) =>
  x == null ? '-' : x === 0 ? '$0' : x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(3)}`

/** Ring device ids (ava1.ring.device.…) are never shown: any message that mentions one reads "the camera" instead. */
export const hideDeviceIds = (s: string) => s.replace(/\bava1\.ring\.device\.[A-Za-z0-9_-]+/g, 'the camera')

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

/**
 * A clip's name for people: its one-sentence summary, else what it is and when ("Person · Oct 15, 12:38 PM").
 * Never the raw clip or event id, which means nothing to the reader.
 */
export function clipName(ev: Pick<EventSummary, 'summary' | 'kind' | 'sub_type' | 'source' | 'start_ms' | 'trace_status'> | null | undefined): string {
  if (!ev) return 'A labelled clip'
  if (ev.summary && ev.trace_status !== 'perception_failed') return ev.summary
  const what = (ev.sub_type && SUBTYPE_LABEL[ev.sub_type]) || (ev.kind && KIND_LABEL[ev.kind]) || SOURCE_LABEL[ev.source] || 'Clip'
  return `${what} · ${fmtDay(ev.start_ms)}`
}

/** Minimum number of random negatives for a conformal guarantee at level alpha: ceil(1/alpha) - 1. */
export const negativesNeeded = (alpha: number) => Math.max(0, Math.ceil(1 / alpha - 1e-9) - 1)

/** Typography only: keep a number and its unit ("24 s") on one line. The wording itself is never changed. */
export const keepUnits = (t: string) => t.replace(/(\d) (s|ms|min)\b/g, '$1\u00a0$2')
