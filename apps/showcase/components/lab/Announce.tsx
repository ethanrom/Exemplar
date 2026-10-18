'use client'

import { useEffect, useState } from 'react'

/**
 * Text for a polite live region that follows `text` after it has stopped changing for `delay` ms, so dragging a
 * slider announces the settled result once instead of every intermediate value.
 */
export function useSettled(text: string, delay = 400): string {
  const [settled, setSettled] = useState(text)
  useEffect(() => {
    const id = window.setTimeout(() => setSettled(text), delay)
    return () => window.clearTimeout(id)
  }, [text, delay])
  return settled
}

/** A visually hidden polite live region (WCAG 4.1.3). Keep the element mounted; change only its text. */
export function LiveRegion({ text, delay = 400 }: { text: string; delay?: number }) {
  const settled = useSettled(text, delay)
  return (
    <p role="status" aria-live="polite" aria-atomic="true" className="sr-only">
      {settled}
    </p>
  )
}
