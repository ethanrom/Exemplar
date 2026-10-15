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
    <div aria-hidden="true" className="relative mt-2 h-6">
      <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded bg-ex-raised" />
      <div className="absolute top-1/2 h-1 -translate-y-1/2 rounded bg-cyan-300" style={{ left: `${ci[0] * 100}%`, width: `${Math.max(0.5, (ci[1] - ci[0]) * 100)}%` }} />
      <div className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-cyan-300" style={{ left: `${ci[0] * 100}%` }} />
      <div className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-cyan-300" style={{ left: `${ci[1] * 100}%` }} />
      <div className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[3px] border-2 border-ex-panel bg-ex-ink" style={{ left: `${recall * 100}%` }} />
    </div>
  )
}

/** Calibration badge (alpha, n, tau) + recall with its 95% Clopper-Pearson interval. */
export function CalibrationPanel({ cal, conceptId }: { cal: Calibration; conceptId: string }) {
  const need = negativesNeeded(cal.alpha)
  return (
    <section aria-labelledby="cal-h" className="card">
      <h2 id="cal-h" className="card-title">False alarms and recall</h2>

      {cal.guarantee ? (
        <div className="mt-3 rounded-lg border border-green-500/60 bg-green-950/60 p-3">
          <p className="flex items-center gap-2 text-base font-semibold text-green-200">
            <Icon name="shield" className="h-5 w-5" /> Guarantee: false-alarm rate ≤ {fmtPct(cal.alpha)} (α = {fmtNum(cal.alpha)})
          </p>
          <dl className="mt-2 grid grid-cols-3 gap-2 text-sm">
            <div><dt className="text-xs text-green-200/80">α</dt><dd className="font-mono tabular-nums text-ex-ink">{fmtNum(cal.alpha)}</dd></div>
            <div><dt className="text-xs text-green-200/80">n random negatives</dt><dd className="font-mono tabular-nums text-ex-ink">{cal.n_random_neg}</dd></div>
            <div><dt className="text-xs text-green-200/80">threshold τ</dt><dd className="font-mono tabular-nums text-ex-ink">{fmtNum(cal.tau)}</dd></div>
          </dl>
          <p className="mt-2 text-sm text-green-100/90">
            The rule fires only when its score is above τ. For clips that behave like your random negatives, at most {fmtPct(cal.alpha)} of non-matching clips will fire.
            {cal.k != null && <> (τ is the {cal.k}th smallest of {cal.n_random_neg} negative scores.)</>}
          </p>
        </div>
      ) : (
        <div className="mt-3 rounded-lg border border-amber-400/60 bg-amber-950/60 p-3">
          <p className="flex items-center gap-2 text-base font-semibold text-amber-100">
            <Icon name="warning" className="h-5 w-5" /> No false-alarm guarantee yet
          </p>
          <p className="mt-1 font-mono text-sm text-amber-50" data-testid="guarantee-message">{guaranteeMessage(cal)}</p>
          <div className="mt-2" aria-hidden="true">
            <div className="h-2 overflow-hidden rounded-full bg-ex-raised">
              <div className="h-full bg-amber-400" style={{ width: `${Math.min(1, cal.n_random_neg / Math.max(1, need)) * 100}%` }} />
            </div>
          </div>
          <p className="mt-2 text-sm text-amber-100/90">
            Until then the rule fires on any score above 0 (τ = {fmtNum(cal.tau)}) and its false-alarm rate is unknown.
          </p>
          <Link href={`/library?calibrate=1&concept=${encodeURIComponent(conceptId)}`} className="btn mt-3">
            <Icon name="shuffle" /> Label 10 random clips
          </Link>
        </div>
      )}

      <div className="mt-4">
        <h3 className="text-sm font-semibold text-ex-ink">Recall on random positives</h3>
        {cal.recall != null && cal.recall_ci95 ? (
          <>
            <p className="mt-1 text-sm text-ex-ink2">
              <span className="text-2xl font-semibold text-ex-ink">{fmtPct(cal.recall)}</span>{' '}
              <span className="whitespace-nowrap">(95% CI {fmtPct(cal.recall_ci95[0])} to {fmtPct(cal.recall_ci95[1])})</span>
              {cal.n_random_pos != null && <> from {cal.n_random_pos} random positive{cal.n_random_pos === 1 ? '' : 's'}</>}
            </p>
            <RecallRange recall={cal.recall} ci={cal.recall_ci95} />
            {(cal.n_random_pos ?? 0) < 10 && (
              <p className="mt-1 text-xs text-ex-ink3">With so few positives the interval is wide. That is the honest answer, not a bug.</p>
            )}
          </>
        ) : (
          <p className="mt-1 text-sm text-ex-ink2">No random positives yet, so recall can’t be estimated. Positives that turn up while you label random clips count here.</p>
        )}
      </div>

      <details className="mt-4 text-sm">
        <summary className="cursor-pointer rounded text-ex-info">Why only random labels?</summary>
        <p className="mt-1 text-ex-ink2">
          The guarantee needs calibration clips drawn uniformly from your history. Clips you pick yourself, or that Exemplar asks about, are not representative of future events, so they teach the rule but are never used to set τ.
          {cal.delta != null && <> Events scoring within {fmtNum(cal.delta)} of τ are re-checked with the stronger model.</>}
        </p>
      </details>
    </section>
  )
}

export function GuaranteeBadge({ cal }: { cal: Calibration }) {
  return cal.guarantee ? (
    <Badge tone="pos" icon="shield">≤ {fmtPct(cal.alpha)} false alarms (n = {cal.n_random_neg}, τ = {fmtNum(cal.tau)})</Badge>
  ) : (
    <Badge tone="warn">No guarantee yet</Badge>
  )
}
