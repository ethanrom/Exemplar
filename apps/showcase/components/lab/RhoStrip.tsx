import { cx } from '../cx.ts'

/** Position (0..1) of a time on a strip that gives each sampled frame an equal cell, interpolating between frame centres. */
export function xOfTime(tMs: number, timesMs: readonly number[], durationMs: number): number {
  const T = timesMs.length
  if (T === 0) return 0
  const first = timesMs[0] as number
  const last = timesMs[T - 1] as number
  if (tMs <= first) return first <= 0 ? 0.5 / T : (0.5 / T) * Math.max(0, tMs / first)
  if (tMs >= last) {
    const span = durationMs - last
    return span <= 0 ? (T - 0.5) / T : (T - 0.5) / T + (0.5 / T) * Math.min(1, (tMs - last) / span)
  }
  for (let i = 0; i + 1 < T; i++) {
    const a = timesMs[i] as number
    const b = timesMs[i + 1] as number
    if (tMs <= b) return (i + 0.5 + (b === a ? 0 : (tMs - a) / (b - a))) / T
  }
  return (T - 0.5) / T
}

const HALF = 0.5 // the clamp C: robustness lies in [-0.5, 0.5]

/**
 * Body robustness at each sampled frame as bars: up (and green) when the part of the rule holds there, down (and red)
 * when it does not, with an optional window drawn behind them (the span the rule asked about). The cells are equal in
 * width; the window is placed by time.
 */
export function RhoStrip({
  timesMs, rho, durationMs, window: win, windowLabel, label, height = 64, className, selected,
}: {
  timesMs: readonly number[]
  rho: readonly number[]
  durationMs: number
  window?: { startMs: number; endMs: number } | null
  windowLabel?: string
  /** Accessible description of the whole strip. */
  label: string
  height?: number
  className?: string
  selected?: number
}) {
  const T = timesMs.length
  const half = height / 2
  const left = win ? xOfTime(win.startMs, timesMs, durationMs) : 0
  const right = win ? xOfTime(win.endMs, timesMs, durationMs) : 0
  return (
    <div role="img" aria-label={label} className={cx('relative w-full overflow-hidden rounded-md border border-ex-line bg-ex-bg', className)} style={{ height }}>
      {win && (
        <div
          className="absolute inset-y-0 border-x-2 border-ex-accent-ink bg-ex-accent-soft"
          style={{ left: `${left * 100}%`, width: `${Math.max(right - left, 0.004) * 100}%` }}
          title={windowLabel}
        />
      )}
      <div aria-hidden="true" className="absolute inset-x-0 border-t border-dashed border-ex-line2" style={{ top: half }} />
      {rho.map((r, i) => {
        const h = Math.max(2, (Math.abs(r) / HALF) * (half - 3))
        const pos = r > 0
        return (
          <div key={i} aria-hidden="true" className="absolute top-0 h-full" style={{ left: `${(i / T) * 100}%`, width: `${100 / T}%` }}>
            <div
              className={cx('absolute left-1/2 w-[55%] max-w-[18px] -translate-x-1/2 rounded-sm', pos ? 'bg-ex-pos' : 'bg-ex-neg', selected === i && 'ring-2 ring-ex-ink')}
              style={pos ? { bottom: half, height: h } : { top: half, height: h }}
            />
          </div>
        )
      })}
    </div>
  )
}
