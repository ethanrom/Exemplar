'use client'

import { useMemo, useState } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Card } from '@/components/Card.tsx'
import { cx } from '@/components/cx.ts'
import { Icon } from '@/components/Icon.tsx'
import { ScrollRegion } from '@/components/ScrollRegion.tsx'
import { fmtScore } from '@/components/lab/core/format.ts'
import { asTrace, parseCached } from '@/components/lab/core/rules.ts'
import { DV } from '@/components/lab/DataValue.tsx'
import { WitnessTimeline } from '@/components/lab/WitnessTimeline.tsx'
import { witness } from '@/lib/dsl/index.ts'
import type { ClipCard, TraceJson } from '@/lib/data/types.ts'
import type { BacktestRow, ClassTally, CrossCheck } from '../_lib/backtest.ts'

/** What a clip's detail shows: the whole frame sheet (or, without frames, the facts) and the witness of the selected rule. */
function ClipDetail({ card, trace, dslText, tau }: { card: ClipCard; trace: TraceJson; dslText: string; tau: number }) {
  const w = useMemo(() => witness(parseCached(dslText), asTrace(trace)), [dslText, trace])
  const matched = w.score > tau
  return (
    <Card padding="sm" className="mt-3 space-y-3" data-src={`data/traces/${card.alias}.json, lib/dsl witness`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-ex-ink">{card.title}</p>
        <Badge tone={matched ? 'pos' : 'neutral'} icon={matched ? 'check' : 'minus'}>{matched ? 'matched' : 'not matched'}</Badge>
      </div>
      <p className="text-xs text-ex-ink2">{card.summary}</p>
      {card.sheet ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={card.sheet} alt={`Frame sheet: the 16 sampled frames of ${card.title}, in time order, left to right and top to bottom`} loading="lazy" width={1280} height={720} className="aspect-video w-full max-w-3xl rounded-md border border-ex-line" />
      ) : (
        <div className="rounded-md border border-ex-line bg-ex-bg p-3 text-xs text-ex-ink2">
          <p className="font-medium text-ex-ink">Ring Developer Playground recording: frames not shown in this build.</p>
          <p className="mt-1">Entities Claude saw: {trace.entities.map((e) => `${e.id} (${e.type}${e.attrs.length ? `: ${e.attrs.join(', ').replaceAll('_', ' ')}` : ''})`).join('; ') || 'none'}.</p>
          <p className="mt-1">{trace.frames.length} sampled frames, {trace.frames.reduce((n, f) => n + f.facts.length, 0)} facts in total.</p>
        </div>
      )}
      <WitnessTimeline witness={{ ...w, tau, margin: w.score - tau }} durationMs={trace.duration_ms} compact title={matched ? 'Why it matched' : 'Closest attempt: why it did not match'} />
    </Card>
  )
}

/** The selected rule scored on the whole library, by class, with the list of clips. */
export function Backtest({
  rows, tallies, cards, traces, dslText, tau, cross, crossSource,
}: {
  rows: readonly BacktestRow[] | null
  tallies: readonly ClassTally[]
  cards: ReadonlyMap<string, ClipCard>
  traces: Record<string, TraceJson> | null
  dslText: string | null
  tau: number
  cross: CrossCheck | null
  crossSource: string | null
}) {
  const [open, setOpen] = useState<string | null>(null)
  if (!dslText) return <p className="text-sm text-ex-ink2">Select a candidate to score it on the library.</p>
  if (!rows || !traces) return <div role="status" className="skeleton h-24" aria-label="Scoring the rule on the library" />
  const card = open ? cards.get(open) : undefined
  return (
    <div data-src="lib/dsl evaluator on data/traces/*.json" className="space-y-3">
      <ul className="grid gap-2 sm:grid-cols-2" aria-label="Clips matched, by class">
        {tallies.map((t) => (
          <li key={t.cls} className="rounded-lg border border-ex-line bg-ex-panel px-3 py-2">
            <p className="text-xs text-ex-ink3">{t.label}</p>
            <p className="mt-0.5 flex items-baseline gap-2 text-sm text-ex-ink"><span className="font-mono text-lg font-semibold tabular-nums"><DV src="lib/dsl evaluator">{t.matched} of {t.total}</DV></span> matched</p>
            <div aria-hidden="true" className="mt-1 h-1.5 overflow-hidden rounded-full bg-ex-line2"><div className="h-full bg-ex-accent-ink" style={{ width: `${(t.matched / t.total) * 100}%` }} /></div>
          </li>
        ))}
      </ul>
      {cross ? (
        <p className="flex items-start gap-2 text-xs text-ex-ink2">
          <Icon name={cross.differences.length === 0 ? 'check' : 'cross'} className={cx('mt-0.5 h-3.5 w-3.5 shrink-0', cross.differences.length === 0 ? 'text-ex-pos' : 'text-ex-neg')} />
          <span>{cross.differences.length === 0 ? `Cross-check: all ${cross.checked} scores equal the engine’s (${crossSource}).` : `Cross-check: ${cross.differences.length} of ${cross.checked} scores differ from the engine’s (${crossSource}): ${cross.differences.slice(0, 3).map((d) => `${d.alias} ${fmtScore(d.mine)} vs ${fmtScore(d.engine)}`).join('; ')}.`}</span>
        </p>
      ) : (
        <p className="text-xs text-ex-ink3">Not cross-checked against the engine: its scores for this rule are not loaded.</p>
      )}
      <ScrollRegion label="Every library clip with the rule’s score" className="max-h-72 rounded-lg border border-ex-line">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Every clip of the library with the selected rule’s score and whether it matched. Select a clip to see its frames and the rule’s witness.</caption>
          <thead className="sticky top-0 bg-ex-panel text-xs text-ex-ink3">
            <tr><th scope="col" className="px-3 py-2 font-medium">Clip</th><th scope="col" className="px-2 py-2 text-right font-medium">Score</th><th scope="col" className="px-3 py-2 font-medium">Result</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.alias} className={cx('border-t border-ex-line', open === r.alias && 'bg-ex-accent-soft')}>
                <th scope="row" className="px-3 py-1.5 font-normal">
                  <button type="button" aria-expanded={open === r.alias} onClick={() => setOpen(open === r.alias ? null : r.alias)} className="text-left text-ex-ink underline decoration-ex-line2 underline-offset-2 hover:decoration-ex-ink">
                    {r.title}
                  </button>
                </th>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ex-ink2">{fmtScore(r.score)}</td>
                <td className="px-3 py-1.5"><span className={cx('inline-flex items-center gap-1 text-xs', r.matched ? 'text-ex-pos' : 'text-ex-ink3')}><Icon name={r.matched ? 'check' : 'minus'} className="h-3 w-3" />{r.matched ? 'matched' : 'not matched'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>
      {card && traces[card.alias] && <ClipDetail card={card} trace={traces[card.alias] as TraceJson} dslText={dslText} tau={tau} />}
    </div>
  )
}
