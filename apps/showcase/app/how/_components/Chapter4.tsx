'use client'

import { useMemo, useState } from 'react'
import { Button } from '@/components/Button.tsx'
import { Card } from '@/components/Card.tsx'
import { Dsl } from '@/components/CodeBlock.tsx'
import { cx } from '@/components/cx.ts'
import { Icon } from '@/components/Icon.tsx'
import { LiveRegion } from '@/components/lab/Announce.tsx'
import { fmtPlain, fmtScore } from '@/components/lab/core/format.ts'
import { parseCached } from '@/components/lab/core/rules.ts'
import { DV } from '@/components/lab/DataValue.tsx'
import { FrameCell } from '@/components/lab/FrameCell.tsx'
import { RhoStrip } from '@/components/lab/RhoStrip.tsx'
import { Segmented } from '@/components/lab/Segmented.tsx'
import { Slider } from '@/components/lab/Slider.tsx'
import { WitnessTimeline } from '@/components/lab/WitnessTimeline.tsx'
import type { ClipCard, LiveDoc, TraceJson } from '@/lib/data/types.ts'
import { explore, matchesRecorded, singleHole } from '../_lib/explore.ts'
import type { SlimRule } from '../_lib/types.ts'

const CLASS_WORD: Record<string, string> = { pg_package: 'package', pg_vehicle: 'vehicle', pg_bird: 'birds' }
const RULE_WORD: Record<string, string> = { 'package-deployed': 'package rule', 'vehicle-deployed': 'vehicle rule' }

/** Chapter 4: why it fired. Pick a recorded event and a deployed rule; drag the blank and watch each part of the rule re-score. */
export function Chapter4({
  live, deployed, traces, cards,
}: { live: LiveDoc; deployed: Record<string, SlimRule>; traces: Record<string, TraceJson>; cards: Record<string, ClipCard> }) {
  const [order, setOrder] = useState<string>('3')
  const [ruleSlug, setRuleSlug] = useState<string>('package-deployed')
  const ev = live.events.find((e) => String(e.order) === order) ?? (live.events[0] as LiveDoc['events'][number])
  const rule = deployed[ruleSlug] as SlimRule
  const sketch = useMemo(() => parseCached(rule.sketch_text), [rule.sketch_text])
  const hole = useMemo(() => singleHole(sketch), [sketch])
  const recordedValue = hole ? (rule.holes[hole] as number) : null
  const trace = traces[ev.alias] as TraceJson
  const card = cards[ev.alias] as ClipCard
  const decision = ev.decisions.find((x) => x.rule === ruleSlug) as LiveDoc['events'][number]['decisions'][number]

  const [value, setValue] = useState<number>(recordedValue ?? 0)
  const [lastRule, setLastRule] = useState(ruleSlug)
  if (lastRule !== ruleSlug) {
    setLastRule(ruleSlug)
    setValue((deployed[ruleSlug] as SlimRule).holes[singleHole(parseCached((deployed[ruleSlug] as SlimRule).sketch_text)) ?? ''] ?? 0)
  }

  const dValue = hole ? value : null
  const x = useMemo(() => explore(sketch, trace, hole, dValue), [sketch, trace, hole, dValue])
  const w = x.witness
  const tau = decision.tau
  const matches = w.score > 0
  const fires = w.score > tau
  const atRecorded = hole === null || value === recordedValue
  const reproduces = atRecorded && matchesRecorded(w, decision)
  const maxD = Math.ceil(trace.duration_ms / 500) / 2
  const times = trace.frames.map((f) => f.t_ms)
  const evidenceIdx = x.evidenceMs === null ? 0 : Math.max(0, times.findIndex((t) => t >= (x.evidenceMs as number)))

  const summary = `${RULE_WORD[ruleSlug]} on event ${ev.order}${hole ? ` with ${hole} = ${fmtPlain(value)} seconds` : ''}: score ${fmtScore(w.score)}, ${matches ? 'the rule matches' : 'the rule does not match'}, ${fires ? 'it fires' : 'it does not fire'} against tau ${fmtPlain(tau)}.`

  return (
    <div data-src="data/live.json, data/rules/*.json, lib/dsl evaluator and witness" className="space-y-5">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <div>
          <p className="mb-1 text-xs font-medium text-ex-ink3">Recorded event</p>
          <Segmented
            label="Recorded event"
            value={order}
            onChange={(v) => setOrder(v)}
            size="sm"
            options={live.events.map((e) => ({ id: String(e.order), label: `${e.order} · ${CLASS_WORD[e.class] ?? e.class}`, hint: e.decisions.filter((q) => q.fired).map((q) => RULE_WORD[q.rule]).join(', ') || 'neither fired' }))}
          />
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-ex-ink3">Rule</p>
          <Segmented
            label="Deployed rule"
            value={ruleSlug}
            onChange={setRuleSlug}
            size="sm"
            options={Object.keys(RULE_WORD).filter((s) => deployed[s]).map((s) => ({ id: s, label: RULE_WORD[s] as string, hint: 'deployed' }))}
          />
        </div>
      </div>

      <Card padding="sm">
        <p className="text-xs font-medium text-ex-ink3">The rule, {hole ? 'with its blank filled by the slider below' : 'which has no blank'}</p>
        <pre className="mt-1.5 whitespace-pre-wrap break-words font-mono text-xs leading-5"><code><Dsl text={hole ? rule.sketch_text.replaceAll(`?${hole}`, fmtPlain(value)) : rule.dsl_text} /></code></pre>
        <p className="mt-1.5 text-sm text-ex-ink2">{w.english}</p>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,4fr)]">
        <div className="space-y-3">
          <FrameCell sheet={card.sheet} index={evidenceIdx} label={`The frame where the rule found its evidence: ${card.title}, ${(times[evidenceIdx] as number / 1000).toFixed(1)} seconds`} />
          <p className="text-xs text-ex-ink2">
            {card.title}. {x.evidenceMs !== null && matches ? <>The frame where the rule found its evidence, at <span className="font-mono tabular-nums">{(x.evidenceMs / 1000).toFixed(1)} s</span>.</> : <>The frame where the rule came closest, at <span className="font-mono tabular-nums">{x.evidenceMs !== null ? (x.evidenceMs / 1000).toFixed(1) : '0.0'} s</span>.</>}
          </p>
        </div>
        <div className="space-y-4">
          <div>
            <p className="mb-1 text-sm font-medium text-ex-ink">The part of the rule that has to hold, at each sampled frame</p>
            <RhoStrip
              timesMs={times}
              rho={x.rho}
              durationMs={trace.duration_ms}
              window={x.window}
              windowLabel={x.window ? `window ${(x.window.startMs / 1000).toFixed(1)} to ${(x.window.endMs / 1000).toFixed(1)} s` : undefined}
              label={`Per-frame robustness for ${trace.frames.length} sampled frames: ${x.rho.filter((r) => r > 0).length} hold, ${x.rho.filter((r) => r <= 0).length} do not.${x.window ? ` The window the rule checked runs from ${(x.window.startMs / 1000).toFixed(1)} to ${(x.window.endMs / 1000).toFixed(1)} seconds.` : ''}`}
              height={72}
            />
            <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ex-ink3">
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-2 rounded-sm bg-ex-pos" />bar up: holds</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-3 w-2 rounded-sm bg-ex-neg" />bar down: does not hold</span>
              {x.window && <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm border-x-2 border-ex-accent-ink bg-ex-accent-soft" />window the rule checked</span>}
            </p>
          </div>

          {hole ? (
            <Slider
              label={`${hole}, at least this many seconds`}
              value={value}
              min={0}
              max={maxD}
              step={0.5}
              pageStep={5}
              onChange={setValue}
              valueText={(v) => `${fmtPlain(v)} seconds`}
              display={`${fmtPlain(value)} s`}
              marks={recordedValue !== null ? [{ value: recordedValue, label: 'recorded', tone: 'warn' }] : undefined}
              hint="Arrow keys move 0.5 s, Page Up and Page Down 5 s. The window, the score and the match state are recomputed by the evaluator."
            />
          ) : (
            <p className="text-sm text-ex-ink2">This rule has no blank to drag: it asks only whether the vehicle is in the driveway at some sampled frame.</p>
          )}
          {hole && (
            <Button size="sm" icon="refresh" disabled={atRecorded} onClick={() => setValue(recordedValue as number)}>Back to the recorded value</Button>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Card padding="sm" tone={matches ? 'pos' : 'neutral'}>
          <p className="text-xs font-medium text-ex-ink3">Does the rule match? (ρ &gt; 0)</p>
          <p className="mt-1 flex items-center gap-2 text-xl font-semibold text-ex-ink"><Icon name={matches ? 'check' : 'cross'} className={cx('h-5 w-5', matches ? 'text-ex-pos' : 'text-ex-neg')} />{matches ? 'Yes' : 'No'}</p>
          <p className="mt-0.5 font-mono text-xs tabular-nums text-ex-ink2">score <DV src="lib/dsl evaluator">{fmtScore(w.score)}</DV></p>
        </Card>
        <Card padding="sm" tone={fires ? 'pos' : 'neutral'}>
          <p className="text-xs font-medium text-ex-ink3">Does it fire? (ρ &gt; τ)</p>
          <p className="mt-1 flex items-center gap-2 text-xl font-semibold text-ex-ink"><Icon name={fires ? 'bell' : 'minus'} className={cx('h-5 w-5', fires ? 'text-ex-pos' : 'text-ex-ink3')} />{fires ? 'Fires' : 'Stays quiet'}</p>
          <p className="mt-0.5 font-mono text-xs tabular-nums text-ex-ink2">τ = <DV src="data/live.json">{fmtPlain(tau)}</DV> (stage {decision.stage})</p>
        </Card>
        <Card padding="sm">
          <p className="text-xs font-medium text-ex-ink3">Against the recording</p>
          <p className="mt-1 text-sm font-medium text-ex-ink">
            {reproduces ? <span className="inline-flex items-center gap-1.5 text-ex-pos"><Icon name="check" className="h-4 w-4" />Reproduces the recorded {decision.witness ? 'witness' : 'score'} exactly</span> : atRecorded ? <span className="inline-flex items-center gap-1.5 text-ex-neg"><Icon name="cross" className="h-4 w-4" />Differs from the recording</span> : <span className="inline-flex items-center gap-1.5 text-ex-warn"><Icon name="sliders" className="h-4 w-4" />What-if: {hole} changed from the recorded {fmtPlain(recordedValue as number)} s</span>}
          </p>
          <p className="mt-0.5 text-xs text-ex-ink2">Recorded on the Playground: <DV src="data/live.json">{decision.fired ? 'fired' : 'did not fire'}, score {fmtScore(decision.score)}</DV>.</p>
        </Card>
      </div>

      <WitnessTimeline
        witness={{ ...w, tau, margin: w.score - tau }}
        durationMs={trace.duration_ms}
        title={fires ? 'Why it fired' : matches ? 'Why it matched but stays quiet' : 'Closest attempt: why it did not fire'}
      />
      <p className="flex items-start gap-2 text-xs text-ex-ink3">
        <Icon name="shield" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>Recomputed in your browser from the recorded facts, with the same evaluator and witness code the engine’s outputs were checked against.</span>
      </p>
      <LiveRegion text={summary} />
    </div>
  )
}
