'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { useApi, useStoredState } from './hooks'
import type { Concept, RingAuthStatus } from './types'

interface AppCtx {
  engineOk: boolean | null // null = still checking
  engineVersion: string | null
  isMock: boolean
  auth: RingAuthStatus | null
  setAuth: (a: RingAuthStatus) => void
  refreshAuth: () => Promise<void>
  concepts: Concept[]
  conceptsLoading: boolean
  refreshConcepts: () => Promise<void>
  conceptId: string | null
  setConceptId: (id: string) => void
  concept: Concept | null
}

const Ctx = createContext<AppCtx | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const health = useApi<{ ok: boolean; version: string }>('/health', { interval: 15_000 })
  const auth = useApi<RingAuthStatus>('/ring/auth', { interval: 20_000 })
  const concepts = useApi<Concept[]>('/concepts')
  const [stored, setStored] = useStoredState<string | null>('exemplar.concept', null)

  const list = concepts.data ?? []
  const conceptId = useMemo(() => {
    if (stored && list.some((c) => c.id === stored)) return stored
    return list[0]?.id ?? null
  }, [stored, list])

  // Keep the stored id valid once the list arrives.
  useEffect(() => {
    if (conceptId && stored !== conceptId) setStored(conceptId)
  }, [conceptId, stored, setStored])

  const setAuth = useCallback((a: RingAuthStatus) => auth.setData(a), [auth])
  const refreshAuth = auth.reload
  const refreshConcepts = concepts.reload

  const value: AppCtx = {
    engineOk: health.error ? false : health.data ? health.data.ok : null,
    engineVersion: health.data?.version ?? null,
    isMock: /mock/i.test(health.data?.version ?? ''),
    auth: auth.data,
    setAuth,
    refreshAuth,
    concepts: list,
    conceptsLoading: concepts.loading,
    refreshConcepts,
    conceptId,
    setConceptId: setStored,
    concept: list.find((c) => c.id === conceptId) ?? null,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useApp(): AppCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp must be used inside <AppProvider>')
  return v
}
