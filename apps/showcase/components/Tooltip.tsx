'use client'

import { cloneElement, isValidElement, useEffect, useId, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { cx } from './cx.ts'
import { Icon } from './Icon.tsx'

type Side = 'top' | 'bottom'
type Align = 'start' | 'center' | 'end'

const SIDE: Record<Side, string> = { top: 'bottom-full pb-1.5', bottom: 'top-full pt-1.5' }
const ALIGN: Record<Align, string> = { start: 'left-0', center: 'left-1/2 -translate-x-1/2', end: 'right-0' }

/**
 * Tooltip that meets WCAG 1.4.13: it appears on hover and on keyboard focus, stays while the pointer is over
 * it, and Escape dismisses it. `children` must be one focusable element (a button or a link): it gets
 * `aria-describedby`. For a bare icon use <InfoTip>.
 */
export function Tooltip({
  content, children, side = 'top', align = 'center', className,
}: {
  content: ReactNode
  children: ReactElement<{ 'aria-describedby'?: string }>
  side?: Side
  align?: Align
  className?: string
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)

  // Tapping the trigger opens it on touch screens; tapping elsewhere closes it.
  useEffect(() => {
    if (!open) return
    const away = (e: PointerEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])

  const trigger = isValidElement(children)
    ? cloneElement(children, { 'aria-describedby': [children.props['aria-describedby'], id].filter(Boolean).join(' ') })
    : children

  return (
    <span
      ref={root}
      className={cx('relative inline-flex', className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false) }}
      onClick={() => setOpen(true)}
      onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}
    >
      {trigger}
      <span
        role="tooltip"
        id={id}
        className={cx('absolute z-30 w-max max-w-[min(18rem,calc(100vw-2rem))]', SIDE[side], ALIGN[align], open ? 'block' : 'hidden')}
      >
        <span className="block rounded-md border border-ex-line2 bg-ex-raised px-2.5 py-1.5 text-xs leading-4 text-ex-ink shadow-lg">
          {content}
        </span>
      </span>
    </span>
  )
}

/** A small "i" button that explains a term or a number in a sentence. */
export function InfoTip({
  children, label = 'More information', side, align,
}: { children: ReactNode; label?: string; side?: Side; align?: Align }) {
  return (
    <Tooltip content={children} side={side} align={align}>
      <button type="button" aria-label={label} className="btn-icon h-6 w-6">
        <Icon name="info" className="h-3.5 w-3.5" />
      </button>
    </Tooltip>
  )
}
