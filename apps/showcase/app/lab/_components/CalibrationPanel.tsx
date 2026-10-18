'use client'

import { useMemo } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Card } from '@/components/Card.tsx'
import { Disclosure } from '@/components/Disclosure.tsx'
import { Stat, StatStrip } from '@/components/Stat.tsx'
import { recomputeCalibration } from '@/components/lab/core/calibration.ts'
import { fmtPlain, fmtScore, ordinal } from '@/components/lab/core/format.ts'
import { DV } from '@/components/lab/DataValue.tsx'
import { calibrateScores } from '@/lib/synth/conformal.ts'
import type { CalDoc, TraceJson } from '@/lib/data/types.ts'
import type { Mode } from '../_lib/types.ts'

export type CalibrationCase =
  | { kind: 'recorded' } // the unchanged deployed rule of P1
  | { kind: 'exploratory' } // any other rule, on the package random set
  | { kind: 'no-random-labels' } // the user's labels contradict the recorded package labels

/** Which of the three panels applies (SPEC 7.3). */
export function calibrationCase(opts: {
  mode: Mode
  selectedDsl: string | null
  deployedDsl: string
  contradiction: boolean
  recordedMessage: string | null
}): CalibrationCase {
  if (opts.mode === 'p1-playground' && opts.selectedDsl === opts.deployedDsl) return { kind: 'recorded' }
  if (opts.mode === 'free' && opts.contradiction) return { kind: 'no-random-labels' }
  return { kind: 'exploratory' }
}

/** Calibration of the selected rule: the recorded bound only on the unchanged deployed rule, everything else is labelled as exploratory. */
export function CalibrationPanel({
  c, cal, selectedDsl, traces, titleOf,
}: { c: CalibrationCase; cal: CalDoc; selectedDsl: string | null; traces: Record<string, TraceJson> | null; titleOf: (alias: string) => string }) {
  const re = useMemo(
    () => (selectedDsl && traces && (c.kind === 'recorded' || c.kind === 'exploratory') ? recomputeCalibration(selectedDsl, cal, traces) : null),
    [selectedDsl, traces, cal, c.kind],
  )
  const rec = cal.calibration

  if (c.kind === 'no-random-labels') {
    const msg = calibrateScores([], [], cal.alpha).message as string
    return (
      <Card padding="md" tone="warn">
        <Badge tone="warn" icon="warning">Exploratory recalibration, not a guarantee</Badge>
        <p className="mt-2 text-sm text-ex-ink">Your labels contradict the recorded labels of this concept on a clip used here, so the recorded random labels no longer apply.</p>
        <p className="mt-2 font-mono text-sm text-ex-ink" data-src="lib/synth/conformal.ts">no random labels for this concept: {msg}</p>
      </Card>
    )
  }
  if (!re) return <div role="status" className="skeleton h-28" aria-label="Calibrating" />
  const calc = re.calibration
  const neg = re.scores.filter((s) => s.label === 'neg')
  const pos = re.scores.filter((s) => s.label === 'pos')
  const recalled = pos.filter((s) => s.score > calc.tau).length

  if (c.kind === 'recorded') {
    return (
      <Card padding="md" data-src="data/calibration/package.json">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="pos" icon="shield">Recorded calibration</Badge>
          <Badge tone="neutral" icon="check">{re.differences.length === 0 ? 'Recomputed here: identical' : `Recomputed here: differs in ${re.differences.join(', ')}`}</Badge>
        </div>
        <StatStrip label="Recorded calibration of the deployed package rule" cols="mt-3 grid-cols-2 sm:grid-cols-5">
          <Stat label="α" value={<DV src="calibration/package.json#alpha">{fmtPlain(cal.alpha)}</DV>} />
          <Stat label="Random negatives n" value={<DV src="calibration/package.json#n_random_neg">{rec.n_random_neg}</DV>} />
          <Stat label="Rank k" value={<DV src="calibration/package.json#k">{rec.k}</DV>} hint={`${ordinal(rec.k as number)} smallest`} />
          <Stat label="τ" value={<DV src="calibration/package.json#tau">{fmtPlain(rec.tau)}</DV>} hint="fire if score > τ" />
          <Stat label="Recall" value={<DV src="calibration/package.json#recall">{pos.length ? `${recalled} of ${pos.length}` : 'n/a'}</DV>} hint={rec.recall_ci95 ? `95% CI ${fmtPlain(rec.recall_ci95[0])} to ${fmtPlain(rec.recall_ci95[1])}` : undefined} />
        </StatStrip>
        <dl className="mt-3 space-y-1.5 text-sm text-ex-ink2">
          <div><dt className="inline font-medium text-ex-ink">Scope. </dt><dd className="inline">Stage-1 decisions on fast-perception facts, for events exchangeable with the random sample.</dd></div>
          <div><dt className="inline font-medium text-ex-ink">Random labels. </dt><dd className="inline"><DV src="calibration/package.json#provenance">{cal.provenance.random_labels}</DV> clips drawn at random through the random-sample endpoint and labelled; they are disjoint from this run’s examples and from the Lab’s curated clips (checked at export). {neg.length} are negatives, {pos.length} positives.</dd></div>
        </dl>
      </Card>
    )
  }

  // exploratory
  return (
    <Card padding="md" tone="warn" data-src="lib/synth/conformal.ts on data/calibration/package.json#random">
      <Badge tone="warn" icon="warning">Exploratory recalibration, not a guarantee</Badge>
      <StatStrip label="Exploratory recalibration of the selected rule" cols="mt-3 grid-cols-2 sm:grid-cols-4">
        <Stat label="α" value={<DV src="calibration/package.json#alpha">{fmtPlain(calc.alpha)}</DV>} />
        <Stat label="Random negatives n" value={<DV src="lib/synth/conformal.ts">{calc.n_random_neg}</DV>} />
        <Stat label="Rank k" value={<DV src="lib/synth/conformal.ts">{calc.k ?? 'none'}</DV>} hint={calc.k ? `${ordinal(calc.k)} smallest` : calc.message ?? undefined} />
        <Stat label="τ" value={<DV src="lib/synth/conformal.ts">{fmtPlain(calc.tau)}</DV>} hint={calc.tau_alpha !== null ? `τ_α ${fmtScore(calc.tau_alpha)}, floored at 0` : undefined} />
      </StatStrip>
      <Disclosure title="How it was computed" as="h3" className="mt-3">
        <p>The selected rule was scored here on the same {re.scores.length} randomly drawn clips as the recorded calibration ({neg.length} negatives, {pos.length} positives), and k and τ were taken from its negative scores. On the positives it fires on {recalled} of {pos.length}.</p>
        <p>Negatives with the highest scores: {[...neg].sort((a, b) => b.score - a.score).slice(0, 3).map((s) => `${titleOf(s.alias)} (${fmtScore(s.score)})`).join('; ') || 'none'}.</p>
      </Disclosure>
    </Card>
  )
}
