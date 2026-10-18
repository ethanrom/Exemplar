'use client'

import { useMemo, useState } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Card } from '@/components/Card.tsx'
import { Collapsible, Disclosure } from '@/components/Disclosure.tsx'
import { Icon } from '@/components/Icon.tsx'
import { Stat, StatStrip } from '@/components/Stat.tsx'
import { LiveRegion } from '@/components/lab/Announce.tsx'
import { fmtPlain, fmtScore, ordinal } from '@/components/lab/core/format.ts'
import { DV } from '@/components/lab/DataValue.tsx'
import { DotStrip } from '@/components/lab/DotStrip.tsx'
import { Slider } from '@/components/lab/Slider.tsx'
import { conformalRank, minNegatives } from '@/lib/synth/conformal.ts'
import type { CalDoc, ClipCard, TraceJson } from '@/lib/data/types.ts'
import { rankedNegatives, recomputeCalibration } from '@/components/lab/core/calibration.ts'
import type { SlimRule } from '../_lib/types.ts'

/** Chapter 5: a bound on false alarms. The recorded sample, the arithmetic of the rank, and what a different sample size would do. */
export function Chapter5({
  cal, rule, traces, cards,
}: { cal: CalDoc; rule: SlimRule; traces: Record<string, TraceJson>; cards: Record<string, ClipCard> }) {
  const re = useMemo(() => recomputeCalibration(rule.dsl_text, cal, traces), [rule.dsl_text, cal, traces])
  const neg = useMemo(() => rankedNegatives(re.scores), [re.scores])
  const c = cal.calibration
  const nReal = c.n_random_neg
  const kReal = c.k as number
  const tauAlpha = re.calibration.tau_alpha
  const title = (a: string) => cards[a]?.title ?? a
  const posScores = re.scores.filter((s) => s.label === 'pos')
  const recalled = posScores.filter((s) => s.score > c.tau).length

  const [alpha, setAlpha] = useState(cal.alpha)
  const [n, setN] = useState(nReal)
  const k = conformalRank(n, alpha)
  const need = minNegatives(alpha)
  const finite = k <= n
  const hypothetical = n !== nReal
  const exact = (n + 1) * (1 - alpha)

  const summary = `Alpha ${fmtPlain(alpha)}, n ${n} random negatives: ${finite ? `the rank k is ${k}, so the threshold is the ${ordinal(k)} smallest score` : `no finite rank exists, it needs at least ${need} random negatives`}.${hypothetical ? ' This sample size is hypothetical.' : ''}`

  return (
    <div className="space-y-8">
      {/* A: recorded */}
      <div data-src="data/calibration/package.json" className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-md font-semibold tracking-tight text-ex-ink">A. Recorded calibration of the deployed package rule</h3>
          <Badge tone="neutral" icon="shield">Immutable: read from the export</Badge>
        </div>
        <p className="max-w-3xl text-sm text-ex-ink2">
          Before the rule was deployed, {cal.provenance.random_labels} clips were drawn at random from the library (through the random-sample endpoint, disjoint from the examples the rule was taught from and from the Lab’s curated clips) and labelled. The rule was scored on each. Its alert threshold τ comes from the random <em>negatives</em>: the k-th smallest of their n scores, where k = ⌈(n + 1)(1 − α)⌉.
        </p>

        <StatStrip label="Recorded calibration" cols="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="α" value={<DV src="calibration/package.json#alpha">{fmtPlain(cal.alpha)}</DV>} hint="target false-alarm rate" />
          <Stat label="Random negatives n" value={<DV src="calibration/package.json#calibration.n_random_neg">{nReal}</DV>} hint="scored for the threshold" />
          <Stat label="Rank k" value={<DV src="calibration/package.json#calibration.k">{kReal}</DV>} hint={`⌈(${nReal} + 1) × ${fmtPlain(1 - cal.alpha, 2)}⌉`} />
          <Stat label="τ_α, the k-th smallest" value={<DV src="lib/synth/conformal.ts">{tauAlpha !== null ? fmtScore(tauAlpha) : 'none'}</DV>} hint="before the floor at 0" />
          <Stat label="τ, the alert threshold" value={<DV src="calibration/package.json#calibration.tau">{fmtPlain(c.tau)}</DV>} hint="max(τ_α, 0): fire if score > τ" />
          <Stat label="Recall on random positives" value={<DV src="calibration/package.json#calibration.recall">{c.recall !== null ? `${recalled} of ${posScores.length}` : 'n/a'}</DV>} hint={c.recall_ci95 ? `95% CI ${fmtPlain(c.recall_ci95[0])} to ${fmtPlain(c.recall_ci95[1])}` : undefined} />
        </StatStrip>

        <div data-src="calibration/package.json#random, lib/dsl evaluator">
          <DotStrip
            label={`Scores of the ${cal.random.length} random clips: ${neg.length} negatives and ${posScores.length} positives. The ${ordinal(kReal)} smallest negative score is ${tauAlpha !== null ? fmtScore(tauAlpha) : 'undefined'}; the threshold τ is ${fmtPlain(c.tau)}.`}
            dots={re.scores.map((s) => ({ id: s.alias, score: s.score, label: s.label, rank: neg.find((q) => q.alias === s.alias)?.rank }))}
            kth={kReal}
            tauAlpha={tauAlpha}
            tau={c.tau}
          />
          <p className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ex-ink3">
            <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-full bg-ex-neg" />random negative (circle)</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm bg-ex-pos" />random positive (square)</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 rounded-full bg-ex-neg ring-2 ring-ex-ink ring-offset-1 ring-offset-ex-bg" />the k-th negative, {ordinal(kReal)} of {nReal}</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-3 w-0.5 bg-ex-warn" />τ</span>
          </p>
        </div>
        <p className="max-w-3xl text-sm text-ex-ink2">
          The {ordinal(kReal)} of the {nReal} negative scores is <span className="font-mono tabular-nums">{tauAlpha !== null ? fmtScore(tauAlpha) : 'undefined'}</span>. Scores below zero never fire a rule anyway, so τ is floored at zero: the rule fires when its score is above <span className="font-mono tabular-nums">{fmtPlain(c.tau)}</span>.
        </p>

        <Disclosure title="Scope of the recorded bound">
          <p>Stage-1 decisions on fast-perception facts, for events exchangeable with the random sample. The recorded rule and its calibration are not changed by anything on this page.</p>
          <p>The same calibration, recomputed here from the recorded facts: <strong className="font-medium text-ex-ink">{re.differences.length === 0 ? 'identical' : `differs in ${re.differences.join(', ')}`}</strong> ({re.scoresIdentical} of {re.scores.length} scores and every calibration field compared).</p>
        </Disclosure>

        <Collapsible summary="The random sample as a table">
          <div className="overflow-x-auto" role="region" tabIndex={0} aria-label="Random sample scores (scrolls sideways on narrow screens)">
            <table className="w-full min-w-[420px] text-left text-sm">
              <caption className="sr-only">The random clips, their label and the deployed rule’s score on each. Negatives are listed in rank order.</caption>
              <thead>
                <tr className="text-xs text-ex-ink3"><th scope="col" className="py-1.5 pr-3 font-medium">Rank among negatives</th><th scope="col" className="py-1.5 pr-3 font-medium">Clip</th><th scope="col" className="py-1.5 pr-3 font-medium">Label</th><th scope="col" className="py-1.5 text-right font-medium">Score</th></tr>
              </thead>
              <tbody>
                {neg.map((s) => (
                  <tr key={s.alias} className="border-t border-ex-line">
                    <td className="py-1.5 pr-3 font-mono tabular-nums">{s.rank}{s.rank === kReal && <span className="ml-1.5 font-sans text-xs text-ex-warn">k-th: becomes τ_α</span>}</td>
                    <td className="py-1.5 pr-3 text-ex-ink2">{title(s.alias)}</td>
                    <td className="py-1.5 pr-3">no</td>
                    <td className="py-1.5 text-right font-mono tabular-nums">{fmtScore(s.score)}</td>
                  </tr>
                ))}
                {posScores.map((s) => (
                  <tr key={s.alias} className="border-t border-ex-line">
                    <td className="py-1.5 pr-3 text-ex-ink3">n/a</td>
                    <td className="py-1.5 pr-3 text-ex-ink2">{title(s.alias)}</td>
                    <td className="py-1.5 pr-3">yes</td>
                    <td className="py-1.5 text-right font-mono tabular-nums">{fmtScore(s.score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Collapsible>
      </div>

      {/* B: arithmetic */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-md font-semibold tracking-tight text-ex-ink">B. The arithmetic of the rank</h3>
          <Badge tone="info" icon="sliders">Exploration: change α and n</Badge>
        </div>
        <p className="max-w-3xl text-sm text-ex-ink2">
          The threshold is the k-th smallest of the n negative scores, with k = ⌈(n + 1)(1 − α)⌉. Under exchangeability, a new negative event then scores above the threshold with probability at most α. The sliders change only the arithmetic: no scores are drawn beyond the {nReal} real ones.
        </p>
        <Card padding="md">
          <div className="grid gap-5 sm:grid-cols-2">
            <Slider
              label="α, the false-alarm rate to aim for"
              value={alpha}
              min={0.01}
              max={0.5}
              step={0.01}
              pageStep={0.05}
              onChange={(v) => setAlpha(+v.toFixed(2))}
              valueText={(v) => `alpha ${fmtPlain(v)}`}
              display={fmtPlain(alpha)}
              marks={[{ value: cal.alpha, label: 'recorded', tone: 'warn' }]}
            />
            <Slider
              label="n, the number of random negatives"
              value={n}
              min={0}
              max={100}
              step={1}
              pageStep={10}
              onChange={setN}
              valueText={(v) => `${v} random negatives`}
              display={String(n)}
              marks={[{ value: nReal, label: 'recorded', tone: 'warn' }]}
            />
          </div>
          <div className="mt-4 border-t border-ex-line pt-4">
            <p className="font-mono text-sm tabular-nums text-ex-ink">
              k = ⌈({n} + 1) × (1 − {fmtPlain(alpha)})⌉ = ⌈{fmtPlain(exact, 4)}⌉ = <span className="font-semibold">{k}</span>
            </p>
            {finite ? (
              <p className="mt-1.5 text-sm text-ex-ink2">The threshold would be the <strong className="font-medium text-ex-ink">{ordinal(k)}</strong> smallest of {n} negative scores.</p>
            ) : (
              <p className="mt-1.5 flex items-start gap-2 text-sm text-ex-warn"><Icon name="warning" className="mt-0.5 h-4 w-4 shrink-0" /><span>With fewer than ⌈1/α⌉ − 1 = {need} random negatives no finite calibration rank exists: k = {k} is more than n = {n}.</span></p>
            )}
            {hypothetical ? (
              <p className="mt-2 flex items-start gap-2 text-sm text-ex-ink2"><Badge tone="info" icon="info">Hypothetical sample size</Badge><span>The recorded sample has {nReal} random negatives. Nothing is drawn for n = {n}, so there are no dots for it.</span></p>
            ) : alpha === cal.alpha ? (
              <p className="mt-2 text-sm text-ex-ink2">These are the recorded values: k = {kReal}, the {ordinal(kReal)} of {nReal} negatives, as in part A.</p>
            ) : (
              <p className="mt-2 text-sm text-ex-ink2">The sample size is the recorded one ({nReal} negatives); the recorded α is {fmtPlain(cal.alpha)}, so the recorded rank is {kReal}.</p>
            )}
            <p className="mt-2 text-xs text-ex-ink3">Smaller α asks for fewer false alarms and needs more random negatives: the fewest that give a finite rank at α = {fmtPlain(alpha)} is {need}.</p>
          </div>
        </Card>
      </div>
      <LiveRegion text={summary} />
    </div>
  )
}
