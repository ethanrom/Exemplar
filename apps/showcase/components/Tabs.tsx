'use client'

import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { cx } from './cx.ts'

export type TabItem = {
  id: string
  label: ReactNode
  /** Short extra on the tab (a count, a status). Keep it text; it is read as part of the tab name. */
  badge?: ReactNode
  disabled?: boolean
  panel: ReactNode
}

type TabsProps = {
  tabs: TabItem[]
  /** Accessible name of the tab list. */
  label: string
  /** Controlled selection. Omit it and use `defaultValue` for an uncontrolled instance. */
  value?: string
  defaultValue?: string
  onValueChange?: (id: string) => void
  /** `auto`: arrow keys select (default). `manual`: arrow keys move focus, Enter or Space selects (use when selecting is expensive). */
  activation?: 'auto' | 'manual'
  className?: string
}

/**
 * WAI-ARIA tabs: roving tabindex, Left/Right/Home/End, optional manual activation.
 * Every panel stays mounted; inactive ones are `hidden`.
 */
export function Tabs({ tabs, label, value, defaultValue, onValueChange, activation = 'auto', className }: TabsProps) {
  const base = useId()
  const enabled = tabs.filter((t) => !t.disabled)
  const [inner, setInner] = useState(defaultValue ?? enabled[0]?.id ?? tabs[0]?.id ?? '')
  const selected = value ?? inner
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  const select = (id: string) => {
    if (value === undefined) setInner(id)
    onValueChange?.(id)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, id: string) => {
    const i = enabled.findIndex((t) => t.id === id)
    let next: number | null = null
    if (e.key === 'ArrowRight') next = (i + 1) % enabled.length
    else if (e.key === 'ArrowLeft') next = (i - 1 + enabled.length) % enabled.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = enabled.length - 1
    if (next === null) return
    e.preventDefault()
    const target = enabled[next]
    if (!target) return
    refs.current[target.id]?.focus()
    if (activation === 'auto') select(target.id)
  }

  const tabId = (id: string) => `${base}-tab-${id}`
  const panelId = (id: string) => `${base}-panel-${id}`

  return (
    <div className={className}>
      <div role="tablist" aria-label={label} className="-mx-1 flex gap-0.5 overflow-x-auto border-b border-ex-line px-1">
        {tabs.map((t) => {
          const on = t.id === selected
          return (
            <button
              key={t.id}
              ref={(el) => { refs.current[t.id] = el }}
              type="button"
              role="tab"
              id={tabId(t.id)}
              aria-selected={on}
              aria-controls={panelId(t.id)}
              tabIndex={on ? 0 : -1}
              disabled={t.disabled}
              onClick={() => select(t.id)}
              onKeyDown={(e) => onKeyDown(e, t.id)}
              className={cx(
                '-mb-px inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-base font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                on ? 'border-ex-accent-ink text-ex-ink' : 'border-transparent text-ex-ink2 hover:text-ex-ink',
              )}
            >
              {t.label}
              {t.badge != null && <span className="tabular-nums text-ex-ink3">{t.badge}</span>}
            </button>
          )
        })}
      </div>
      {tabs.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          id={panelId(t.id)}
          aria-labelledby={tabId(t.id)}
          hidden={t.id !== selected}
          tabIndex={0}
          className="pt-4"
        >
          {t.panel}
        </div>
      ))}
    </div>
  )
}
