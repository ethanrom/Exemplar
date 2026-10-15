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
  q, busy, onAnswer, onSkip, onOpen, step,
}: {
  step?: number
  q: Question
  busy?: boolean
  onAnswer: (v: 'pos' | 'neg') => void
  onSkip: () => void
  onOpen: () => void
}) {
  const ev = q.event
  const yes = Math.round(q.p * 100)
  return (
    <section aria-labelledby="q-h" className="overflow-hidden rounded-xl border border-ex-accent-line bg-ex-panel">
      <div className="grid gap-5 p-5 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)] sm:p-6 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
        {ev ? (
          <button type="button" onClick={onOpen} className="group block aspect-video w-full self-start overflow-hidden rounded-lg" aria-label={`View clip: ${ev.summary ?? q.clip_id}`}>
            <EventThumb event={ev} className="h-full w-full transition-transform duration-200 group-hover:scale-[1.03]" />
          </button>
        ) : (
          <div className="grid aspect-video place-items-center rounded-lg bg-ex-bg text-sm text-ex-ink3">Clip {q.clip_id}</div>
        )}

        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-xs font-medium text-ex-accent-ink">
            <Icon name="question" className="h-3.5 w-3.5" /> {step != null && <span aria-hidden="true">{step} ·</span>} One question for you
          </p>
          <h3 id="q-h" className="mt-2 text-lg font-semibold leading-snug tracking-tight text-ex-ink">Should this one count?</h3>
          {ev && (
            <p className="mt-1.5 line-clamp-3 text-sm text-ex-ink2">
              {ev.summary ?? q.clip_id}
              <span className="ml-2 inline-block align-middle"><SourceBadge source={ev.source} /></span>
            </p>
          )}

          <div className="mt-5">
            <p className="text-sm font-medium text-ex-ink">
              Your rules disagree on this one <span className="num ml-1 text-xs font-normal text-ex-ink3">p = {q.p.toFixed(2)}</span>
            </p>
            <div aria-hidden="true" className="mt-2.5 flex h-2 gap-0.5 overflow-hidden rounded-full">
              <div className="rounded-l-full bg-ex-accent-ink" style={{ width: `${q.p * 100}%` }} />
              <div className="flex-1 rounded-r-full bg-white/[0.12]" />
            </div>
            <div className="mt-1.5 flex justify-between text-xs text-ex-ink2">
              <span><span className="font-medium tabular-nums text-ex-ink">{yes}%</span> say it matches</span>
              <span><span className="font-medium tabular-nums text-ex-ink">{100 - yes}%</span> say it doesn’t</span>
            </div>
            {q.committee_size ? (
              <p className="mt-1 text-xs text-ex-ink3">Of {q.committee_size.toLocaleString()} rule variants that fit your examples ({fmtPct(q.p)} match).</p>
            ) : null}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-ex-line bg-ex-bg/40 px-5 py-4 sm:px-6">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Answer the question">
          <button type="button" className="btn hover:!border-ex-pos-line hover:!bg-ex-pos-soft" disabled={busy} onClick={() => onAnswer('pos')}>
            <Icon name="check" className="h-4 w-4 text-ex-pos" /> Yes, this counts
          </button>
          <button type="button" className="btn hover:!border-ex-neg-line hover:!bg-ex-neg-soft" disabled={busy} onClick={() => onAnswer('neg')}>
            <Icon name="cross" className="h-4 w-4 text-ex-neg" /> No, it doesn’t
          </button>
          <button type="button" className="btn-ghost" disabled={busy} onClick={onSkip}>Skip for now</button>
        </div>
        <p className="max-w-sm text-xs text-ex-ink3">Your answer is used for learning only. It never feeds the false-alarm calibration.</p>
      </div>
    </section>
  )
}
