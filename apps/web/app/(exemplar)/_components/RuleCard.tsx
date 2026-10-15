'use client'

import Link from 'next/link'
import type { EventSummary, RuleSummary } from '../_lib/types'
import { fmtNum } from '../_lib/format'
import { EventThumb } from './EventBits'
import { Icon } from './Icon'
import { Badge } from './ui'

const STATUS_TONE = { candidate: 'neutral', selected: 'info', deployed: 'pos', retired: 'neutral' } as const

/** A rule exactly as the engine rendered it: English and DSL come from the engine, never composed here. */
export function RuleHeadline({ rule, large = false }: { rule: RuleSummary; large?: boolean }) {
  return (
    <>
      <p className={`${large ? 'text-xl' : 'text-base'} font-medium leading-snug text-ex-ink`}>{rule.english}</p>
      <pre className="code mt-2 text-[13px]" aria-label="Rule in the Exemplar logic language"><code>{rule.dsl_text}</code></pre>
    </>
  )
}

export function RuleMetrics({ rule }: { rule: RuleSummary }) {
  const holes = Object.entries(rule.holes ?? {})
  return (
    <ul className="mt-2 flex flex-wrap items-center gap-1.5">
      <li><span className="chip" title="Description length: smaller is a simpler rule">MDL <span className="font-mono tabular-nums text-ex-ink">{fmtNum(rule.mdl, 1)}</span></span></li>
      <li><span className="chip" title="How far the examples sit from the decision boundary, in robustness units (larger is safer)">margin <span className="font-mono tabular-nums text-ex-ink">{fmtNum(rule.margin)}</span></span></li>
      {holes.map(([k, v]) => (
        <li key={k}><span className="chip" title="Value the solver chose for this threshold"><span className="font-mono text-ex-ink">{k}</span> = <span className="font-mono tabular-nums text-ex-ink">{v}</span></span></li>
      ))}
      <li><Badge tone={STATUS_TONE[rule.status]} icon={rule.status === 'deployed' ? 'bolt' : rule.status === 'selected' ? 'check' : 'dot'}>{rule.status}</Badge></li>
    </ul>
  )
}

export function SuspectList({
  rule, events, onInspect,
}: { rule: RuleSummary; events: Map<string, EventSummary>; onInspect: (eventId: string) => void }) {
  const ids = rule.violated_clip_ids ?? []
  if (ids.length === 0) return null
  return (
    <div className="mt-3 rounded-lg border border-amber-400/60 bg-amber-950/60 p-3">
      <p className="flex items-center gap-2 text-sm font-semibold text-amber-100">
        <Icon name="warning" /> Perception suspect?
      </p>
      <p className="mt-0.5 text-sm text-amber-100/90">
        This rule disagrees with {ids.length} of your labelled example{ids.length === 1 ? '' : 's'}. The label may be right and the model may have missed a fact: check the clip{ids.length === 1 ? '' : 's'}.
      </p>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {ids.map((id) => {
          const ev = events.get(id)
          return (
            <li key={id} className="flex items-center gap-2 rounded-md border border-amber-400/30 bg-ex-bg p-1.5">
              {ev && <EventThumb event={ev} className="h-9 w-16 shrink-0 rounded" />}
              <span className="min-w-0 flex-1 truncate text-xs text-ex-ink2">{ev?.summary ?? id}</span>
              {ev && (
                <button type="button" className="btn !min-h-[32px] !px-2 text-xs" onClick={() => onInspect(ev.id)}>
                  Inspect<span className="sr-only">: {ev.summary ?? id}</span>
                </button>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function RuleCard({
  rule, rank, events, onInspect,
}: { rule: RuleSummary; rank: number; events: Map<string, EventSummary>; onInspect: (eventId: string) => void }) {
  return (
    <article className="rounded-xl border border-ex-line bg-ex-panel p-4" aria-label={`Candidate rule ${rank}`}>
      <div className="flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ex-raised text-sm font-bold text-ex-ink" aria-hidden="true">{rank}</span>
        <div className="min-w-0 flex-1">
          <RuleHeadline rule={rule} />
          <RuleMetrics rule={rule} />
          <SuspectList rule={rule} events={events} onInspect={onInspect} />
          <div className="mt-3">
            <Link href={`/rule?rule=${encodeURIComponent(rule.id)}`} className="btn-primary">
              Backtest and deploy <Icon name="chevron-right" />
              <span className="sr-only">: candidate {rank}</span>
            </Link>
          </div>
        </div>
      </div>
    </article>
  )
}
