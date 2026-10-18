'use client'

import { useId, type KeyboardEvent, type ReactNode } from 'react'
import { cx } from '../cx.ts'

export type SliderMark = { value: number; label: string; tone?: 'accent' | 'pos' | 'neg' | 'warn' | 'neutral' }

const MARK_TONE: Record<NonNullable<SliderMark['tone']>, string> = {
  accent: 'bg-ex-accent-ink',
  pos: 'bg-ex-pos',
  neg: 'bg-ex-neg',
  warn: 'bg-ex-warn',
  neutral: 'bg-ex-ink3',
}

const THUMB = 18 // px, keep in sync with the thumb classes below

/**
 * A labelled range slider. It is the native <input type="range">, so arrow keys, Home and End work everywhere; Page Up
 * and Page Down are handled here (a larger step) so they behave the same in every browser. `valueText` becomes
 * aria-valuetext, so a screen reader hears "15 seconds" instead of "15".
 */
export function Slider({
  label, value, min, max, step, onChange, valueText, display, pageStep, marks, describedBy, disabled, className, hint,
}: {
  label: ReactNode
  value: number
  min: number
  max: number
  step: number
  onChange: (v: number) => void
  /** Spoken value, e.g. (v) => `${v} seconds`. */
  valueText: (v: number) => string
  /** Visible value next to the label (defaults to valueText). */
  display?: ReactNode
  pageStep?: number
  /** Tick marks under the track (for example the recorded value). Decorative: each is also listed in `hint`. */
  marks?: SliderMark[]
  describedBy?: string
  disabled?: boolean
  className?: string
  hint?: ReactNode
}) {
  const id = useId()
  const big = pageStep ?? Math.max(step, Math.round((max - min) / 10 / step) * step)
  const clampSnap = (v: number) => {
    const k = Math.round((v - min) / step)
    return Math.min(max, Math.max(min, +(min + k * step).toFixed(6)))
  }
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'PageUp') { e.preventDefault(); onChange(clampSnap(value + big)) }
    else if (e.key === 'PageDown') { e.preventDefault(); onChange(clampSnap(value - big)) }
  }
  const pos = (v: number) => (max === min ? 0 : (v - min) / (max - min))
  return (
    <div className={cx('w-full', className)}>
      <div className="mb-1 flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-ex-ink">{label}</label>
        <span className="font-mono text-sm tabular-nums text-ex-ink" aria-hidden="true">{display ?? valueText(value)}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        aria-valuetext={valueText(value)}
        aria-describedby={describedBy}
        onChange={(e) => onChange(Number(e.target.value))}
        onKeyDown={onKeyDown}
        className={cx(
          'block h-6 w-full cursor-pointer appearance-none bg-transparent disabled:cursor-not-allowed disabled:opacity-50',
          '[&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:rounded-full [&::-webkit-slider-runnable-track]:bg-ex-line2',
          '[&::-moz-range-track]:h-1.5 [&::-moz-range-track]:rounded-full [&::-moz-range-track]:bg-ex-line2',
          '[&::-webkit-slider-thumb]:-mt-[6px] [&::-webkit-slider-thumb]:h-[18px] [&::-webkit-slider-thumb]:w-[18px] [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-ex-bg [&::-webkit-slider-thumb]:bg-ex-accent-ink',
          '[&::-moz-range-thumb]:h-[14px] [&::-moz-range-thumb]:w-[14px] [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-ex-bg [&::-moz-range-thumb]:bg-ex-accent-ink',
        )}
      />
      {marks && marks.length > 0 && (
        <div aria-hidden="true" className="relative mt-0.5 h-4">
          {marks.map((m) => (
            <span
              key={m.label + m.value}
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center"
              style={{ left: `calc(${pos(m.value) * 100}% + ${(0.5 - pos(m.value)) * THUMB}px)` }}
            >
              <span className={cx('h-1.5 w-0.5 rounded-full', MARK_TONE[m.tone ?? 'neutral'])} />
            </span>
          ))}
        </div>
      )}
      {hint && <div className="mt-1 text-xs text-ex-ink3">{hint}</div>}
    </div>
  )
}
