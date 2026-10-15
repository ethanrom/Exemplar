'use client'

import Link from 'next/link'
import type { EventSummary, RuleSummary } from '../_lib/types'
import { fmtNum, keepUnits } from '../_lib/format'
import { Dsl, DslBlock } from './Dsl'
import { EventThumb } from './EventBits'
import { Icon } from './Icon'
import { Badge, Meta, cx } from './ui'

const STATUS_TONE = { candidate: 'neutral', selected: 'info', deployed: 'pos', retired: 'neutral' } as const
const STATUS_LABEL = { candidate: 'Candidate', selected: 'Selected', deployed: 'Live', retired: 'Retired' } as const

/** A rule exactly as the engine rendered it: English and DSL come from the engine, never composed here. */
export function RuleHeadline({ rule, size = 'md' }: { rule: RuleSummary; size?: 'sm' | 'md' | 'lg' | 'xl' }) {
  const cls = { sm: 'text-base', md: 'text-md', lg: 'text-lg', xl: 'text-xl sm:text-2xl' }[size]
  return (
    <>
      <p className={cx(cls, 'text-pretty font-medium leading-snug tracking-tight text-ex-ink')}>{keepUnits(rule.english)}</p>
      <DslBlock text={rule.dsl_text} size={size === 'sm' ? 'sm' : size === 'md' ? 'md' : 'lg'} className="mt-3" />
    </>
  )
}

/** Quiet metadata: description length, margin and the numbers the solver chose. No chips. */
export function RuleMetrics({ rule, showStatus = true }: { rule: RuleSummary; showStatus?: boolean }) {
  const holes = Object.entries(rule.holes ?? {})
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <li><Meta label="MDL" value={fmtNum(rule.mdl, 1)} title="Description length: smaller is a simpler rule" /></li>
      <li><Meta label="margin" value={fmtNum(rule.margin)} title="How far the examples sit from the decision boundary, in robustness units (larger is safer)" /></li>
      {holes.map(([k, v]) => (
        <li key={k}><Meta label={<span className="font-mono text-ex-syn-hole">{k}</span>} value={v} title="Value the solver chose for this threshold" /></li>
      ))}
      {showStatus && rule.status !== 'candidate' && (
        <li><Badge tone={STATUS_TONE[rule.status]} icon={rule.status === 'deployed' ? 'bolt' : rule.status === 'selected' ? 'check' : 'dot'}>{STATUS_LABEL[rule.status]}</Badge></li>
      )}
    </ul>
  )
}

export function SuspectList({
  rule, events, onInspect,
}: { rule: RuleSummary; events: Map<string, EventSummary>; onInspect: (eventId: string) => void }) {
  const ids = rule.violated_clip_ids ?? []
  if (ids.length === 0) return null
  return (
    <div className="mt-4 rounded-lg border border-ex-warn-line bg-ex-warn-soft p-3.5">
      <p className="flex items-center gap-2 text-sm font-medium text-ex-ink">
        <Icon name="warning" className="h-4 w-4 text-ex-warn" /> Perception suspect?
      </p>
      <p className="mt-1 text-sm text-ex-ink2">
        This rule disagrees with {ids.length} of your labelled example{ids.length === 1 ? '' : 's'}. The label may be right and the model may have missed a fact: check the clip{ids.length === 1 ? '' : 's'}.
      </p>
      <ul className={cx('mt-3 grid gap-2', ids.length > 1 && 'sm:grid-cols-2')}>
        {ids.map((id) => {
          const ev = events.get(id)
          return (
            <li key={id} className="flex items-center gap-2.5 rounded-md bg-ex-bg/60 p-1.5">
              {ev && <EventThumb event={ev} compact className="h-9 w-16 shrink-0 rounded" />}
              <span className="min-w-0 flex-1 line-clamp-2 text-xs text-ex-ink2">{ev?.summary ?? id}</span>
              {ev && (
                <button type="button" className="btn btn-sm" onClick={() => onInspect(ev.id)}>
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

/** The top candidate as a hero: English large, highlighted DSL, quiet metadata, one primary action. */
export function HeroRuleCard({
  rule, events, onInspect,
}: { rule: RuleSummary; events: Map<string, EventSummary>; onInspect: (eventId: string) => void }) {
  return (
    <article className="rounded-xl border border-ex-line2 bg-ex-panel p-6" aria-label="Top candidate rule">
      <p className="text-xs font-medium text-ex-accent-ink">
        <Icon name="spark" className="mr-1.5 inline h-3.5 w-3.5 align-[-2px]" />Top candidate
        <span className="font-normal text-ex-ink3"> · simplest rule that fits every example</span>
      </p>
      <p className="mt-3 text-pretty text-lg font-medium leading-snug tracking-tight text-ex-ink sm:text-xl">{keepUnits(rule.english)}</p>
      <DslBlock text={rule.dsl_text} size="lg" className="mt-4" />
      <div className="mt-4"><RuleMetrics rule={rule} /></div>
      <SuspectList rule={rule} events={events} onInspect={onInspect} />
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Link href={`/rule?rule=${encodeURIComponent(rule.id)}`} className="btn btn-primary btn-lg">
          Backtest &amp; deploy <Icon name="arrow-right" />
        </Link>
        <span className="text-xs text-ex-ink3">Scores every clip in your library with this rule. Free: no model calls.</span>
      </div>
    </article>
  )
}

/** One of the remaining candidates: compact, ranked, with a single secondary action. */
export function CandidateRow({
  rule, rank, events, onInspect,
}: { rule: RuleSummary; rank: number; events: Map<string, EventSummary>; onInspect: (eventId: string) => void }) {
  return (
    <li className="group grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 py-4 sm:grid-cols-[1.5rem_minmax(0,1fr)_auto]" aria-label={`Candidate rule ${rank}`}>
      <span className="pt-0.5 text-sm font-medium tabular-nums text-ex-ink3" aria-hidden="true">{rank}</span>
      <div className="min-w-0">
        <p className="text-pretty text-base font-medium leading-snug text-ex-ink">{keepUnits(rule.english)}</p>
        <p className="mt-1.5 break-words font-mono text-xs leading-5"><Dsl text={rule.dsl_text} /></p>
        <div className="mt-2"><RuleMetrics rule={rule} showStatus={false} /></div>
        <SuspectList rule={rule} events={events} onInspect={onInspect} />
      </div>
      <div className="col-start-2 sm:col-start-3 sm:row-start-1">
        <Link href={`/rule?rule=${encodeURIComponent(rule.id)}`} className="btn btn-sm">
          Use this rule<span className="sr-only">: candidate {rank}</span>
        </Link>
      </div>
    </li>
  )
}
