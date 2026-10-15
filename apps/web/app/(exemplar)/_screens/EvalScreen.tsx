'use client'

import { useMemo, useState } from 'react'
import { useApp } from '../_lib/app'
import { fmtInt, fmtNum, fmtUsd } from '../_lib/format'
import { useApi } from '../_lib/hooks'
import type { EvalResults, EvalRow } from '../_lib/types'
import { Icon } from '../_components/Icon'
import { Alert, Empty, PageHeader, Skeleton, Stat, StatStrip } from '../_components/ui'

// Dark-surface categorical slots 1-4 (dataviz reference palette), validated adjacent-pair on the card
// surface #111316: CVD dE 8.4 (worst), normal-vision dE 19.8, contrast >= 3:1. Order is fixed: color
// follows the method, never its rank.
const METHODS = [
  { key: 'exemplar', label: 'Exemplar (ours)', color: '#3987e5' },
  { key: 'zero_shot_vlm', label: 'Zero-shot VLM', color: '#d95926' },
  { key: 'knn_embed', label: 'kNN on embeddings', color: '#199e70' },
  { key: 'nova_video', label: 'Amazon Nova video', color: '#c98500' },
] as const
type MethodKey = (typeof METHODS)[number]['key']

const CONCEPT_NAME: Record<string, string> = {
  vehicle_dwell: 'Vehicle dwell',
  door_entry_exit: 'Door entry / exit',
  exit_vehicle: 'Exit vehicle',
  load_unload: 'Load / unload',
}
const conceptName = (c: string) => CONCEPT_NAME[c] ?? c.replace(/_/g, ' ')

// Chart chrome, from the design tokens (ex-ink, ex-ink2, ex-ink3, the card surface ex-panel).
const INK = '#ECEDEF'
const INK2 = '#B2B6BD'
const MUTED = '#8A8F98'
const GRID = '#23272D'
const AXIS = '#3A3F47'
const SURFACE = '#111316'
const ALL = '__all__'

type Metric = 'f1' | 'false_alarm_rate' | 'usd_per_event' | 'p50_latency_ms' | 'tokens_per_event' | 'escalated_fraction'

interface Stat { mean: number; sd: number; n: number }

function stat(rows: EvalRow[], m: Metric): Stat | null {
  const v = rows.map((r) => r[m]).filter((x): x is number => typeof x === 'number')
  if (!v.length) return null
  const mean = v.reduce((a, b) => a + b, 0) / v.length
  const sd = v.length > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (v.length - 1)) : 0
  return { mean, sd, n: v.length }
}

/** Mean of per-concept means (macro average) with the sd of the per-concept means' seeds pooled. */
function macro(rows: EvalRow[], concepts: string[], m: Metric): Stat | null {
  const per = concepts.map((c) => stat(rows.filter((r) => r.concept === c), m)).filter((x): x is Stat => !!x)
  if (!per.length) return null
  const mean = per.reduce((a, b) => a + b.mean, 0) / per.length
  const sd = per.reduce((a, b) => a + b.sd, 0) / per.length
  return { mean, sd, n: per.reduce((a, b) => a + b.n, 0) }
}

// ---------------------------------------------------------------------------------------------
function Legend({ methods }: { methods: readonly { key: string; label: string; color: string }[] }) {
  if (methods.length < 2) return null // one series: the title names it
  return (
    <ul className="flex flex-wrap items-center gap-x-5 gap-y-1" aria-label="Legend">
      {methods.map((m) => (
        <li key={m.key} className="flex items-center gap-2 text-sm text-ex-ink2">
          <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[3px]" style={{ background: m.color }} />
          {m.label}
        </li>
      ))}
    </ul>
  )
}

function ChartCard({
  id, title, subtitle, legend, children, table, footer,
}: {
  id: string
  title: string
  subtitle: string
  legend?: React.ReactNode
  children: React.ReactNode
  table: React.ReactNode
  footer?: React.ReactNode
}) {
  const [asTable, setAsTable] = useState(false)
  return (
    <figure className="rounded-xl border border-ex-line bg-ex-panel p-5 sm:p-6" aria-labelledby={`${id}-t`}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-2xl">
          <figcaption>
            <span id={`${id}-t`} className="block text-md font-semibold tracking-tight text-ex-ink">{title}</span>
            <span className="mt-0.5 block text-sm text-ex-ink2">{subtitle}</span>
          </figcaption>
        </div>
        <button type="button" className="btn btn-sm" aria-pressed={asTable} onClick={() => setAsTable(!asTable)}>
          <Icon name={asTable ? 'gauge' : 'table'} className="h-3.5 w-3.5" /> {asTable ? 'Show chart' : 'Show as table'}
        </button>
      </div>
      {legend && <div className="mt-4">{legend}</div>}
      <div className="mt-4">{asTable ? <div className="relative overflow-x-auto">{table}</div> : children}</div>
      {footer && <div className="mt-4 border-t border-ex-line pt-4 text-sm text-ex-ink2">{footer}</div>}
    </figure>
  )
}

interface Tip { x: number; y: number; title: string; lines: string[] }

function TooltipBox({ tip }: { tip: Tip | null }) {
  if (!tip) return null
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-ex-line2 bg-ex-raised px-2.5 py-1.5 text-xs shadow-lg shadow-black/50"
      style={{ left: `${tip.x}%`, top: `${tip.y}%` }}
    >
      <p className="font-semibold text-ex-ink">{tip.title}</p>
      {tip.lines.map((l) => <p key={l} className="text-ex-ink2">{l}</p>)}
    </div>
  )
}

const roundedTop = (x: number, y: number, w: number, h: number, r = 4) => {
  const rr = Math.min(r, w / 2, h)
  return `M${x},${y + h} V${y + rr} Q${x},${y} ${x + rr},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h} Z`
}
const roundedRight = (x: number, y: number, w: number, h: number, r = 4) => {
  const rr = Math.min(r, h / 2, w)
  return `M${x},${y} H${x + w - rr} Q${x + w},${y} ${x + w},${y + rr} V${y + h - rr} Q${x + w},${y + h} ${x + w - rr},${y + h} H${x} Z`
}

// ---------------------------------------------------------------------------------------------
// Chart 1: grouped columns, F1 by concept x method
function F1Chart({ rows, concepts, methods }: { rows: EvalRow[]; concepts: string[]; methods: typeof METHODS[number][] }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const groups = [...concepts, ALL]
  const W = 760, H = 330
  const m = { l: 56, r: 12, t: 16, b: 46 }
  const pw = W - m.l - m.r, ph = H - m.t - m.b
  const y = (v: number) => m.t + ph - v * ph
  const gw = pw / groups.length
  const bw = Math.min(24, (gw * 0.82) / methods.length - 2)
  const cell = (g: string, key: MethodKey) => {
    const r = rows.filter((x) => x.method === key)
    return g === ALL ? macro(r, concepts, 'f1') : stat(r.filter((x) => x.concept === g), 'f1')
  }
  return (
    <div className="relative overflow-x-auto">
      <div className="relative min-w-[680px]">
        <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="group" aria-label="Grouped column chart of F1 score by concept and method. Use the table view for exact values.">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? AXIS : GRID} strokeWidth="1" />
              <text x={m.l - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill={MUTED}>{t.toFixed(2)}</text>
            </g>
          ))}
          <text x={12} y={m.t + ph / 2} fontSize="11" fill={MUTED} transform={`rotate(-90 12 ${m.t + ph / 2})`} textAnchor="middle">F1 at fixed false-alarm rate</text>
          {groups.map((g, gi) => {
            const gx = m.l + gi * gw + (gw - methods.length * (bw + 2) + 2) / 2
            return (
              <g key={g}>
                <text x={m.l + gi * gw + gw / 2} y={H - 22} textAnchor="middle" fontSize="12" fill={g === ALL ? INK : INK2} fontWeight={g === ALL ? 600 : 400}>
                  {g === ALL ? 'All concepts' : conceptName(g)}
                </text>
                {methods.map((me, mi) => {
                  const s = cell(g, me.key)
                  if (!s) return null
                  const x = gx + mi * (bw + 2)
                  const top = y(s.mean)
                  const label = `${me.label}, ${g === ALL ? 'all concepts' : conceptName(g)}: F1 ${s.mean.toFixed(2)}, standard deviation ${s.sd.toFixed(2)} over ${s.n} runs`
                  const show = () => setTip({ x: ((x + bw / 2) / W) * 100, y: (top / H) * 100 - 1, title: me.label, lines: [`F1 ${s.mean.toFixed(3)} ± ${s.sd.toFixed(3)}`, `${s.n} runs (${g === ALL ? 'macro average' : conceptName(g)})`] })
                  return (
                    <g
                      key={me.key}
                      tabIndex={0}
                      role="img"
                      aria-label={label}
                      onPointerEnter={show}
                      onPointerLeave={() => setTip(null)}
                      onFocus={show}
                      onBlur={() => setTip(null)}
                      className="outline-none [&:focus-visible>path]:stroke-white [&:focus-visible>path]:stroke-2 hover:opacity-90"
                    >
                      <rect x={x - 1} y={m.t} width={bw + 2} height={ph} fill="transparent" />
                      <path d={roundedTop(x, top, bw, y(0) - top)} fill={me.color} />
                      {s.sd > 0 && (
                        <g stroke={INK2} strokeWidth="1">
                          <line x1={x + bw / 2} x2={x + bw / 2} y1={y(Math.min(1, s.mean + s.sd))} y2={y(Math.max(0, s.mean - s.sd))} />
                          <line x1={x + bw / 2 - 3} x2={x + bw / 2 + 3} y1={y(Math.min(1, s.mean + s.sd))} y2={y(Math.min(1, s.mean + s.sd))} />
                        </g>
                      )}
                      {me.key === 'exemplar' && (
                        <text x={x + bw / 2} y={y(Math.min(1, s.mean + s.sd)) - 5} textAnchor="middle" fontSize="11" fontWeight="600" fill={INK}>{s.mean.toFixed(2)}</text>
                      )}
                    </g>
                  )
                })}
              </g>
            )
          })}
        </svg>
        <TooltipBox tip={tip} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// Chart 2: validity check, measured false-alarm rate vs alpha
function ValidityChart({ rows, concepts, methods, alpha }: { rows: EvalRow[]; concepts: string[]; methods: typeof METHODS[number][]; alpha: number }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const rowH = 46
  const W = 760
  const m = { l: 150, r: 110, t: 30, b: 34 }
  const H = m.t + methods.length * rowH + m.b
  const pw = W - m.l - m.r
  const all = rows.map((r) => r.false_alarm_rate ?? 0)
  const max = Math.max(0.4, Math.ceil((Math.max(...all, alpha) + 0.02) * 10) / 10)
  const x = (v: number) => m.l + (v / max) * pw
  const ticks = Array.from({ length: Math.round(max / 0.1) + 1 }, (_, i) => +(i * 0.1).toFixed(1))
  return (
    <div className="relative overflow-x-auto">
      <div className="relative min-w-[680px]">
        <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="group" aria-label="Dot plot of measured false-alarm rate by method, with the target alpha marked. Use the table view for exact values.">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={m.t} y2={H - m.b} stroke={t === 0 ? AXIS : GRID} strokeWidth="1" />
              <text x={x(t)} y={H - m.b + 16} textAnchor="middle" fontSize="11" fill={MUTED}>{t.toFixed(1)}</text>
            </g>
          ))}
          <text x={m.l + pw / 2} y={H - 4} textAnchor="middle" fontSize="11" fill={MUTED}>measured false-alarm rate on held-out negatives</text>
          {/* target alpha: a labelled threshold line (dashed = limit, solid = grid) */}
          <line x1={x(alpha)} x2={x(alpha)} y1={m.t - 8} y2={H - m.b} stroke={INK} strokeWidth="2" strokeDasharray="6 4" />
          <text x={x(alpha) + 6} y={m.t - 12} fontSize="12" fontWeight="600" fill={INK}>target α = {alpha.toFixed(2)}</text>
          {methods.map((me, i) => {
            const cy = m.t + i * rowH + rowH / 2
            const r = rows.filter((q) => q.method === me.key)
            const meanAll = stat(r, 'false_alarm_rate')
            const within = r.filter((q) => (q.false_alarm_rate ?? 1) <= alpha).length
            return (
              <g key={me.key}>
                <line x1={m.l} x2={W - m.r} y1={cy} y2={cy} stroke={GRID} strokeWidth="1" />
                <text x={m.l - 12} y={cy + 4} textAnchor="end" fontSize="12" fill={INK2}>{me.label}</text>
                {concepts.map((c) => {
                  const s = stat(r.filter((q) => q.concept === c), 'false_alarm_rate')
                  if (!s) return null
                  const cx = x(s.mean)
                  const label = `${me.label}, ${conceptName(c)}: measured false-alarm rate ${s.mean.toFixed(3)} averaged over ${s.n} runs; target ${alpha}`
                  const show = () => setTip({ x: (cx / W) * 100, y: ((cy - 10) / H) * 100, title: `${me.label} · ${conceptName(c)}`, lines: [`false-alarm rate ${s.mean.toFixed(3)}`, `${s.n} runs · target ${alpha}`] })
                  return (
                    <g key={c} tabIndex={0} role="img" aria-label={label} onPointerEnter={show} onPointerLeave={() => setTip(null)} onFocus={show} onBlur={() => setTip(null)} className="outline-none [&:focus-visible>circle:last-of-type]:stroke-white">
                      <circle cx={cx} cy={cy} r={12} fill="transparent" />
                      <circle cx={cx} cy={cy} r={6} fill={me.color} stroke={SURFACE} strokeWidth="2" />
                    </g>
                  )
                })}
                {meanAll && (
                  <g>
                    <path
                      d={`M${x(meanAll.mean)},${cy - 10} l8,10 l-8,10 l-8,-10 z`}
                      fill={SURFACE}
                      stroke={INK}
                      strokeWidth="2"
                    />
                    <text x={W - m.r + 10} y={cy - 1} fontSize="12" fontWeight="600" fill={INK}>mean {meanAll.mean.toFixed(3)}</text>
                    <text x={W - m.r + 10} y={cy + 13} fontSize="11" fill={MUTED}>{within}/{r.length} runs ≤ α</text>
                  </g>
                )}
              </g>
            )
          })}
        </svg>
        <TooltipBox tip={tip} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
// Chart 3: model cost per event
function CostChart({ rows, concepts, methods }: { rows: EvalRow[]; concepts: string[]; methods: typeof METHODS[number][] }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const rowH = 38
  const W = 760
  const m = { l: 150, r: 90, t: 12, b: 34 }
  const H = m.t + methods.length * rowH + m.b
  const pw = W - m.l - m.r
  const vals = methods.map((me) => macro(rows.filter((r) => r.method === me.key), concepts, 'usd_per_event'))
  const maxV = Math.max(...vals.map((v) => v?.mean ?? 0), 0.001)
  const niceMax = Math.ceil((maxV * 1.05) / 0.01) * 0.01
  const x = (v: number) => m.l + (v / niceMax) * pw
  const ticks = [0, niceMax / 3, (2 * niceMax) / 3, niceMax]
  return (
    <div className="relative overflow-x-auto">
      <div className="relative min-w-[680px]">
        <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" role="group" aria-label="Bar chart of model cost in US dollars per event by method. Use the table view for exact values.">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x(t)} x2={x(t)} y1={m.t} y2={H - m.b} stroke={t === 0 ? AXIS : GRID} strokeWidth="1" />
              <text x={x(t)} y={H - m.b + 16} textAnchor="middle" fontSize="11" fill={MUTED}>{fmtUsd(t)}</text>
            </g>
          ))}
          <text x={m.l + pw / 2} y={H - 4} textAnchor="middle" fontSize="11" fill={MUTED}>model cost per event (USD)</text>
          {methods.map((me, i) => {
            const v = vals[i]
            if (!v) return null
            const cy = m.t + i * rowH + rowH / 2
            const bx = x(0)
            const bwid = Math.max(4, x(v.mean) - bx)
            const label = `${me.label}: ${fmtUsd(v.mean)} per event`
            const show = () => setTip({ x: (x(v.mean) / W) * 100, y: ((cy - 12) / H) * 100, title: me.label, lines: [`${fmtUsd(v.mean)} per event`, 'macro average over concepts'] })
            return (
              <g key={me.key} tabIndex={0} role="img" aria-label={label} onPointerEnter={show} onPointerLeave={() => setTip(null)} onFocus={show} onBlur={() => setTip(null)} className="outline-none [&:focus-visible>path]:stroke-white [&:focus-visible>path]:stroke-2">
                <text x={m.l - 12} y={cy + 4} textAnchor="end" fontSize="12" fill={INK2}>{me.label}</text>
                <rect x={m.l} y={cy - 14} width={pw} height={28} fill="transparent" />
                <path d={roundedRight(bx, cy - 9, bwid, 18)} fill={me.color} />
                <text x={bx + bwid + 8} y={cy + 4} fontSize="12" fontWeight="600" fill={INK}>{fmtUsd(v.mean)}</text>
              </g>
            )
          })}
        </svg>
        <TooltipBox tip={tip} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------------------------
function Table({ head, body }: { head: string[]; body: (string | number)[][] }) {
  return (
    <table className="w-full min-w-[560px] border-separate border-spacing-0 text-sm">
      <thead>
        <tr>{head.map((h, i) => <th key={h} scope="col" className={`border-b border-ex-line2 py-2 pr-4 text-xs font-medium text-ex-ink3 ${i === 0 ? 'text-left' : 'text-right'}`}>{h}</th>)}</tr>
      </thead>
      <tbody>
        {body.map((row, i) => (
          <tr key={i}>
            {row.map((c, j) => j === 0
              ? <th key={j} scope="row" className="border-b border-ex-line py-2.5 pr-4 text-left font-normal text-ex-ink">{c}</th>
              : <td key={j} className="border-b border-ex-line py-2.5 pr-4 text-right font-mono text-xs tabular-nums text-ex-ink2">{c}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------------------------
export default function EvalScreen() {
  const { isMock } = useApp()
  const res = useApi<EvalResults>('/eval/results')
  const [kWant, setK] = useState(3)
  const [qWant, setQ] = useState(3)

  const data = res.data
  const alpha = data?.alpha ?? 0.1
  const concepts = useMemo(() => Array.from(new Set((data?.rows ?? []).map((r) => r.concept))), [data])
  const ks = useMemo(() => Array.from(new Set((data?.rows ?? []).filter((r) => r.method === 'exemplar').map((r) => r.k))).sort(), [data])
  const qs = useMemo(() => Array.from(new Set((data?.rows ?? []).filter((r) => r.method === 'exemplar').map((r) => r.q))).sort(), [data])
  const hasExemplar = ks.length > 0
  // The chosen k / q may not exist in the data (for example before the first Exemplar run): fall back to what does.
  const k = ks.includes(kWant) ? kWant : ks[0] ?? kWant
  const q = qs.includes(qWant) ? qWant : qs[0] ?? qWant
  const rows = useMemo(
    () => (data?.rows ?? []).filter((r) => (r.method === 'exemplar' ? r.k === k && r.q === q : r.method === 'knn_embed' ? r.k === k : true)),
    [data, k, q],
  )
  const methods = METHODS.filter((m) => rows.some((r) => r.method === m.key))

  const f1 = (key: MethodKey) => macro(rows.filter((r) => r.method === key), concepts, 'f1')
  const fa = (key: MethodKey) => macro(rows.filter((r) => r.method === key), concepts, 'false_alarm_rate')
  const usd = (key: MethodKey) => macro(rows.filter((r) => r.method === key), concepts, 'usd_per_event')
  const ex = { f1: f1('exemplar'), fa: fa('exemplar'), usd: usd('exemplar') }
  const zs = { f1: f1('zero_shot_vlm'), fa: fa('zero_shot_vlm'), usd: usd('zero_shot_vlm') }

  return (
    <>
      <PageHeader
        title="Eval"
        subtitle="Does teach-by-example beat prompting a vision model per event, and does the false-alarm guarantee hold? Benchmarked on MEVA outdoor surveillance footage (CC BY 4.0)."
      />
      {isMock && <div className="mb-6"><Alert tone="info" title="Mock numbers">These results come from the mock engine so the charts can be reviewed. Real MEVA results appear when the engine serves them.</Alert></div>}
      {res.loading && !data && (
        <div role="status" aria-label="Loading results" className="grid gap-4"><Skeleton className="h-28 rounded-xl" /><Skeleton className="h-96 rounded-xl" /></div>
      )}
      {res.error && <Alert tone="neg" title="No evaluation results yet">{res.error.message} Run <code className="font-mono">python -m eval.run</code> and reload.</Alert>}
      {data && data.rows.length === 0 && <Empty title="The benchmark has not run yet" icon="gauge">Run <code className="font-mono">python -m eval.run --concept vehicle_dwell --k 3 --q 3 --seeds 5</code>.</Empty>}

      {data && data.rows.length > 0 && (
        <>
          {!hasExemplar && (
            <div className="mb-6">
              <Alert tone="info" title="Exemplar’s runs are not in yet">
                This is the zero-shot baseline only. Run <code className="font-mono text-xs">python -m eval.run</code> to add few-shot results next to it.
              </Alert>
            </div>
          )}
          <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
            {hasExemplar && (
              <>
                <div>
                  <label htmlFor="ev-k" className="field-label">Examples shown (k)</label>
                  <select id="ev-k" className="field w-48" value={k} onChange={(e) => setK(Number(e.target.value))}>
                    {ks.map((v) => <option key={v} value={v}>{v} positive example{v === 1 ? '' : 's'}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="ev-q" className="field-label">Active questions (q)</label>
                  <select id="ev-q" className="field w-48" value={q} onChange={(e) => setQ(Number(e.target.value))}>
                    {qs.map((v) => <option key={v} value={v}>{v} question{v === 1 ? '' : 's'}</option>)}
                  </select>
                </div>
              </>
            )}
            <p className="max-w-xl flex-1 pb-1 text-sm text-ex-ink3">
              Every chart below uses these settings. Zero-shot and Nova see no examples. Error bars are one standard deviation over seeds.
              Generated {new Date(data.generated_at).toLocaleString()}.
            </p>
          </div>

          <div className="mt-6">
            <StatStrip cols="grid-cols-1 sm:grid-cols-3" label="Headline numbers">
              <Stat
                label="F1 at a fixed false-alarm rate"
                size="lg"
                value={ex.f1 ? ex.f1.mean.toFixed(2) : '–'}
                hint={zs.f1 ? <>vs <span className="tabular-nums">{zs.f1.mean.toFixed(2)}</span> for zero-shot prompting</> : undefined}
              />
              <Stat
                label={<>Measured false-alarm rate (target α = {alpha})</>}
                size="lg"
                value={ex.fa ? ex.fa.mean.toFixed(3) : '–'}
                hint={zs.fa ? <>zero-shot: <span className="tabular-nums">{zs.fa.mean.toFixed(3)}</span>, uncalibrated</> : undefined}
              />
              <Stat
                label="Model cost per event"
                size="lg"
                value={ex.usd ? fmtUsd(ex.usd.mean) : '–'}
                hint={zs.usd && ex.usd && ex.usd.mean > 0 ? <><span className="tabular-nums">{(zs.usd.mean / ex.usd.mean).toFixed(1)}×</span> less than zero-shot ({fmtUsd(zs.usd.mean)})</> : zs.usd ? <>zero-shot: {fmtUsd(zs.usd.mean)}</> : undefined}
              />
            </StatStrip>
          </div>

          <div className="mt-8">
          <div className="grid gap-6">
            <ChartCard
              id="f1"
              title="F1 at a fixed false-alarm rate"
              subtitle="Higher is better. Each method is thresholded to the same false-alarm rate, so the comparison is fair."
              legend={<Legend methods={methods} />}
              table={
                <Table
                  head={['Concept', ...methods.map((me) => me.label)]}
                  body={[...concepts, ALL].map((g) => [
                    g === ALL ? 'All concepts (macro average)' : conceptName(g),
                    ...methods.map((me) => {
                      const r = rows.filter((x) => x.method === me.key)
                      const s = g === ALL ? macro(r, concepts, 'f1') : stat(r.filter((x) => x.concept === g), 'f1')
                      return s ? `${s.mean.toFixed(3)} ± ${s.sd.toFixed(3)}` : '-'
                    }),
                  ])}
                />
              }
            >
              <F1Chart rows={rows} concepts={concepts} methods={methods as unknown as typeof METHODS[number][]} />
            </ChartCard>

            <ChartCard
              id="validity"
              title="Validity check: does the false-alarm rate stay under α?"
              subtitle="Each dot is one concept (mean over seeds); the diamond is the method's mean. The guarantee is about the average over calibration draws, so individual runs can land on either side."
              legend={<Legend methods={methods} />}
              table={
                <Table
                  head={['Method', ...concepts.map(conceptName), 'Mean', `Runs ≤ α (${alpha})`]}
                  body={methods.map((me) => {
                    const r = rows.filter((x) => x.method === me.key)
                    return [
                      me.label,
                      ...concepts.map((c) => fmtNum(stat(r.filter((x) => x.concept === c), 'false_alarm_rate')?.mean, 3)),
                      fmtNum(stat(r, 'false_alarm_rate')?.mean, 3),
                      `${r.filter((x) => (x.false_alarm_rate ?? 1) <= alpha).length}/${r.length}`,
                    ]
                  })}
                />
              }
              footer={
                ex.fa && (
                  <p>
                    {ex.fa.mean <= alpha ? (
                      <span className="inline-flex items-center gap-1 text-ex-pos"><Icon name="check" className="h-4 w-4" /> Exemplar’s mean false-alarm rate ({ex.fa.mean.toFixed(3)}) is within α = {alpha}.</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-ex-warn"><Icon name="warning" className="h-4 w-4" /> Exemplar’s mean false-alarm rate ({ex.fa.mean.toFixed(3)}) is above α = {alpha}.</span>
                    )}
                    {zs.fa && <> Prompting a model per event has no such bound: {zs.fa.mean.toFixed(3)}.</>}
                  </p>
                )
              }
            >
              <ValidityChart rows={rows} concepts={concepts} methods={methods as unknown as typeof METHODS[number][]} alpha={alpha} />
            </ChartCard>

            <ChartCard
              id="cost"
              title="Model cost per event"
              subtitle="Lower is better. Exemplar reads each clip once and only escalates events near the decision boundary."
              table={
                <Table
                  head={['Method', 'USD / event', 'Tokens / event', 'p50 latency (s)', 'Escalated']}
                  body={methods.map((me) => {
                    const r = rows.filter((x) => x.method === me.key)
                    return [
                      me.label,
                      fmtUsd(macro(r, concepts, 'usd_per_event')?.mean),
                      fmtInt(macro(r, concepts, 'tokens_per_event')?.mean),
                      fmtNum((macro(r, concepts, 'p50_latency_ms')?.mean ?? 0) / 1000, 1),
                      me.key === 'exemplar' ? `${((macro(r, concepts, 'escalated_fraction')?.mean ?? 0) * 100).toFixed(0)}%` : 'n/a',
                    ]
                  })}
                />
              }
            >
              <CostChart rows={rows} concepts={concepts} methods={methods as unknown as typeof METHODS[number][]} />
            </ChartCard>
          </div>
          </div>
        </>
      )}
    </>
  )
}
