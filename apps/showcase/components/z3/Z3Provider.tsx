'use client'

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode,
} from 'react'
import { browserEnv, z3Capability, type Capability } from '../../lib/synth/z3/capability.ts'
import { Z3Client, type CheckHandle, type Z3State } from '../../lib/synth/z3/client.ts'
import { itemResult, type ItemResult, type Z3Inputs } from '../../lib/synth/z3/model.ts'
import { Z3_SHIPPED, Z3_WORKER_URL } from './assets.ts'

/** The Z3 answers for one Lab request. `key` is the request they were asked for; answers for any other key are never shown. */
export type Z3Run = {
  key: string | null
  status: 'idle' | 'running' | 'done'
  results: Readonly<Record<string, ItemResult>>
  expected: number
  /** Worker time for the whole check, ms. */
  ms: number | null
}

export type Z3Ctl = {
  /** null until the page has mounted (the check reads the browser). */
  capability: Capability | null
  /** The user clicked "Check with real Z3": a worker exists (or is loading, or failed). */
  enabled: boolean
  state: Z3State
  /** The run for the result set on screen now; empty whenever the Lab's request has moved on or Z3 is not ready. */
  run: Z3Run
  /** Whether the Lab has handed over something to check. */
  hasInputs: boolean
  enable: () => void
  disable: () => void
}

const EMPTY_RUN: Z3Run = { key: null, status: 'idle', results: {}, expected: 0, ms: null }
const IDLE_STATE: Z3State = { phase: 'idle', failure: null, info: null }
const idleSnapshot = (): Z3State => IDLE_STATE
const noopSubscribe = (): (() => void) => () => {}

/** Read side: the panel and the badges. */
const StateContext = createContext<Z3Ctl | null>(null)
/** Write side: the panes hand over what they show. Kept apart so a pane does not re-render on every Z3 message. */
const RegisterContext = createContext<((inputs: Z3Inputs | null) => void) | null>(null)

export const useZ3 = (): Z3Ctl | null => useContext(StateContext)

/**
 * Tell Z3 what the Lab currently shows: the selected rule first, then the top candidates, each with the result shown for it.
 * `inputs.requestKey` must change whenever that result changes (the Lab's request id); `inputs.ready` is true once the Lab
 * has finished computing and comparing it. Pass a memoised object. A no-op when this build ships no Z3.
 */
export function useZ3Inputs(inputs: Z3Inputs | null): void {
  const register = useContext(RegisterContext)
  useEffect(() => {
    register?.(inputs)
  }, [register, inputs])
  useEffect(() => () => register?.(null), [register])
}

/**
 * Owns the opt-in Z3: exactly one worker, created on the click, terminated by "Turn off Z3" and when the Lab unmounts.
 * Answers are matched to the Lab request they were asked for; the badge appears only for a completed run of the current one.
 * In a build without Z3 (any release before R4) it renders its children and nothing else.
 */
export function Z3Provider({ children }: { children: ReactNode }) {
  if (!Z3_SHIPPED) return <>{children}</>
  return <ProviderInner>{children}</ProviderInner>
}

function ProviderInner({ children }: { children: ReactNode }) {
  const [capability, setCapability] = useState<Capability | null>(null)
  useEffect(() => {
    setCapability(z3Capability(browserEnv()))
  }, [])

  const clientRef = useRef<Z3Client | null>(null)
  const [client, setClient] = useState<Z3Client | null>(null)
  const state = useSyncExternalStore(client ? client.subscribe : noopSubscribe, client ? client.getState : idleSnapshot, idleSnapshot)

  const inputsRef = useRef<Z3Inputs | null>(null)
  const [meta, setMeta] = useState<{ sig: string; key: string | null }>({ sig: '', key: null })
  const register = useCallback((inputs: Z3Inputs | null) => {
    inputsRef.current = inputs
    const sig = inputs
      ? `${inputs.requestKey}|${inputs.ready ? 1 : 0}|${inputs.items.map((i) => `${i.key}\u0001${i.sketch}`).join('\u0002')}`
      : ''
    setMeta((m) => (m.sig === sig ? m : { sig, key: inputs ? inputs.requestKey : null }))
  }, [])

  const [run, setRun] = useState<Z3Run>(EMPTY_RUN)

  const enable = useCallback(() => {
    const existing = clientRef.current
    if (existing && existing.getState().phase !== 'failed') return
    const c = existing ?? new Z3Client({ workerUrl: Z3_WORKER_URL })
    clientRef.current = c
    setClient(c)
    void c.start().catch(() => {}) // the failure is in the client's state
  }, [])

  const disable = useCallback(() => {
    clientRef.current?.dispose() // terminates the worker: its memory is released
    clientRef.current = null
    setClient(null)
    setRun(EMPTY_RUN)
  }, [])

  // Leaving the Lab ends the worker.
  useEffect(
    () => () => {
      clientRef.current?.dispose()
      clientRef.current = null
    },
    [],
  )

  // One check per Lab request: starts when Z3 is ready and the Lab has finished the request; a newer request cancels it.
  useEffect(() => {
    const inp = inputsRef.current
    if (!client || state.phase !== 'ready' || !inp || !inp.ready || !inp.examples || inp.items.length === 0) return
    if (client.needsRecycle()) {
      void client.recycle().catch(() => {}) // a fresh worker has a fresh heap; the effect runs again when it is ready
      return
    }
    const key = inp.requestKey
    const examples = inp.examples
    const refs = new Map(inp.items.map((i) => [i.key, i.reference] as const))
    const noSketch: Record<string, ItemResult> = {}
    for (const i of inp.items) if (i.sketch === '') noSketch[i.key] = { kind: 'unsupported', reason: 'no rule sketch is available for this candidate' }
    const jobs = inp.items.filter((i) => i.sketch !== '').map((i) => ({ key: i.key, sketch: i.sketch, referenceHoles: i.reference.holes ?? undefined }))
    let live = true
    let handle: CheckHandle | null = null
    const finishedAlready = jobs.length === 0
    setRun({ key, status: finishedAlready ? 'done' : 'running', results: noSketch, expected: inp.items.length, ms: finishedAlready ? 0 : null })
    const timer = window.setTimeout(() => {
      if (finishedAlready) return
      handle = client.check({ examples, jobs }, (k, outcome) => {
        const ref = refs.get(k)
        if (!live || !ref) return
        const res = itemResult(outcome, ref)
        setRun((r) => (r.key === key ? { ...r, results: { ...r.results, [k]: res } } : r))
      })
      handle.done
        .then(({ ms }) => {
          if (live) setRun((r) => (r.key === key ? { ...r, status: 'done', ms } : r))
        })
        .catch(() => {
          // cancelled (a newer request) or failed (the client state says why, and the badges go away with it)
        })
    }, 120)
    return () => {
      live = false
      window.clearTimeout(timer)
      handle?.cancel()
    }
  }, [client, state.phase, meta.sig])

  const shown: Z3Run = state.phase === 'ready' && run.key !== null && run.key === meta.key ? run : EMPTY_RUN
  const ctl = useMemo<Z3Ctl>(
    () => ({ capability, enabled: client !== null, state, run: shown, hasInputs: meta.key !== null, enable, disable }),
    [capability, client, state, shown, meta.key, enable, disable],
  )

  return (
    <RegisterContext.Provider value={register}>
      <StateContext.Provider value={ctl}>{children}</StateContext.Provider>
    </RegisterContext.Provider>
  )
}
