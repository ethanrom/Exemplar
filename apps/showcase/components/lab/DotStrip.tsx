import { cx } from '../cx.ts'
import { fmtPlain, fmtScore } from './core/format.ts'

export type Dot = { id: string; score: number; label: 'pos' | 'neg'; rank?: number }

const LO = -0.5
const HI = 0.5
const DOT = 12 // px
const GAP = 2

const pos = (s: number) => ((s - LO) / (HI - LO)) * 100

/**
 * The scores of a calibration sample on the robustness axis [-0.5, +0.5]: red dots for random negatives, green for random
 * positives, equal scores stacked. Marks the k-th smallest negative (it becomes tau_alpha) and the final threshold tau.
 * The same numbers are available as a table next to it; the strip itself is a described image.
 */
export function DotStrip({
  dots, kth, tauAlpha, tau, label,
}: { dots: Dot[]; kth?: number | null; tauAlpha?: number | null; tau?: number | null; label: string }) {
  // stack equal scores per label
  const stacks = new Map<string, number>()
  const placed = dots.map((d) => {
    const key = `${d.label}:${d.score.toFixed(6)}`
    const n = stacks.get(key) ?? 0
    stacks.set(key, n + 1)
    return { ...d, level: n }
  })
  const maxLevel = (lab: 'pos' | 'neg') => Math.max(0, ...placed.filter((p) => p.label === lab).map((p) => p.level))
  const laneH = (lab: 'pos' | 'neg') => (maxLevel(lab) + 1) * (DOT + GAP) + 6
  const negH = laneH('neg')
  const posH = laneH('pos')
  const ticks = [-0.5, -0.25, 0, 0.25, 0.5]
  return (
    <div role="img" aria-label={label} className="relative rounded-lg border border-ex-line bg-ex-bg px-5 pb-7 pt-8">
      {/* marker labels sit above the lanes */}
      {tau != null && (
        <span aria-hidden="true" className="absolute top-1.5 -translate-x-1/2 whitespace-nowrap font-mono text-xs text-ex-warn" style={{ left: `calc(20px + (100% - 40px) * ${pos(tau) / 100})` }}>
          τ = {fmtPlain(tau)}
        </span>
      )}
      <div className="relative" style={{ marginLeft: 0, marginRight: 0 }}>
        <div className="relative" style={{ height: negH }}>
          {placed.filter((p) => p.label === 'neg').map((p) => (
            <span
              key={p.id}
              className={cx('absolute -translate-x-1/2 rounded-full bg-ex-neg', p.rank !== undefined && kth === p.rank && 'ring-2 ring-ex-ink ring-offset-1 ring-offset-ex-bg')}
              style={{ width: DOT, height: DOT, left: `${pos(p.score)}%`, bottom: 3 + p.level * (DOT + GAP) }}
            />
          ))}
        </div>
        <div aria-hidden="true" className="relative h-px bg-ex-line2" />
        <div className="relative" style={{ height: posH }}>
          {placed.filter((p) => p.label === 'pos').map((p) => (
            <span key={p.id} className="absolute -translate-x-1/2 rounded-sm bg-ex-pos" style={{ width: DOT - 2, height: DOT - 2, left: `${pos(p.score)}%`, top: 3 + p.level * (DOT + GAP) }} />
          ))}
        </div>
        {tauAlpha != null && (
          <span aria-hidden="true" className="absolute inset-y-0 w-px border-l border-dashed border-ex-ink3" style={{ left: `${pos(tauAlpha)}%` }} />
        )}
        {tau != null && <span aria-hidden="true" className="absolute inset-y-0 w-0.5 bg-ex-warn" style={{ left: `${pos(tau)}%` }} />}
        <div aria-hidden="true" className="absolute inset-x-0 -bottom-5 text-xs text-ex-ink3">
          {ticks.map((t) => (
            <span key={t} className={cx('absolute font-mono tabular-nums', t === LO ? '' : t === HI ? '-translate-x-full' : '-translate-x-1/2')} style={{ left: `${pos(t)}%` }}>{t > 0 ? '+' : ''}{fmtPlain(t)}</span>
          ))}
        </div>
      </div>
      <span className="sr-only">Axis from {fmtScore(LO)} to {fmtScore(HI)}.</span>
    </div>
  )
}
