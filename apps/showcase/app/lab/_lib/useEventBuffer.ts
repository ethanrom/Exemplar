'use client'

import { startTransition, useCallback, useEffect, useRef, useState } from 'react'

/**
 * Collects streamed events and publishes them to React at most every `interval` ms, so a solve that emits a hundred events
 * costs a handful of renders, not a hundred (no main-thread task should run long while the worker streams).
 */
export function useEventBuffer<T>(interval = 100) {
  const buf = useRef<T[]>([])
  const timer = useRef<number | null>(null)
  const [events, setEvents] = useState<T[]>([])

  const clear = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
  }
  const flush = useCallback(() => {
    clear()
    startTransition(() => setEvents(buf.current.slice()))
  }, [])
  const push = useCallback((e: T) => {
    buf.current.push(e)
    if (timer.current === null) {
      timer.current = window.setTimeout(() => {
        timer.current = null
        startTransition(() => setEvents(buf.current.slice()))
      }, interval)
    }
  }, [interval])
  const reset = useCallback(() => {
    clear()
    buf.current = []
    setEvents([])
  }, [])
  useEffect(() => clear, [])
  return { events, push, reset, flush }
}
