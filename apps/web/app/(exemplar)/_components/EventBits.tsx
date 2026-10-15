'use client'

import { useState } from 'react'
import { engineUrl } from '../_lib/api'
import { KIND_LABEL, SOURCE_LABEL, SUBTYPE_LABEL } from '../_lib/format'
import { useTrace } from '../_lib/traces'
import type { EventSummary, LabelSummary, Trace } from '../_lib/types'
import { Icon, type IconName } from './Icon'
import { Badge, cx } from './ui'

export const snapshotUrl = (eventId: string) => engineUrl(`/events/${encodeURIComponent(eventId)}/snapshot`)
export const clipUrl = (eventId: string) => engineUrl(`/events/${encodeURIComponent(eventId)}/clip`)

// ---------------------------------------------------------------------------------------------
// Trace strip: entities as rows, facts as small coloured ticks over time. Stands in for a snapshot.

const ENTITY_DOT: Record<string, string> = {
  person: 'bg-ex-accent-ink',
  package: 'bg-ex-warn',
  vehicle: 'bg-ex-syn-type',
  animal: 'bg-ex-syn-kw',
  object: 'bg-ex-ink3',
}

/** Most telling fact wins when several fall on the same frame. */
const FACT_RANK: Record<string, number> = {
  picks_up: 6, puts_down: 6, carrying: 5, rings_bell: 5, enters: 4, leaves: 4, in_zone: 3, near: 2, facing_camera: 2, attr: 1, present: 1,
}
const FACT_COLOR: Record<string, string> = {
  picks_up: '#F2B968', puts_down: '#F2B968', carrying: '#E3A24F', rings_bell: '#B9A3F5', enters: '#6FD3D0', leaves: '#6FD3D0',
  in_zone: '#7FB1FF', near: '#8A8F98', facing_camera: '#8A8F98', attr: '#5E646D', present: '#5E646D',
}

export function TraceStrip({ trace, compact = false }: { trace: Trace; compact?: boolean }) {
  const dur = Math.max(1, trace.duration_ms || trace.frames[trace.frames.length - 1]?.t_ms || 1)
  const frames = trace.frames
  const ents = trace.entities.slice(0, compact ? 3 : 4)
  const rowH = compact ? 5 : 8
  if (ents.length === 0) {
    return (
      <div aria-hidden="true" className="flex h-full w-full items-center justify-center gap-1.5 bg-ex-raised text-xs text-ex-ink3">
        <Icon name="circle" className="h-3.5 w-3.5" />
      </div>
    )
  }
  return (
    <div aria-hidden="true" className={cx('flex h-full w-full flex-col justify-center bg-ex-raised', compact ? 'gap-[3px] px-2' : 'gap-2 px-3.5')}>
      {ents.map((e) => (
        <div key={e.id} className="flex items-center gap-2">
          {!compact && (
            <span className="flex w-9 shrink-0 items-center gap-1.5 font-mono text-[10px] leading-none text-ex-ink3">
              <span className={cx('h-1.5 w-1.5 rounded-full', ENTITY_DOT[e.type] ?? 'bg-ex-ink3')} />
              {e.id}
            </span>
          )}
          <svg viewBox="0 0 100 10" preserveAspectRatio="none" className="w-full" style={{ height: rowH }}>
            <rect x="0" y="3.5" width="100" height="3" rx="1.5" fill="rgba(255,255,255,0.07)" />
            {frames.map((f, i) => {
              let best: string | null = null
              let rank = -1
              for (const fact of f.facts) {
                if (!fact.args.includes(e.id)) continue
                const r = FACT_RANK[fact.pred] ?? 0
                if (r > rank) { rank = r; best = fact.pred }
              }
              if (!best) return null
              const x = (f.t_ms / dur) * 100
              const next = frames[i + 1]?.t_ms ?? dur
              const w = Math.max(2.2, Math.min(9, ((next - f.t_ms) / dur) * 100 - 0.6))
              return <rect key={i} x={Math.min(100 - w, x)} y="0" width={w} height="10" rx="1.6" fill={FACT_COLOR[best] ?? '#8A8F98'} />
            })}
          </svg>
        </div>
      ))}
    </div>
  )
}

function TracePlaceholder({ event, compact }: { event: ThumbEvent; compact: boolean }) {
  const trace = useTrace(event.id, event.trace_status === 'ok')
  if (event.trace_status === 'perception_failed') {
    return (
      <div aria-hidden="true" className="flex h-full w-full items-center justify-center gap-1.5 bg-ex-raised text-xs text-ex-warn">
        <Icon name="warning" className="h-3.5 w-3.5" />
      </div>
    )
  }
  if (event.trace_status === 'none') {
    return (
      <div aria-hidden="true" className="skeleton flex h-full w-full items-center justify-center gap-1.5 rounded-none text-xs text-ex-ink3">
        <Icon name="clock" className="h-3.5 w-3.5" />
      </div>
    )
  }
  if (trace === undefined) return <div aria-hidden="true" className="skeleton h-full w-full rounded-none" />
  if (trace === null) {
    return (
      <div aria-hidden="true" className="flex h-full w-full items-center justify-center bg-ex-raised text-ex-ink3">
        <Icon name="image" className="h-4 w-4" />
      </div>
    )
  }
  return <TraceStrip trace={trace} compact={compact} />
}

type ThumbEvent = Pick<EventSummary, 'id' | 'has_snapshot'> & Partial<Pick<EventSummary, 'trace_status'>>

/**
 * Snapshot thumbnail. Decorative by default (the card text already describes the event). Clips without a
 * picture (fixtures, a snapshot that failed to load) get a trace strip drawn from the symbolic trace.
 */
export function EventThumb({
  event, className = '', alt = '', compact = false,
}: { event: ThumbEvent; className?: string; alt?: string; showLabel?: boolean; compact?: boolean }) {
  const [failed, setFailed] = useState(false)
  if (!event.has_snapshot || failed) {
    return (
      <div className={cx('overflow-hidden bg-ex-raised', className)}>
        <TracePlaceholder event={{ ...event, trace_status: event.trace_status ?? 'ok' }} compact={compact} />
      </div>
    )
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={snapshotUrl(event.id)} alt={alt} loading="lazy" onError={() => setFailed(true)} className={cx('bg-ex-raised object-cover', className)} />
}

// ---------------------------------------------------------------------------------------------
export const SOURCE_ICON: Record<string, IconName> = { ring: 'camera', ring_live: 'camera', upload: 'upload', meva: 'film', fixture: 'layers' }

/** Small dark tag for the bottom-left of a thumbnail (never the top corners: Ring's watermark lives there). */
export function SourceTag({ source }: { source: EventSummary['source'] }) {
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded bg-black/70 px-1.5 text-[11px] font-medium leading-none text-white">
      <Icon name={SOURCE_ICON[source] ?? 'camera'} className="h-3 w-3" />
      {SOURCE_LABEL[source] ?? source}
    </span>
  )
}

/** Plain-text source: icon and word, no chip. */
export function SourceBadge({ source }: { source: EventSummary['source'] }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-ex-ink2">
      <Icon name={SOURCE_ICON[source] ?? 'camera'} className="h-3 w-3" />
      {SOURCE_LABEL[source] ?? source}
    </span>
  )
}

export function KindBadges({ event }: { event: EventSummary }) {
  const parts = [event.kind && (KIND_LABEL[event.kind] ?? event.kind), event.sub_type && event.sub_type !== event.kind && (SUBTYPE_LABEL[event.sub_type] ?? event.sub_type)].filter(Boolean)
  if (parts.length === 0) return null
  return <span className="text-xs text-ex-ink2">{parts.join(' · ')}</span>
}

export function TraceStatusBadge({ event }: { event: EventSummary }) {
  if (event.trace_status === 'perception_failed') return <Badge tone="warn" icon="warning">Perception failed</Badge>
  if (event.trace_status === 'none') {
    const wait = event.clip_status === 'failed' || event.clip_status === 'not_found'
    return <Badge tone={wait ? 'neg' : 'neutral'} icon={wait ? 'cross' : 'clock'}>{wait ? 'Clip unavailable' : event.clip_status === 'ready' ? 'Reading clip…' : 'Fetching clip…'}</Badge>
  }
  return null
}

const PROV_TEXT = { example: 'example', active: 'asked', random: 'calibration' } as const
const PROV_TITLE = {
  random: 'Labelled from a uniform random sample: counts towards the false-alarm calibration',
  active: 'Answered after Exemplar asked: used for learning, never for calibration',
  example: 'Chosen by you as an example: used for learning, never for calibration',
} as const

/** Label state as an icon, a word and a quiet provenance note. */
export function LabelIndicator({ label, showProvenance = true }: { label: LabelSummary | null | undefined; showProvenance?: boolean }) {
  if (!label || !label.value) return null
  const pos = label.value === 'pos'
  return (
    <span className="inline-flex items-center gap-1.5 text-xs" title={PROV_TITLE[label.provenance]}>
      <span className={cx('inline-flex items-center gap-1 font-medium', pos ? 'text-ex-pos' : 'text-ex-neg')}>
        <Icon name={pos ? 'plus' : 'minus'} className="h-3 w-3" />
        {pos ? 'Positive' : 'Negative'}
      </span>
      {showProvenance && (
        <span className="inline-flex items-center gap-1 text-ex-ink3">
          {label.provenance === 'random' && <Icon name="shuffle" className="h-3 w-3" />}
          {PROV_TEXT[label.provenance]}
        </span>
      )}
    </span>
  )
}

/** Kept for call sites that used the old name. */
export const ProvenanceBadge = LabelIndicator

/**
 * Three-state label control: + positive, − negative, ? unlabelled. A real toggle group: each button has
 * aria-pressed and a text name; pressed state is shown with fill and the glyph, not colour alone.
 */
export function LabelControl({
  conceptName, clipSummary, value, onSet, disabled, className = '',
}: {
  conceptName: string
  clipSummary: string
  value: 'pos' | 'neg' | null | undefined
  onSet: (v: 'pos' | 'neg' | null) => void
  disabled?: boolean
  className?: string
}) {
  const btn = (v: 'pos' | 'neg' | null, icon: IconName, name: string, on: string) => {
    const pressed = (value ?? null) === v
    return (
      <button
        type="button"
        aria-pressed={pressed}
        aria-label={`${name}: ${clipSummary}`}
        title={`${name} for “${conceptName}”`}
        disabled={disabled}
        onClick={() => onSet(v)}
        className={cx(
          'grid h-7 w-7 place-items-center rounded transition-colors disabled:opacity-50',
          pressed ? on : 'text-ex-ink2 hover:bg-ex-hover hover:text-ex-ink',
        )}
      >
        <Icon name={icon} className="h-3.5 w-3.5" />
      </button>
    )
  }
  return (
    <div role="group" aria-label={`Label for ${conceptName}`} className={cx('inline-flex gap-0.5 rounded-md border border-ex-line2 bg-ex-bg p-0.5', className)}>
      {btn('pos', 'plus', 'Mark positive', 'bg-ex-pos-soft text-ex-pos shadow-[inset_0_0_0_1px_var(--ex-pos-line)]')}
      {btn('neg', 'minus', 'Mark negative', 'bg-ex-neg-soft text-ex-neg shadow-[inset_0_0_0_1px_var(--ex-neg-line)]')}
      {btn(null, 'question', 'Clear label', 'bg-ex-hover text-ex-ink')}
    </div>
  )
}
