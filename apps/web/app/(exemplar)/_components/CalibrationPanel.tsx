'use client'

import Link from 'next/link'
import { fmtNum, fmtPct, negativesNeeded } from '../_lib/format'
import type { Calibration } from '../_lib/types'
import { Icon } from './Icon'
import { Badge } from './ui'

/** The exact wording required when the guarantee isn't available yet. Prefers the engine's own message. */
export function guaranteeMessage(c: Calibration): string {
  return c.message || `guarantee needs ≥ ${negativesNeeded(c.alpha)} random negatives (have ${c.n_random_neg})`
}

function RecallRange({ recall, ci }: { recall: number; ci: [number, number] }) {
  return (
    <div aria-hidden="true" className="mt-3">
      <div className="relative h-5">
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/[0.1]" />
        <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-ex-accent/60" style={{ left: `${ci[0] * 100}%`, width: `${Math.max(0.8, (ci[1] - ci[0]) * 100)}%` }} />
        <div className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-ex-accent-ink" style={{ left: `${ci[0] * 100}%` }} />
        <div className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-ex-accent-ink" style={{ left: `${ci[1] * 100}%` }} />
        <div className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px] border-2 border-ex-panel bg-ex-ink" style={{ left: `${recall * 100}%` }} />
      </div>
      <div className="mt-0.5 flex justify-between text-xs tabular-nums text-ex-ink3"><span>0%</span><span>50%</span><span>100%</span></div>
    </div>
  )
}

/**
 * The calibration story in one band: the false-alarm guarantee (alpha, n, tau) on the left, recall with its
 * 95% Clopper-Pearson interval on the right.
 */
export function CalibrationPanel({ cal, conceptId }: { cal: Calibration; conceptId: string }) {
  const need = negativesNeeded(cal.alpha)
  const have = cal.n_random_neg
  return (
    <section aria-labelledby="cal-h" className="rounded-xl border border-ex-line bg-ex-panel">
      <h2 id="cal-h" className="sr-only">False alarms and recall</h2>
      <div className="grid divide-y divide-ex-line lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:divide-x lg:divide-y-0">
        <div className="p-5 sm:p-6">
          {cal.guarantee ? (
            <>
              <p className="flex items-center gap-2 text-xs font-medium text-ex-pos"><Icon name="shield" className="h-4 w-4" /> Guarantee holds</p>
              <p className="mt-2 text-lg font-semibold tracking-tight text-ex-ink">False alarms ≤ {fmtPct(cal.alpha)}</p>
              <p className="mt-1 font-mono text-xs tabular-nums text-ex-ink2">
                n = {have} random negatives <span className="text-ex-ink3">·</span> τ = {fmtNum(cal.tau)} <span className="text-ex-ink3">·</span> α = {fmtNum(cal.alpha)}
              </p>
              <p className="mt-3 text-sm text-ex-ink2">
                The rule fires only when its score is above τ. For clips that behave like your random negatives, at most {fmtPct(cal.alpha)} of non-matching clips will fire.
                {cal.k != null && <> (τ is the {cal.k}th smallest of {have} negative scores.)</>}
              </p>
            </>
          ) : (
            <>
              <p className="flex items-center gap-2 text-xs font-medium text-ex-warn"><Icon name="warning" className="h-4 w-4" /> No false-alarm guarantee yet</p>
              <p className="mt-2 font-mono text-sm text-ex-ink" data-testid="guarantee-message">{guaranteeMessage(cal)}</p>
              <div className="mt-3 max-w-sm" aria-hidden="true">
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.1]">
                  <div className="h-full rounded-full bg-ex-warn" style={{ width: `${Math.min(1, have / Math.max(1, need)) * 100}%` }} />
                </div>
                <p className="mt-1.5 text-xs tabular-nums text-ex-ink3">{have} of {need} random negatives</p>
              </div>
              <p className="mt-3 text-sm text-ex-ink2">
                Until then the rule fires on any score above 0 (τ = {fmtNum(cal.tau)}) and its false-alarm rate is unknown.
              </p>
              <Link href={`/library?calibrate=1&concept=${encodeURIComponent(conceptId)}`} className="btn mt-4">
                <Icon name="shuffle" /> Label 10 random clips
              </Link>
            </>
          )}
        </div>

        <div className="p-5 sm:p-6">
          <h3 className="text-xs font-medium text-ex-ink3">Recall on random positives</h3>
          {cal.recall != null && cal.recall_ci95 ? (
            <>
              <p className="mt-2 flex flex-wrap items-baseline gap-x-2">
                <span className="text-2xl font-semibold tracking-tight tabular-nums text-ex-ink">{fmtPct(cal.recall)}</span>
                <span className="whitespace-nowrap text-sm tabular-nums text-ex-ink2">95% CI {fmtPct(cal.recall_ci95[0])} to {fmtPct(cal.recall_ci95[1])}</span>
              </p>
              <RecallRange recall={cal.recall} ci={cal.recall_ci95} />
              <p className="mt-2 text-xs text-ex-ink3">
                From {cal.n_random_pos ?? 0} random positive{cal.n_random_pos === 1 ? '' : 's'}.
                {(cal.n_random_pos ?? 0) < 10 && ' With so few the interval is wide: that is the honest answer, not a bug.'}
              </p>
            </>
          ) : (
            <p className="mt-2 text-sm text-ex-ink2">No random positives yet, so recall can’t be estimated. Positives that turn up while you label random clips count here.</p>
          )}
        </div>
      </div>
      <details className="group border-t border-ex-line px-5 py-3 text-sm sm:px-6">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded text-ex-ink2 hover:text-ex-ink [&::-webkit-details-marker]:hidden">
          <Icon name="chevron-right" className="h-3.5 w-3.5 transition-transform group-open:rotate-90" /> Why only random labels?
        </summary>
        <p className="mt-2 max-w-3xl text-ex-ink2">
          The guarantee needs calibration clips drawn uniformly from your history. Clips you pick yourself, or that Exemplar asks about, are not representative of future events, so they teach the rule but are never used to set τ.
          {cal.delta != null && <> Events scoring within {fmtNum(cal.delta)} of τ are re-checked with the stronger model.</>}
        </p>
      </details>
    </section>
  )
}

export function GuaranteeBadge({ cal, wrap = false }: { cal: Calibration; wrap?: boolean }) {
  if (!wrap) {
    return cal.guarantee ? (
      <Badge tone="pos" icon="shield">False alarms ≤ {fmtPct(cal.alpha)} · n = {cal.n_random_neg} random negatives · τ = {fmtNum(cal.tau)}</Badge>
    ) : (
      <Badge tone="warn">No guarantee yet</Badge>
    )
  }
  // A badge that may wrap onto two lines (used in narrow stat cells).
  return cal.guarantee ? (
    <span className="inline-flex items-start gap-1.5 rounded bg-ex-pos-soft px-2 py-1 text-xs font-medium leading-4 text-ex-pos">
      <Icon name="shield" className="mt-px h-3 w-3" />
      <span>False alarms ≤ {fmtPct(cal.alpha)} · n = {cal.n_random_neg} random negatives · τ = {fmtNum(cal.tau)}</span>
    </span>
  ) : (
    <span className="inline-flex items-start gap-1.5 rounded bg-ex-warn-soft px-2 py-1 text-xs font-medium leading-4 text-ex-warn">
      <Icon name="warning" className="mt-px h-3 w-3" />
      <span>No guarantee yet</span>
    </span>
  )
}
