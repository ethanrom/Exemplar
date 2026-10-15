'use client'

import { fmtPct } from '../_lib/format'
import type { Question } from '../_lib/types'
import { EventThumb, SourceBadge } from './EventBits'
import { Icon } from './Icon'

/**
 * The single active-learning question: the unlabelled clip the surviving rules disagree on most.
 * `p` is the weighted share of rule variants that match it; the closer to 50%, the more an answer teaches.
 */
export function QuestionCard({
  q, busy, onAnswer, onSkip, onOpen,
}: {
  q: Question
  busy?: boolean
  onAnswer: (v: 'pos' | 'neg') => void
  onSkip: () => void
  onOpen: () => void
}) {
  const ev = q.event
  return (
    <section aria-labelledby="q-h" className="rounded-xl border-2 border-cyan-300/70 bg-ex-panel p-4">
      <h3 id="q-h" className="flex items-center gap-2 text-lg font-semibold text-ex-ink">
        <Icon name="question" className="h-5 w-5 text-cyan-300" /> Should this one count?
      </h3>
      <p className="mt-1 text-sm text-ex-ink2">
        Your rules disagree on this one <span className="font-mono tabular-nums text-ex-ink">(p = {q.p.toFixed(2)})</span>.
        {q.committee_size ? ` ${fmtPct(q.p)} of ${q.committee_size} rule variants say it matches.` : ''}
      </p>
      <div className="mt-2" aria-hidden="true">
        <div className="relative h-2 rounded-full bg-ex-raised">
          <div className="absolute inset-y-0 left-0 rounded-full bg-cyan-300" style={{ width: `${q.p * 100}%` }} />
          <div className="absolute -top-1 bottom-[-4px] left-1/2 w-0.5 bg-ex-ink" />
        </div>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-[240px_1fr]">
        {ev ? (
          <button type="button" onClick={onOpen} className="block overflow-hidden rounded-lg" aria-label={`View clip: ${ev.summary ?? q.clip_id}`}>
            <EventThumb event={ev} className="aspect-video w-full" />
          </button>
        ) : (
          <div className="grid aspect-video place-items-center rounded-lg bg-ex-bg text-sm text-ex-ink3">Clip {q.clip_id}</div>
        )}
        <div className="min-w-0">
          {ev && (
            <>
              <p className="text-sm text-ex-ink">{ev.summary ?? q.clip_id}</p>
              <div className="mt-1 flex flex-wrap gap-1.5"><SourceBadge source={ev.source} /></div>
              {ev.attribution && <p className="mt-1 text-xs italic text-ex-ink2">{ev.attribution}</p>}
            </>
          )}
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Answer the question">
            <button type="button" className="btn-primary" disabled={busy} onClick={() => onAnswer('pos')}><Icon name="check" /> Yes, this counts</button>
            <button type="button" className="btn" disabled={busy} onClick={() => onAnswer('neg')}><Icon name="cross" /> No, it doesn’t</button>
            <button type="button" className="btn" disabled={busy} onClick={onSkip}>Skip for now</button>
          </div>
          <p className="mt-2 text-xs text-ex-ink3">Your answer is used for learning only. It never feeds the false-alarm calibration.</p>
        </div>
      </div>
    </section>
  )
}
