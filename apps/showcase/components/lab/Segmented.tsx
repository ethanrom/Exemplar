'use client'

import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { cx } from '../cx.ts'

export type SegmentedOption<T extends string> = { id: T; label: ReactNode; hint?: ReactNode; disabled?: boolean }

/**
 * A choice of one among a few, as a WAI-ARIA radio group: one tab stop, arrow keys move and select, Home and End jump.
 * Use it for the run selector, the event picker and the like (it is not a tab list: it does not switch panels).
 */
export function Segmented<T extends string>({
  label, value, options, onChange, className, size = 'md',
}: {
  label: string
  value: T
  options: SegmentedOption<T>[]
  onChange: (id: T) => void
  className?: string
  size?: 'sm' | 'md'
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})
  const enabled = options.filter((o) => !o.disabled)
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, id: T) => {
    const i = enabled.findIndex((o) => o.id === id)
    let next = -1
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % enabled.length
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + enabled.length) % enabled.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = enabled.length - 1
    if (next < 0) return
    e.preventDefault()
    const target = enabled[next]
    if (!target) return
    refs.current[target.id]?.focus()
    onChange(target.id)
  }
  return (
    <div role="radiogroup" aria-label={label} className={cx('inline-flex max-w-full flex-wrap gap-1 rounded-lg border border-ex-line bg-ex-panel p-1', className)}>
      {options.map((o) => {
        const on = o.id === value
        return (
          <button
            key={o.id}
            ref={(el) => { refs.current[o.id] = el }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            disabled={o.disabled}
            onClick={() => onChange(o.id)}
            onKeyDown={(e) => onKeyDown(e, o.id)}
            className={cx(
              'inline-flex min-w-[44px] flex-col items-start justify-center rounded-md px-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              size === 'sm' ? 'min-h-[32px] py-1 text-sm' : 'min-h-[40px] py-1.5 text-base',
              on ? 'bg-ex-accent-soft text-ex-ink ring-1 ring-ex-accent-line' : 'text-ex-ink2 hover:bg-ex-hover hover:text-ex-ink',
            )}
          >
            <span className="font-medium">{o.label}</span>
            {o.hint && <span className="text-xs text-ex-ink3">{o.hint}</span>}
          </button>
        )
      })}
    </div>
  )
}
