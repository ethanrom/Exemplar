'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, engineUrl, get } from './api'

export interface ApiState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => Promise<void>
  setData: (v: T | null | ((prev: T | null) => T | null)) => void
}

/**
 * GET `path` through the engine proxy. Keeps the previous data while reloading (no flash), aborts on
 * unmount / path change, optionally polls every `interval` ms. Pass `null` to skip fetching.
 */
export function useApi<T>(path: string | null, opts: { interval?: number } = {}): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState<boolean>(path !== null)
  const pathRef = useRef(path)
  pathRef.current = path
  const alive = useRef(true)

  const load = useCallback(async (signal?: AbortSignal) => {
    const p = pathRef.current
    if (p === null) return
    try {
      const res = await get<T>(p, signal)
      if (!alive.current || pathRef.current !== p) return
      setData(res)
      setError(null)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      if (!alive.current || pathRef.current !== p) return
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)))
    } finally {
      if (alive.current && pathRef.current === p) setLoading(false)
    }
  }, [])

  useEffect(() => {
    alive.current = true
    if (path === null) {
      setData(null)
      setError(null)
      setLoading(false)
      return
    }
    setLoading(true)
    const ctrl = new AbortController()
    load(ctrl.signal)
    let timer: ReturnType<typeof setInterval> | undefined
    if (opts.interval) timer = setInterval(() => load(), opts.interval)
    return () => {
      alive.current = false
      ctrl.abort()
      if (timer) clearInterval(timer)
    }
  }, [path, opts.interval, load])

  const reload = useCallback(() => load(), [load])
  return { data, error, loading, reload, setData }
}

/** Re-renders every `ms` and returns Date.now(). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

/**
 * Subscribe to a server-sent-event stream through the proxy. `onEvent(type, data)` is called for every
 * named event in `types`; `ping` frames are ignored. The browser's EventSource reconnects on its own and
 * sends Last-Event-ID. Return false from `onEvent` to close the stream (e.g. after `done`).
 */
export function useEventStream<T>(
  path: string | null,
  types: readonly string[],
  onEvent: (type: string, data: T) => boolean | void,
): StreamStatus {
  const [status, setStatus] = useState<StreamStatus>('idle')
  const handler = useRef(onEvent)
  handler.current = onEvent
  const typeKey = types.join(',')

  useEffect(() => {
    if (path === null) {
      setStatus('idle')
      return
    }
    setStatus('connecting')
    const es = new EventSource(engineUrl(path))
    es.onopen = () => setStatus('open')
    es.onerror = () => setStatus(es.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting')
    const listeners: [string, (e: MessageEvent) => void][] = typeKey.split(',').filter(Boolean).map((t) => {
      const fn = (e: MessageEvent) => {
        let data: T
        try {
          data = JSON.parse(e.data) as T
        } catch {
          return
        }
        if (handler.current(t, data) === false) {
          es.close()
          setStatus('closed')
        }
      }
      es.addEventListener(t, fn as EventListener)
      return [t, fn]
    })
    return () => {
      for (const [t, fn] of listeners) es.removeEventListener(t, fn as EventListener)
      es.close()
    }
  }, [path, typeKey])

  return status
}

/** Persisted state (localStorage), safe for SSR. */
export function useStoredState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(initial)
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(key)
      if (raw !== null) setValue(JSON.parse(raw) as T)
    } catch {
      /* ignore */
    }
  }, [key])
  const set = useCallback(
    (v: T) => {
      setValue(v)
      try {
        window.localStorage.setItem(key, JSON.stringify(v))
      } catch {
        /* ignore */
      }
    },
    [key],
  )
  return [value, set]
}
