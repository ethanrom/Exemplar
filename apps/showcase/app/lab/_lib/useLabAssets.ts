'use client'

import { useEffect, useState } from 'react'
import { Grid } from '../../../lib/synth/compare/grid.ts'
import type { TraceJson } from '../../../lib/data/types.ts'

export type ClosedDoc = {
  format: string
  clips: string[]
  rules: { key: string; sketch: number; holes: number[]; dsl_text: string; english: string; mdl: number; scores: number[] }[]
}

export type Assets = {
  /** Every library trace by alias (the facts the evaluator reads). */
  traces: Record<string, TraceJson> | null
  tracesError: boolean
  /** The engine's precomputed results for every label combination; 'unavailable' when it did not load. */
  grid: Grid | null
  gridStatus: 'loading' | 'ready' | 'unavailable'
  closed: ClosedDoc | null
}

async function getJson<T>(url: string): Promise<T | null> {
  const r = await fetch(url)
  if (!r.ok) return null
  return (await r.json()) as T | null
}

/**
 * Loads the static files the Lab computes with: the library's traces first (everything needs them), then the engine's grid
 * and the closed-rule scores (only the comparison needs those). Nothing but same-origin static files is requested.
 */
export function useLabAssets(): Assets {
  const [a, setA] = useState<Assets>({ traces: null, tracesError: false, grid: null, gridStatus: 'loading', closed: null })
  useEffect(() => {
    let live = true
    getJson<Record<string, TraceJson>>('/lab/traces.json')
      .then((traces) => { if (live) setA((s) => ({ ...s, traces, tracesError: traces === null })) })
      .catch(() => { if (live) setA((s) => ({ ...s, tracesError: true })) })
    getJson<ConstructorParameters<typeof Grid>[0]>('/lab/grid.json')
      .then((doc) => { if (live) setA((s) => (doc ? { ...s, grid: new Grid(doc), gridStatus: 'ready' } : { ...s, gridStatus: 'unavailable' })) })
      .catch(() => { if (live) setA((s) => ({ ...s, gridStatus: 'unavailable' })) })
    getJson<ClosedDoc>('/lab/closed.json')
      .then((closed) => { if (live) setA((s) => ({ ...s, closed })) })
      .catch(() => {})
    return () => { live = false }
  }, [])
  return a
}
