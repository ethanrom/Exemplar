'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Trace } from '../../../lib/dsl/index.ts'
import type { CandidateItem, LabData, PresetRun, SketchOutcome, States, WorkerMessage, WorkerRequest } from '../../../lib/synth/session.ts'
import type { RunEvent as SynthEvent } from '../../../lib/synth/state.ts'

export type Handlers = {
  onEvent?: (e: SynthEvent) => void
  onCandidates?: (items: CandidateItem[]) => void
  onOutcomes?: (o: SketchOutcome[]) => void
  onDone?: (d: { backend: string; solved: number; budget_exceeded: number }) => void
  onError?: (message: string) => void
}

export type WorkerInit = LabData & { traces: Record<string, Trace> }

/**
 * The Lab's Web Worker (SPEC 7.5). Every request gets the next request id; only messages that carry the id of the latest
 * request reach the handlers, so a result for an older toggle can never overwrite a newer one. With cross-origin isolation
 * the id is also written to a shared flag, so the worker abandons the old request at its next check-point even mid-solve.
 */
export function useLabWorker(init: WorkerInit | null) {
  const worker = useRef<Worker | null>(null)
  const latest = useRef(0)
  const handlers = useRef<Handlers>({})
  const flag = useRef<Int32Array | null>(null)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)

  useEffect(() => {
    if (init === null) return
    let w: Worker
    try {
      w = new Worker(new URL('../_worker/lab.worker.ts', import.meta.url), { type: 'module' })
    } catch (e) {
      setFailed(e instanceof Error ? e.message : 'the worker could not start')
      return
    }
    worker.current = w
    const shared = typeof SharedArrayBuffer !== 'undefined' && typeof crossOriginIsolated !== 'undefined' && crossOriginIsolated
    flag.current = shared ? new Int32Array(new SharedArrayBuffer(4)) : null
    w.onmessage = (ev: MessageEvent<WorkerMessage>) => {
      const m = ev.data
      if (m.request_id !== latest.current) return // stale: a newer request exists
      const h = handlers.current
      if (m.type === 'event') h.onEvent?.(m.event)
      else if (m.type === 'candidates') h.onCandidates?.(m.items)
      else if (m.type === 'outcomes') h.onOutcomes?.(m.outcomes)
      else if (m.type === 'done') h.onDone?.({ backend: m.backend_status.backend, solved: m.backend_status.solved, budget_exceeded: m.backend_status.budget_exceeded })
      else if (m.type === 'error') h.onError?.(m.message)
    }
    w.onerror = (e) => setFailed(e.message || 'the worker failed')
    const msg: WorkerRequest = { type: 'init', data: init, cancelFlag: flag.current ?? undefined }
    w.postMessage(msg)
    setReady(true)
    return () => {
      w.terminate()
      worker.current = null
      setReady(false)
    }
  }, [init])

  const send = useCallback((req: { type: 'free'; states: States } | { type: 'preset'; run: PresetRun }, h: Handlers): number => {
    const w = worker.current
    const id = latest.current + 1
    if (w === null) {
      h.onError?.('the worker is not ready')
      return id
    }
    const prev = latest.current
    latest.current = id
    handlers.current = h
    if (flag.current) Atomics.store(flag.current, 0, id)
    if (prev > 0) w.postMessage({ type: 'cancel', request_id: prev } satisfies WorkerRequest)
    w.postMessage({ ...req, request_id: id } as WorkerRequest)
    return id
  }, [])

  /** True while `id` is the request the page accepts messages for. */
  const isCurrent = useCallback((id: number) => latest.current === id, [])
  /** Drop the running request: nothing it posts will reach the page. */
  const cancel = useCallback(() => {
    const prev = latest.current
    latest.current = prev + 1
    handlers.current = {}
    if (flag.current) Atomics.store(flag.current, 0, prev + 1)
    worker.current?.postMessage({ type: 'cancel', request_id: prev } satisfies WorkerRequest)
  }, [])

  return { ready, failed, send, isCurrent, cancel }
}
