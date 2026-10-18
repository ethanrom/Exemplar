'use client'

import { useId, useState, type PointerEvent } from 'react'
import { dollars, type CostRow } from './cost-types.ts'

// Model cost per event as rules are added. Redrawn from the published table (docs/eval/cost_vs_rules.md), which the
// page shows next to it as the text twin. Two series, one axis. Series colours are validated for the dark panel
// surface (OKLCH lightness band, CVD separation, contrast >= 3:1); text stays in text colours.

const W = 420
const H = 262
const X0 = 64
const X1 = 404
const Y0 = 20
const Y1 = 216
const YMAX = 0.15
const EXEMPLAR = '#3987e5'
const ZERO_SHOT = '#d95926'
const SURFACE = '#111316'

const xAt = (rules: number) => X0 + ((rules - 1) / 9) * (X1 - X0)
const yAt = (v: number) => Y1 - (v / YMAX) * (Y1 - Y0)

export function CostChart({ rows }: { rows: CostRow[] }) {
  const [n, setN] = useState(10)
  const uid = useId()
  const titleId = `${uid}-title`
  const descId = `${uid}-desc`
  const sliderId = `${uid}-rules`

  const cur = rows[n - 1] as CostRow
  const last = rows[rows.length - 1] as CostRow
  const valueText = `${n} ${n === 1 ? 'rule' : 'rules'}: Exemplar ${cur.exemplar} per event, zero-shot prompting ${cur.zeroShot} per event, ${cur.ratio}`

  const zeroPoints = rows.map((r) => `${xAt(r.rules).toFixed(1)},${yAt(dollars(r.zeroShot)).toFixed(1)}`).join(' ')
  const exemplarPoints = rows.map((r) => `${xAt(r.rules).toFixed(1)},${yAt(dollars(r.exemplar)).toFixed(1)}`).join(' ')

  function onMove(e: PointerEvent<SVGSVGElement>) {
    const box = e.currentTarget.getBoundingClientRect()
    if (box.width === 0) return
    const x = ((e.clientX - box.left) / box.width) * W
    const k = Math.round(((x - X0) / (X1 - X0)) * 9) + 1
    setN(Math.min(10, Math.max(1, k)))
  }

  return (
    <figure className="m-0">
      <ul className="mb-3 flex flex-wrap gap-x-6 gap-y-1.5 text-sm text-ex-ink2" aria-label="Legend">
        <li className="inline-flex items-center gap-2">
          <svg width="28" height="12" viewBox="0 0 28 12" aria-hidden="true"><line x1="0" y1="6" x2="28" y2="6" stroke={EXEMPLAR} strokeWidth="2" strokeLinecap="round" /><circle cx="14" cy="6" r="4.5" fill={EXEMPLAR} stroke={SURFACE} strokeWidth="2" /></svg>
          Exemplar (perceive once, score every rule)
        </li>
        <li className="inline-flex items-center gap-2">
          <svg width="28" height="12" viewBox="0 0 28 12" aria-hidden="true"><line x1="0" y1="6" x2="28" y2="6" stroke={ZERO_SHOT} strokeWidth="2" strokeLinecap="round" /><rect x="9.5" y="1.5" width="9" height="9" fill={ZERO_SHOT} stroke={SURFACE} strokeWidth="2" /></svg>
          Zero-shot prompting (one call per rule)
        </li>
      </ul>

      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full max-w-[480px] touch-pan-y" role="img" aria-labelledby={`${titleId} ${descId}`} onPointerMove={onMove} onPointerDown={onMove}>
        <title id={titleId}>Model cost per event as rules are added</title>
        <desc id={descId}>
          Line chart of US dollars per event for 1 to 10 deployed rules. Exemplar is flat at {rows[0]?.exemplar} per event. Zero-shot prompting
          rises from {rows[0]?.zeroShot} at 1 rule to {last.zeroShot} at 10 rules. The same numbers are in the table below the chart.
        </desc>

        {[0, 0.05, 0.1, 0.15].map((v) => (
          <g key={v}>
            <line x1={X0} x2={X1} y1={yAt(v)} y2={yAt(v)} stroke={v === 0 ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.08)'} strokeWidth="1" />
            <text x={X0 - 8} y={yAt(v) + 4.5} textAnchor="end" fontSize="13" className="fill-ex-ink3">${v.toFixed(2)}</text>
          </g>
        ))}
        {rows.map((r) => (
          <text key={r.rules} x={xAt(r.rules)} y={Y1 + 18} textAnchor="middle" fontSize="13" className="fill-ex-ink3">{r.rules}</text>
        ))}
        <text x={(X0 + X1) / 2} y={Y1 + 39} textAnchor="middle" fontSize="13" className="fill-ex-ink2">Rules deployed on the camera</text>
        <text x={9} y={(Y0 + Y1) / 2} textAnchor="middle" fontSize="13" className="fill-ex-ink2" transform={`rotate(-90 9 ${(Y0 + Y1) / 2})`}>US dollars per event</text>

        <line x1={xAt(n)} x2={xAt(n)} y1={Y0} y2={Y1} stroke="rgba(255,255,255,0.3)" strokeWidth="1" />

        <polyline points={zeroPoints} fill="none" stroke={ZERO_SHOT} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        <polyline points={exemplarPoints} fill="none" stroke={EXEMPLAR} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

        {rows.map((r) => {
          const big = r.rules === n
          const s = big ? 7 : 5
          return (
            <g key={r.rules}>
              <rect x={xAt(r.rules) - s} y={yAt(dollars(r.zeroShot)) - s} width={s * 2} height={s * 2} fill={ZERO_SHOT} stroke={SURFACE} strokeWidth="2" />
              <circle cx={xAt(r.rules)} cy={yAt(dollars(r.exemplar))} r={s} fill={EXEMPLAR} stroke={SURFACE} strokeWidth="2" />
            </g>
          )
        })}

        <text x={X1 - 16} y={Y0 + 10} textAnchor="end" fontSize="13" fontWeight="600" className="fill-ex-ink">Zero-shot prompting</text>
        <text x={X1 - 16} y={Y0 + 26} textAnchor="end" fontSize="13" className="fill-ex-ink2">{last.zeroShot} at 10 rules</text>
        <text x={X1 - 8} y={Y1 - 28} textAnchor="end" fontSize="13" fontWeight="600" className="fill-ex-ink">Exemplar</text>
        <text x={X1 - 8} y={Y1 - 10} textAnchor="end" fontSize="13" className="fill-ex-ink2">{rows[0]?.exemplar} per event, flat</text>

      </svg>

      <figcaption className="mt-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <label htmlFor={sliderId} className="text-sm font-medium text-ex-ink">Rules deployed</label>
          <input
            id={sliderId}
            type="range"
            min={1}
            max={10}
            step={1}
            value={n}
            onChange={(e) => setN(Number(e.currentTarget.value))}
            aria-valuetext={valueText}
            className="h-6 w-full max-w-xs cursor-pointer accent-[#7FAEFF]"
          />
        </div>
        <p className="mt-2 text-sm text-ex-ink2" data-src={`cost-table:row:${cur.rules}`}>
          <span className="font-medium text-ex-ink">{n} {n === 1 ? 'rule' : 'rules'}:</span>{' '}
          Exemplar <span className="tabular-nums text-ex-ink">{cur.exemplar}</span> per event; zero-shot prompting{' '}
          <span className="tabular-nums text-ex-ink">{cur.zeroShot}</span> per event ({cur.ratio}).
        </p>
      </figcaption>
    </figure>
  )
}
