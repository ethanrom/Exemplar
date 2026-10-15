'use client'

import { useState } from 'react'
import { COST, PLAYGROUND, VERIFIED, fmtCost } from '../_data/evidence'
import { useApi } from '../_lib/hooks'
import type { EventDetail, Firing, RuleSummary } from '../_lib/types'
import { EventThumb } from '../_components/EventBits'
import { Dsl } from '../_components/Dsl'
import { Icon } from '../_components/Icon'
import { PageHeader, Skeleton, Stat, StatStrip, cx } from '../_components/ui'
import { WitnessTimeline } from '../_components/WitnessTimeline'

// Categorical slots 1 and 2 of the dataviz reference palette (dark): validated on the card surface
// #111316 (CVD dE >= 8, contrast >= 3:1). Colour follows the method, never its rank.
const EXEMPLAR = { label: 'Exemplar', color: '#3987e5' }
const ZERO_SHOT = { label: 'Zero-shot VLM', color: '#d95926' }
const INK = '#ECEDEF'
const INK2 = '#B2B6BD'
const MUTED = '#8A8F98'
const GRID = '#23272D'
const AXIS = '#3A3F47'
const SURFACE = '#111316'

const zeroShotCost = (rules: number) => COST.zeroShotPerRuleUsd * rules
const ratio = (rules: number) => zeroShotCost(rules) / COST.exemplarPerEventUsd

// ---------------------------------------------------------------------------------------------
function CostChart({ rules, onRules }: { rules: number; onRules: (n: number) => void }) {
  const W = 760, H = 340
  const m = { l: 62, r: 138, t: 22, b: 50 }
  const pw = W - m.l - m.r
  const ph = H - m.t - m.b
  const YMAX = 0.15
  const xs = Array.from({ length: COST.maxRules }, (_, i) => i + 1)
  const x = (n: number) => m.l + ((n - 1) / (COST.maxRules - 1)) * pw
  const y = (v: number) => m.t + ph - (v / YMAX) * ph
  const yTicks = [0, 0.05, 0.1, 0.15]
  const zs = (n: number) => zeroShotCost(n)
  const ex = COST.exemplarPerEventUsd

  function onPointer(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect()
    const vx = ((e.clientX - r.left) / r.width) * W
    const n = Math.round(((vx - m.l) / pw) * (COST.maxRules - 1)) + 1
    if (n >= 1 && n <= COST.maxRules) onRules(n)
  }
  const halo = { stroke: SURFACE, strokeWidth: 4, paintOrder: 'stroke' as const }

  return (
    <div className="relative overflow-x-auto">
      <div className="min-w-[620px]">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block w-full cursor-crosshair touch-pan-y"
          role="group"
          aria-label="Line chart of model cost per event against the number of rules deployed. Zero-shot prompting grows with every rule; Exemplar stays flat. Use the table view or the slider below for exact values."
          onPointerMove={onPointer}
          onPointerDown={onPointer}
        >
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? AXIS : GRID} strokeWidth="1" />
              <text x={m.l - 10} y={y(t) + 4} textAnchor="end" fontSize="12" fill={MUTED}>{t === 0 ? '$0' : `$${t.toFixed(2)}`}</text>
            </g>
          ))}
          {xs.map((n) => (
            <text key={n} x={x(n)} y={H - m.b + 20} textAnchor="middle" fontSize="12" fill={n === rules ? INK : MUTED} fontWeight={n === rules ? 600 : 400}>{n}</text>
          ))}
          <text x={m.l + pw / 2} y={H - 8} textAnchor="middle" fontSize="12" fill={MUTED}>rules deployed</text>
          <text x={14} y={m.t + ph / 2} textAnchor="middle" fontSize="12" fill={MUTED} transform={`rotate(-90 14 ${m.t + ph / 2})`}>model cost per event (USD)</text>

          {/* the selected number of rules */}
          <line x1={x(rules)} x2={x(rules)} y1={m.t} y2={m.t + ph} stroke={MUTED} strokeWidth="1" strokeDasharray="4 4" />

          {/* lines: 2 px, round caps */}
          <line x1={x(1)} y1={y(zs(1))} x2={x(COST.maxRules)} y2={y(zs(COST.maxRules))} stroke={ZERO_SHOT.color} strokeWidth="2.5" strokeLinecap="round" />
          <line x1={x(1)} y1={y(ex)} x2={x(COST.maxRules)} y2={y(ex)} stroke={EXEMPLAR.color} strokeWidth="2.5" strokeLinecap="round" />

          {/* direct labels at the line ends */}
          <g>
            <text x={x(COST.maxRules) + 14} y={y(zs(COST.maxRules)) - 2} fontSize="12" fill={INK2}>{ZERO_SHOT.label}</text>
            <text x={x(COST.maxRules) + 14} y={y(zs(COST.maxRules)) + 15} fontSize="13" fontWeight="600" fill={INK}>{fmtCost(zs(COST.maxRules))}</text>
            <text x={x(COST.maxRules) + 14} y={y(ex) - 18} fontSize="12" fill={INK2}>{EXEMPLAR.label}</text>
            <text x={x(COST.maxRules) + 14} y={y(ex) - 3} fontSize="13" fontWeight="600" fill={INK}>{fmtCost(ex)}</text>
          </g>

          {/* markers on the selected x: 10 px with a surface ring */}
          <circle cx={x(rules)} cy={y(zs(rules))} r="5" fill={ZERO_SHOT.color} stroke={SURFACE} strokeWidth="2" />
          <circle cx={x(rules)} cy={y(ex)} r="5" fill={EXEMPLAR.color} stroke={SURFACE} strokeWidth="2" />
          <text x={x(rules) - 12} y={y(zs(rules)) - 10} textAnchor={rules === 1 ? 'start' : 'end'} fontSize="13" fontWeight="600" fill={INK} {...halo}>{fmtCost(zs(rules))}</text>
          <text x={x(rules)} y={y(ex) - 12} textAnchor="middle" fontSize="13" fontWeight="600" fill={INK} {...halo}>{fmtCost(ex)}</text>
        </svg>
      </div>
    </div>
  )
}

function Legend() {
  const item = (s: { label: string; color: string }, formula: React.ReactNode) => (
    <li className="flex items-start gap-2.5 text-sm text-ex-ink2">
      <span aria-hidden="true" className="mt-1 h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: s.color }} />
      <span><span className="font-medium text-ex-ink">{s.label}</span> <span className="text-ex-ink3">·</span> {formula}</span>
    </li>
  )
  return (
    <ul className="flex flex-wrap gap-x-8 gap-y-2" aria-label="Legend">
      {item(ZERO_SHOT, <><span className="font-mono text-xs tabular-nums">{fmtCost(COST.zeroShotPerRuleUsd)}</span> for every rule, on every event</>)}
      {item(EXEMPLAR, <><span className="font-mono text-xs tabular-nums">{fmtCost(COST.exemplarPerEventUsd)}</span> per event, however many rules</>)}
    </ul>
  )
}

function CostTable() {
  const rows = Array.from({ length: COST.maxRules }, (_, i) => i + 1)
  return (
    <table className="w-full min-w-[520px] border-separate border-spacing-0 text-sm">
      <caption className="sr-only">Model cost per event for one to {COST.maxRules} deployed rules: zero-shot prompting against Exemplar.</caption>
      <thead>
        <tr>
          {['Rules deployed', ZERO_SHOT.label, EXEMPLAR.label, 'Exemplar is cheaper by'].map((h, i) => (
            <th key={h} scope="col" className={cx('border-b border-ex-line2 py-2 pr-4 text-xs font-medium text-ex-ink3', i === 0 ? 'text-left' : 'text-right')}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((n) => (
          <tr key={n}>
            <th scope="row" className="border-b border-ex-line py-2.5 pr-4 text-left font-normal tabular-nums text-ex-ink">{n}</th>
            <td className="border-b border-ex-line py-2.5 pr-4 text-right font-mono text-xs tabular-nums text-ex-ink2">{fmtCost(zeroShotCost(n))}</td>
            <td className="border-b border-ex-line py-2.5 pr-4 text-right font-mono text-xs tabular-nums text-ex-ink2">{fmtCost(COST.exemplarPerEventUsd)}</td>
            <td className="border-b border-ex-line py-2.5 pr-4 text-right font-mono text-xs tabular-nums text-ex-ink2">{ratio(n).toFixed(1)}×</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function CostFigure() {
  const [rules, setRules] = useState(5)
  const [asTable, setAsTable] = useState(false)
  const summary = `At ${rules} rule${rules === 1 ? '' : 's'}: zero-shot prompting costs ${fmtCost(zeroShotCost(rules))} per event, Exemplar ${fmtCost(COST.exemplarPerEventUsd)}, which is ${ratio(rules).toFixed(rules === 1 ? 1 : 0)} times less.`
  return (
    <figure className="rounded-xl border border-ex-line bg-ex-panel p-5 sm:p-8" aria-labelledby="cost-t">
      <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-3">
        <figcaption className="min-w-0 max-w-2xl">
          <span id="cost-t" className="block text-lg font-semibold tracking-tight text-ex-ink">Cost per event as you add rules</span>
          <span className="mt-1.5 block text-base text-ex-ink2">
            Ask a vision model about each rule and every new rule is another strong-model call on every event. Exemplar reads each clip once; every rule then runs on that trace without a model call.
          </span>
        </figcaption>
        <button type="button" className="btn btn-sm" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>
          <Icon name={asTable ? 'gauge' : 'table'} className="h-3.5 w-3.5" /> {asTable ? 'Show chart' : 'Show as table'}
        </button>
      </div>

      <div className="mt-6"><Legend /></div>

      <div className="mt-5">{asTable ? <div className="relative overflow-x-auto"><CostTable /></div> : <CostChart rules={rules} onRules={setRules} />}</div>

      <div className="mt-5 grid gap-4 border-t border-ex-line pt-5 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] md:items-center">
        <div>
          <label htmlFor="rules-range" className="flex items-baseline gap-3 text-sm font-medium text-ex-ink">
            Rules deployed <span className="text-xl font-semibold tabular-nums">{rules}</span>
          </label>
          <input
            id="rules-range"
            type="range"
            min={1}
            max={COST.maxRules}
            step={1}
            value={rules}
            onChange={(e) => setRules(Number(e.target.value))}
            aria-valuetext={`${rules} rule${rules === 1 ? '' : 's'}`}
            className="mt-2 h-6 w-full cursor-pointer accent-[#3987e5]"
          />
        </div>
        <p role="status" aria-live="polite" className="text-sm text-ex-ink2 md:pl-4">
          At <span className="font-medium tabular-nums text-ex-ink">{rules}</span> rule{rules === 1 ? '' : 's'}, zero-shot prompting costs{' '}
          <span className="font-semibold tabular-nums text-ex-ink">{fmtCost(zeroShotCost(rules))}</span> per event and Exemplar{' '}
          <span className="font-semibold tabular-nums text-ex-ink">{fmtCost(COST.exemplarPerEventUsd)}</span>:{' '}
          <span className="font-semibold tabular-nums text-ex-ink">{ratio(rules).toFixed(rules === 1 ? 1 : 0)}×</span> less.
          <span className="sr-only"> {summary}</span>
        </p>
      </div>

      <p className="mt-5 text-xs text-ex-ink3">
        Measured on Amazon Bedrock. Zero-shot: {COST.zeroShotCalls} calls on MEVA footage. Exemplar: {COST.exemplarClips.toLocaleString()} clips, median latency {COST.exemplarP50LatencyS} s.
        Exemplar excludes the strong-model re-check of borderline events (0 of the live Playground events needed one).
      </p>
    </figure>
  )
}

// ---------------------------------------------------------------------------------------------
function Verified() {
  return (
    <section aria-labelledby="ver-h" className="mt-20">
      <h2 id="ver-h" className="text-lg font-semibold tracking-tight text-ex-ink">Verified, not just tested</h2>
      <p className="mt-1.5 max-w-2xl text-base text-ex-ink2">
        A wrong threshold from the solver, or a false-alarm bound that does not hold, would quietly break the whole promise. So both are checked against independent code and by simulation.
      </p>
      <div className="mt-6">
        <StatStrip cols="grid-cols-1 sm:grid-cols-2 lg:grid-cols-4" label="Verification">
          {VERIFIED.map((v) => (
            <Stat key={v.label} label={v.label} value={v.value} size="lg" icon={v.clean ? 'check' : 'layers'} hint={v.detail} />
          ))}
        </StatStrip>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
function LatestAlert() {
  const firings = useApi<Firing[]>('/monitor/firings?limit=30')
  const f = (firings.data ?? []).find((x) => x.fired && x.witness) ?? null
  const rule = useApi<RuleSummary>(f ? `/rules/${encodeURIComponent(f.rule_id)}` : null)
  const ev = useApi<EventDetail>(f ? `/events/${encodeURIComponent(f.event_id)}` : null)
  if (firings.loading && !firings.data) return <Skeleton className="mt-8 h-56 rounded-xl" label="Loading the latest alert" />
  if (!f || !f.witness) return null
  return (
    <div className="mt-8">
      <h3 className="text-sm font-semibold text-ex-ink">An alert and its explanation</h3>
      <p className="mt-0.5 text-sm text-ex-ink2">The latest alert on this install: what fired, and the facts and times that satisfied the rule.</p>
      <div className="mt-4 flex items-start gap-4">
        {ev.data ? <EventThumb event={ev.data} compact className="h-[54px] w-24 shrink-0 rounded-md" /> : <Skeleton className="h-[54px] w-24 shrink-0" />}
        <div className="min-w-0">
          <p className="line-clamp-2 text-sm text-ex-ink">{ev.data?.summary ?? 'Event'}</p>
          {rule.data && <p className="mt-1 text-sm text-ex-ink2">Rule: {rule.data.english} <span className="ml-1 font-mono text-xs"><Dsl text={rule.data.dsl_text} /></span></p>}
        </div>
      </div>
      <div className="mt-4"><WitnessTimeline witness={f.witness} durationMs={ev.data?.duration_ms} /></div>
    </div>
  )
}

function Playground() {
  const { rules, runs, usdPerEvent, taughtInSeconds, strongRechecks } = PLAYGROUND
  return (
    <section aria-labelledby="live-h" className="mt-20">
      <h2 id="live-h" className="text-lg font-semibold tracking-tight text-ex-ink">Live on the Ring Playground</h2>
      <p className="mt-1.5 max-w-2xl text-base text-ex-ink2">
        Two rules taught from Playground events, then three simulated events sent through the whole pipeline. Each event fired only its own rule, each alert with its explanation.
      </p>

      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-12">
        <div className="min-w-0 overflow-x-auto rounded-xl border border-ex-line bg-ex-panel">
          <table className="w-full min-w-[460px] border-separate border-spacing-0 text-sm">
            <caption className="sr-only">Which rule fired on which simulated Playground event.</caption>
            <thead>
              <tr>
                <th scope="col" className="border-b border-ex-line px-5 py-3 text-left text-xs font-medium text-ex-ink3">Event sent in</th>
                {rules.map((r) => (
                  <th key={r.key} scope="col" className="border-b border-ex-line px-5 py-3 text-left text-xs font-medium text-ex-ink3">
                    {r.name}
                    <span className="block font-normal">taught as “{r.taught}”</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((run, i) => (
                <tr key={run.event}>
                  <th scope="row" className={cx('px-5 py-4 text-left font-medium text-ex-ink', i < runs.length - 1 && 'border-b border-ex-line')}>{run.event}</th>
                  {rules.map((r) => {
                    const fired = run.fired[r.key]
                    return (
                      <td key={r.key} className={cx('px-5 py-4', i < runs.length - 1 && 'border-b border-ex-line')}>
                        {fired ? (
                          <span className="inline-flex items-center gap-1.5 font-medium text-ex-pos"><Icon name="bolt" className="h-4 w-4" /> Fired</span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-ex-ink3"><Icon name="minus" className="h-4 w-4" /> Did not fire</span>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <dl className="grid content-start gap-5 sm:grid-cols-3 lg:grid-cols-1">
          <div>
            <dt className="text-xs text-ex-ink3">Model cost per event</dt>
            <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums text-ex-ink">~${usdPerEvent}</dd>
          </div>
          <div>
            <dt className="text-xs text-ex-ink3">Time to teach a rule</dt>
            <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums text-ex-ink">{taughtInSeconds[0]}–{taughtInSeconds[1]} s</dd>
          </div>
          <div>
            <dt className="text-xs text-ex-ink3">Strong-model re-checks needed</dt>
            <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums text-ex-ink">{strongRechecks}</dd>
          </div>
        </dl>
      </div>

      <LatestAlert />
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
export default function EvidenceScreen() {
  return (
    <>
      <PageHeader
        title="Evidence"
        subtitle="What it costs to watch, what has been verified, and what happened on a real Ring Playground. Measured numbers, with where each one comes from."
      />
      <CostFigure />
      <Verified />
      <Playground />
    </>
  )
}
