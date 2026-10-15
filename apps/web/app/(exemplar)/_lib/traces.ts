'use client'

// Lazy, cached, concurrency-limited reads of an event's symbolic trace (GET /events/{id}), used to draw the
// mini trace strip that stands in for a snapshot when a clip has no picture.
import { useEffect, useState } from 'react'
import { get } from './api'
import type { EventDetail, Trace } from './types'

const cache = new Map<string, Trace | null>()
const inflight = new Map<string, Promise<Trace | null>>()
const queue: (() => void)[] = []
let active = 0
const LIMIT = 3

function pump() {
  while (active < LIMIT && queue.length) {
    const next = queue.shift()!
    active++
    next()
  }
}

export function loadTrace(eventId: string): Promise<Trace | null> {
  if (cache.has(eventId)) return Promise.resolve(cache.get(eventId) ?? null)
  const existing = inflight.get(eventId)
  if (existing) return existing
  const p = new Promise<Trace | null>((resolve) => {
    queue.push(() => {
      get<EventDetail>(`/events/${encodeURIComponent(eventId)}`)
        .then((d) => d.trace ?? null)
        .catch(() => null)
        .then((t) => {
          cache.set(eventId, t)
          inflight.delete(eventId)
          active--
          resolve(t)
          pump()
        })
    })
    pump()
  })
  inflight.set(eventId, p)
  return p
}

/** `undefined` while loading, `null` when the event has no readable trace. */
export function useTrace(eventId: string, enabled: boolean): Trace | null | undefined {
  const [trace, setTrace] = useState<Trace | null | undefined>(() => (enabled && cache.has(eventId) ? cache.get(eventId) : undefined))
  useEffect(() => {
    if (!enabled) { setTrace(null); return }
    if (cache.has(eventId)) { setTrace(cache.get(eventId) ?? null); return }
    let alive = true
    setTrace(undefined)
    loadTrace(eventId).then((t) => { if (alive) setTrace(t) })
    return () => { alive = false }
  }, [eventId, enabled])
  return trace
}
