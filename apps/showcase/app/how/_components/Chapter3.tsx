'use client'

import { useMemo, useState } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Button } from '@/components/Button.tsx'
import { Card } from '@/components/Card.tsx'
import { Dsl } from '@/components/CodeBlock.tsx'
import { cx } from '@/components/cx.ts'
import { Icon } from '@/components/Icon.tsx'
import { LiveRegion } from '@/components/lab/Announce.tsx'
import { clipLength, holdBox, holdsForShape, holdTicks, placeD, scoreAt } from '@/components/lab/core/hold.ts'
import type { HoldExample } from '@/components/lab/core/hold.ts'
import { fmtPlain, fmtScore } from '@/components/lab/core/format.ts'
import { parseCached } from '@/components/lab/core/rules.ts'
import { DV } from '@/components/lab/DataValue.tsx'
import { Slider } from '@/components/lab/Slider.tsx'
import type { ClipCard, TraceJson } from '@/lib/data/types.ts'
import type { HowRun } from '../_lib/types.ts'

const TICK_STEPS = [1, 2, 5, 10]

function niceStep(max: number): number {
  return TICK_STEPS.find((s) => max / s <= 9) ?? 10
}

/** One example: its track on the shared seconds axis. */
function Track({
  domain, box, d, recordedD, tick, window: win, frames,
}: {
  domain: number
  box: { lo: number; hi: number }
  d: number
  recordedD: number
  tick: { sup: number | null; label: 'pos' | 'neg' }
  window: [number, number] | null
  frames: { t: number; holds: boolean }[]
}) {
  const x = (t: number) => `${(Math.min(Math.max(t, 0), domain) / domain) * 100}%`
  return (
    <div aria-hidden="true" className="relative h-8 overflow-hidden rounded-md border border-ex-line bg-ex-bg">
      <div className="absolute inset-y-0 border-x border-dashed border-ex-accent-line bg-ex-accent-soft" style={{ left: x(box.lo), width: `${((box.hi - box.lo) / domain) * 100}%` }} />
      {win && <div className="absolute top-1 h-6 rounded-sm border border-ex-accent-ink bg-ex-accent/40" style={{ left: x(win[0]), width: `${Math.max(((win[1] - win[0]) / domain) * 100, 0.4)}%` }} />}
      <div className="absolute inset-y-0 w-px bg-ex-warn" style={{ left: x(recordedD) }} />
      {frames.map((f) => (
        <span
          key={f.t}
          className={cx('absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full', f.holds ? 'bg-ex-pos' : 'border-2 border-ex-neg bg-ex-bg')}
          style={{ left: x(f.t) }}
        />
      ))}
      {tick.sup !== null && (
        <span
          className={cx('absolute inset-y-0.5 w-1.5 -translate-x-1/2 rounded-sm ring-2 ring-ex-bg', tick.label === 'pos' ? 'bg-ex-pos' : 'bg-ex-neg')}
          style={{ left: x(tick.sup) }}
        />
      )}
      <div className="absolute inset-y-0 w-0.5 bg-ex-ink" style={{ left: x(d) }} />
    </div>
  )
}

/** Chapter 3: why d is 15 s. The solver's range of d on a number line, and a slider that re-scores every example. */
export function Chapter3({ runs, traces, cards }: { runs: HowRun[]; traces: Record<string, TraceJson>; cards: Record<string, ClipCard> }) {
  const run = runs[0] as HowRun
  const slug = run.slug

  const model = useMemo(() => {
    const sketch = parseCached(run.rule.sketch_text)
    const shape = holdsForShape(sketch)
    if (!shape) return null
    const exs: HoldExample[] = run.examples.map((e) => ({ alias: e.alias, label: e.label, weight: e.weight, trace: traces[e.alias] as TraceJson }))
    const ticks = holdTicks(sketch, exs, run.rule.margin)
    const satisfied = new Set(exs.filter((e) => !run.rule.violations.includes(e.alias)).map((e) => e.alias))
    const domainHi = clipLength(exs)
    const box = holdBox(ticks, satisfied, domainHi)
    const placed = placeD(box)
    const recordedD = run.rule.holes[shape.hole] as number
    const exported = run.rule.box?.[shape.hole] as [number, number] | undefined
    const max = Math.ceil(domainHi * 2) / 2
    return { sketch, shape, exs, ticks, box, placed, recordedD, exported, max }
  }, [run, traces])

  const [d, setD] = useState<number>(model?.recordedD ?? 15)

  const rows = useMemo(() => {
    if (!model) return []
    return model.exs.map((ex, i) => {
      const s = scoreAt(model.sketch, ex, d)
      const tick = model.ticks[i] as (typeof model.ticks)[number]
      return { ex, s, tick, card: cards[ex.alias], provenance: run.examples[i]?.provenance }
    })
  }, [model, d, cards, run.examples])

  if (!model) return null

  const rightRows = rows.filter((r) => r.s.right)
  const wTotal = rows.reduce((a, r) => a + r.ex.weight, 0)
  const wRight = rightRows.reduce((a, r) => a + r.ex.weight, 0)
  const margin = rightRows.length === rows.length ? Math.min(...rows.map((r) => Math.abs(r.s.score))) : null
  const pos = rows.filter((r) => r.ex.label === 'pos')
  const neg = rows.filter((r) => r.ex.label === 'neg')
  const posRight = pos.filter((r) => r.s.right).length
  const negRight = neg.filter((r) => r.s.right).length
  const atRecorded = d === model.recordedD
  const ticksAxis: number[] = []
  const step = niceStep(model.max)
  for (let t = 0; t <= model.max; t += step) ticksAxis.push(t)
  const x = (t: number) => `${(t / model.max) * 100}%`
  const boxMatches = model.exported !== undefined && Math.abs(model.exported[0] - model.box.lo) < 1e-9 && Math.abs(model.exported[1] - model.box.hi) < 1e-9
  const placedMatches = model.placed.snapped === model.recordedD
  const violated = run.rule.violations

  const summary = `d = ${fmtPlain(d)} seconds. ${posRight} of ${pos.length} yes examples matched, ${negRight} of ${neg.length} no examples rejected. Weighted agreement ${fmtPlain(wRight)} of ${fmtPlain(wTotal)}.${margin !== null ? ` Margin ${fmtPlain(margin)}.` : ' Some examples are on the wrong side, so there is no margin.'}`

  return (
    <div data-src={`data/runs/${run.slug}.json, data/rules/${run.rule.slug}.json, lib/dsl evaluator`} className="space-y-5">
      <Card padding="sm">
        <p className="text-xs font-medium text-ex-ink3">The recorded sketch and the rule the solver made from it</p>
        <pre className="mt-1.5 whitespace-pre-wrap break-words font-mono text-xs leading-5"><code><Dsl text={run.rule.sketch_text} /></code></pre>
        <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-xs leading-5"><code><Dsl text={run.rule.dsl_text} /></code></pre>
        <p className="mt-2 text-sm text-ex-ink2">{run.rule.english}</p>
      </Card>

      <div>
        <h3 className="text-md font-semibold tracking-tight text-ex-ink">Why <DV src={`rules/${run.rule.slug}.json#holes`}>{fmtPlain(model.recordedD)} s</DV>?</h3>
        <p className="mt-1 max-w-3xl text-sm text-ex-ink2">
          Each row is one example. The dots are the sampled frames: a filled dot where the part of the rule inside the &ldquo;continuously&rdquo; holds, a ring where it does not. The thick tick is the longest stretch the example holds for. A yes example needs d at or below its tick; a no example needs d above its tick (or no tick at all). The shaded band is the range of d that keeps the examples right, as computed here; the amber line is the value the engine recorded.
        </p>
      </div>

      <div className="rounded-xl border border-ex-line bg-ex-panel p-3 sm:p-4">
        {/* shared axis */}
        <div aria-hidden="true" className="relative mb-1 h-5 text-xs text-ex-ink3">
          {ticksAxis.map((t) => (
            <span key={t} className={cx('absolute font-mono tabular-nums', t === 0 ? '' : '-translate-x-1/2')} style={{ left: x(t) }}>{t}{t === 0 ? ' s' : ''}</span>
          ))}
        </div>
        <ul className="space-y-2.5" aria-label="Examples and how the rule scores each at the chosen d">
          {rows.map((r) => {
            const ok = r.s.right
            const sup = r.tick.sup
            return (
              <li key={r.ex.alias}>
                <div className="mb-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    <Badge tone={r.ex.label === 'pos' ? 'pos' : 'neg'} icon={r.ex.label === 'pos' ? 'plus' : 'minus'}>{r.ex.label === 'pos' ? 'yes' : 'no'}</Badge>
                    <span className="min-w-0 truncate text-sm text-ex-ink" title={r.card?.title}>{r.card?.title ?? r.ex.alias}</span>
                    {violated.includes(r.ex.alias) && <Badge tone="warn" icon="warning">missed by the recorded rule</Badge>}
                  </div>
                  <span className={cx('inline-flex items-center gap-1.5 font-mono text-sm tabular-nums', ok ? 'text-ex-pos' : 'text-ex-neg')}>
                    <Icon name={ok ? 'check' : 'cross'} className="h-3.5 w-3.5" />
                    <span className="sr-only">{ok ? 'on the right side: ' : 'on the wrong side: '}</span>
                    {fmtScore(r.s.score)}
                  </span>
                </div>
                <Track
                  domain={model.max}
                  box={model.box}
                  d={d}
                  recordedD={model.recordedD}
                  tick={{ sup, label: r.ex.label }}
                  window={r.s.window}
                  frames={r.tick.times.map((t, k) => ({ t, holds: (r.tick.rho[k] as number) > 0 }))}
                />
                <p className="mt-0.5 text-xs text-ex-ink3">
                  {sup === null ? 'The part of the rule inside “continuously” never holds on this clip.' : <>Holds for up to <span className="font-mono tabular-nums text-ex-ink2">{fmtPlain(sup, 3)} s</span> in a row{r.tick.closed ? ' (to the end of the clip)' : ''}.</>}
                </p>
              </li>
            )
          })}
        </ul>

        <div className="mt-4 border-t border-ex-line pt-4">
          <Slider
            label="d, at least this many seconds"
            value={d}
            min={0}
            max={model.max}
            step={0.5}
            pageStep={5}
            onChange={setD}
            valueText={(v) => `${fmtPlain(v)} seconds`}
            display={`${fmtPlain(d)} s`}
            marks={[
              { value: model.recordedD, label: 'recorded', tone: 'warn' },
              ...(model.box.lo > 0 ? [{ value: model.box.lo, label: 'range start', tone: 'accent' as const }] : []),
              { value: Math.min(model.box.hi, model.max), label: 'range end', tone: 'accent' },
            ]}
            hint={<>Drag, or use the arrow keys for 0.5 s and Page Up / Page Down for 5 s. Every score is recomputed by the evaluator. Marks under the track: <span className="text-ex-warn">amber</span> is the recorded value, <span className="text-ex-accent-ink">blue</span> the ends of the range.</>}
          />
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setD(model.recordedD)} disabled={atRecorded} icon="refresh">Back to the recorded value</Button>
            <Button size="sm" variant="ghost" onClick={() => setD(model.placed.snapped ?? model.recordedD)}>Go to the placed value</Button>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Card padding="sm">
          <p className="text-xs font-medium text-ex-ink3">Weighted agreement at d = <DV src="slider">{fmtPlain(d)} s</DV></p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-ex-ink"><DV src="lib/dsl evaluator">{fmtPlain(wRight)} of {fmtPlain(wTotal)}</DV></p>
          <p className="mt-0.5 text-xs text-ex-ink2">{posRight} of {pos.length} yes examples matched, {negRight} of {neg.length} no examples rejected.</p>
        </Card>
        <Card padding="sm">
          <p className="text-xs font-medium text-ex-ink3">Margin at d = <DV src="slider">{fmtPlain(d)} s</DV></p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-ex-ink"><DV src="lib/dsl evaluator">{margin !== null ? fmtPlain(margin) : 'none'}</DV></p>
          <p className="mt-0.5 text-xs text-ex-ink2">{margin !== null ? 'The smallest |score| over all examples; every example is on its labelled side.' : 'Some examples are on the wrong side here, so the rule has no margin on this set.'}</p>
        </Card>
        <Card padding="sm">
          <p className="text-xs font-medium text-ex-ink3">Recorded</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-ex-ink"><DV src={`rules/${run.rule.slug}.json`}>d = {fmtPlain(model.recordedD)} s, margin {fmtPlain(run.rule.margin)}</DV></p>
          <p className="mt-0.5 text-xs text-ex-ink2">{atRecorded ? 'You are looking at the recorded value.' : 'Drag back to the recorded value to see it again.'}</p>
        </Card>
      </div>

      <Card tone="accent" padding="sm">
        <p className="text-sm text-ex-ink">
          The solver first keeps as much of the (weighted) example set on the right side as it can, then makes the margin as wide as possible. For that best set it computes the range of d that keeps those same examples right at that margin. The engine places d in the middle of the range, on a 0.5 s grid.
        </p>
        <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-ex-ink3">Range of d at margin {fmtPlain(run.rule.margin)}</dt>
          <dd className="font-mono tabular-nums text-ex-ink"><DV src="lib/dsl evaluator">{fmtPlain(model.box.lo, 3)} to {fmtPlain(model.box.hi, 3)} s</DV>{model.exported && <span className="ml-2 font-sans text-xs text-ex-ink3">{boxMatches ? 'equals the engine’s exported range' : `engine exported ${fmtPlain(model.exported[0], 3)} to ${fmtPlain(model.exported[1], 3)} s`}</span>}</dd>
          <dt className="text-ex-ink3">Middle of the range</dt>
          <dd className="font-mono tabular-nums text-ex-ink"><DV src="lib/dsl evaluator">{fmtPlain(model.placed.centre, 3)} s</DV></dd>
          <dt className="text-ex-ink3">Snapped to the 0.5 s grid</dt>
          <dd className="font-mono tabular-nums text-ex-ink"><DV src="lib/dsl evaluator">{model.placed.snapped !== null ? `${fmtPlain(model.placed.snapped)} s` : 'no grid point in the range'}</DV><span className="ml-2 font-sans text-xs text-ex-ink3">{placedMatches ? 'equals the recorded d' : `recorded d is ${fmtPlain(model.recordedD)} s`}</span></dd>
        </dl>
        {violated.length > 0 && (
          <p className="mt-3 text-sm text-ex-warn">
            In this recorded solve the rule misses {violated.length} labelled example{violated.length > 1 ? 's' : ''} ({violated.map((a) => cards[a]?.title ?? a).join('; ')}); the range above is for the examples it keeps.
          </p>
        )}
      </Card>
      <LiveRegion text={summary} />
    </div>
  )
}
