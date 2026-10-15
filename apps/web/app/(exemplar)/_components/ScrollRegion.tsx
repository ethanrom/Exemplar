'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { cx } from './ui'

/**
 * A keyboard-focusable scroll area that fades its edge where more content is hidden, so a row cut by the
 * scroll boundary reads as "scroll for more" rather than as a layout bug.
 */
export function ScrollRegion({
  label, className = '', children,
}: { label: string; className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [more, setMore] = useState(false)
  const [less, setLess] = useState(false)

  const update = useCallback(() => {
    const el = ref.current
    if (!el) return
    setMore(el.scrollTop + el.clientHeight < el.scrollHeight - 4)
    setLess(el.scrollTop > 4)
  }, [])

  useEffect(() => {
    update()
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(update)
    ro.observe(el)
    if (el.firstElementChild) ro.observe(el.firstElementChild)
    return () => ro.disconnect()
  }, [update, children])

  return (
    <div className="relative">
      <div ref={ref} onScroll={update} tabIndex={0} role="region" aria-label={label} className={cx('overflow-y-auto', className)}>
        {children}
      </div>
      {less && <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-8 bg-gradient-to-b from-ex-panel to-transparent" />}
      {more && <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-ex-panel to-transparent" />}
    </div>
  )
}
