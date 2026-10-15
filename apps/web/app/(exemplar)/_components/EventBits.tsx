'use client'

import { engineUrl } from '../_lib/api'
import { KIND_LABEL, SOURCE_LABEL, SUBTYPE_LABEL } from '../_lib/format'
import type { EventSummary, LabelSummary } from '../_lib/types'
import { Badge } from './ui'
import { Icon } from './Icon'

export const snapshotUrl = (eventId: string) => engineUrl(`/events/${encodeURIComponent(eventId)}/snapshot`)
export const clipUrl = (eventId: string) => engineUrl(`/events/${encodeURIComponent(eventId)}/clip`)

/** Snapshot thumbnail. Decorative by default (the card text already describes the event). */
export function EventThumb({ event, className = '', alt = '' }: { event: Pick<EventSummary, 'id' | 'has_snapshot'>; className?: string; alt?: string }) {
  if (!event.has_snapshot) {
    return (
      <div className={`grid place-items-center bg-ex-bg text-ex-ink3 ${className}`}>
        <span className="flex flex-col items-center gap-1 text-xs">
          <Icon name="camera" className="h-6 w-6" />
          No snapshot
        </span>
      </div>
    )
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={snapshotUrl(event.id)} alt={alt} loading="lazy" className={`bg-ex-bg object-cover ${className}`} />
}

export function SourceBadge({ source }: { source: EventSummary['source'] }) {
  const tone = source === 'upload' ? 'accent' : source === 'ring' || source === 'ring_live' ? 'info' : 'neutral'
  return <Badge tone={tone} icon={source === 'upload' ? 'upload' : source === 'meva' ? 'film' : 'camera'}>{SOURCE_LABEL[source] ?? source}</Badge>
}

export function KindBadges({ event }: { event: EventSummary }) {
  return (
    <>
      {event.kind && <span className="chip">{KIND_LABEL[event.kind] ?? event.kind}</span>}
      {event.sub_type && <span className="chip">{SUBTYPE_LABEL[event.sub_type] ?? event.sub_type}</span>}
    </>
  )
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

export function ProvenanceBadge({ label }: { label: LabelSummary | null | undefined }) {
  if (!label || !label.value) return null
  const pos = label.value === 'pos'
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <Badge tone={pos ? 'pos' : 'neg'} icon={pos ? 'plus' : 'minus'}>{pos ? 'Positive' : 'Negative'}</Badge>
      <span
        className={`chip ${label.provenance === 'random' ? 'border-amber-400/60 text-amber-100' : ''}`}
        title={
          label.provenance === 'random'
            ? 'Labelled from a uniform random sample: counts towards the false-alarm calibration'
            : label.provenance === 'active'
              ? 'Answered after Exemplar asked: used for learning, never for calibration'
              : 'Chosen by you as an example: used for learning, never for calibration'
        }
      >
        {label.provenance === 'random' && <Icon name="shuffle" className="h-3 w-3" />}
        {PROV_TEXT[label.provenance]}
      </span>
    </span>
  )
}

/**
 * Three-state label control: + positive, − negative, ? unlabelled. A real toggle group: each button
 * has aria-pressed and a text name; pressed state is shown with fill and the glyph, not colour alone.
 */
export function LabelChips({
  conceptName, clipSummary, value, onSet, disabled,
}: {
  conceptName: string
  clipSummary: string
  value: 'pos' | 'neg' | null | undefined
  onSet: (v: 'pos' | 'neg' | null) => void
  disabled?: boolean
}) {
  const btn = (v: 'pos' | 'neg' | null, glyph: string, name: string, on: string) => {
    const pressed = (value ?? null) === v
    return (
      <button
        type="button"
        aria-pressed={pressed}
        aria-label={`${name}: ${clipSummary}`}
        title={`${name} for “${conceptName}”`}
        disabled={disabled}
        onClick={() => onSet(v)}
        className={`grid h-9 w-9 place-items-center rounded-md border text-base font-bold transition-colors disabled:opacity-60 ${
          pressed ? `${on} border-transparent` : 'border-ex-line bg-ex-bg text-ex-ink2 hover:bg-ex-raised'
        }`}
      >
        <span aria-hidden="true">{glyph}</span>
      </button>
    )
  }
  return (
    <div role="group" aria-label={`Label for ${conceptName}`} className="inline-flex gap-1">
      {btn('pos', '+', 'Mark positive', 'bg-green-400 text-slate-950')}
      {btn('neg', '−', 'Mark negative', 'bg-red-400 text-slate-950')}
      {btn(null, '?', 'Clear label', 'bg-slate-300 text-slate-950')}
    </div>
  )
}
