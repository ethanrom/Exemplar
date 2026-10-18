'use client'

import { useEffect, useMemo, useState } from 'react'
import { Alert } from '@/components/Disclosure.tsx'
import { Tabs } from '@/components/Tabs.tsx'
import { asTrace } from '@/components/lab/core/rules.ts'
import { Z3Provider } from '@/components/z3/Z3Provider.tsx'
import type { ClipCard } from '@/lib/data/types.ts'
import type { Trace } from '@/lib/dsl/index.ts'
import type { LabProps, Mode, PresetSlug } from '../_lib/types.ts'
import { useLabAssets } from '../_lib/useLabAssets.ts'
import { useLabWorker, type WorkerInit } from '../_lib/useLabWorker.ts'
import { FreePane, type ParityReport } from './FreePane.tsx'
import type { TriState } from './FreeControls.tsx'
import { PresetPane } from './PresetPane.tsx'

// An old ?preset=p2 link opens the first preset.
const PRESET_PARAM: Record<string, Mode> = { p1: 'p1-playground', p2: 'p1-playground', free: 'free' }
const PARAM_OF: Record<Mode, string> = { 'p1-playground': 'p1', free: 'free' }

/**
 * The Lab: two modes sharing one worker. `?preset=p1` or `?preset=free` opens that mode on load (read on
 * the client: the site is a static export) and the address follows the selected mode.
 */
export function LabClient({ props, parity }: { props: LabProps; parity: ParityReport | null }) {
  const assets = useLabAssets()
  const cards = useMemo(() => new Map<string, ClipCard>(props.library.map((c) => [c.alias, c])), [props.library])
  const [mode, setMode] = useState<Mode>('p1-playground')
  const [states, setStates] = useState<TriState[]>(() => props.curated.default.map((t) => (t === 'pos' ? 1 : t === 'neg' ? 2 : 0)) as TriState[])

  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get('preset')
    const m = p ? PRESET_PARAM[p.toLowerCase()] : undefined
    if (m) setMode(m)
  }, [])

  const choose = (m: Mode) => {
    setMode(m)
    const url = new URL(window.location.href)
    url.searchParams.set('preset', PARAM_OF[m])
    window.history.replaceState(null, '', url)
  }

  const init: WorkerInit | null = useMemo(() => {
    if (!assets.traces) return null
    const t = assets.traces
    return {
      curated: props.curated.clips.map((a) => ({ alias: a, trace: asTrace(t[a] as never) })),
      sketches: props.sketches.map((s) => ({ id: s.id, text: s.text })),
      traces: Object.fromEntries(Object.entries(t).map(([a, tr]) => [a, asTrace(tr)] as [string, Trace])),
    }
  }, [assets.traces, props.curated.clips, props.sketches])
  const engine = useLabWorker(init)

  const shared = { props, cards, assets, engine }
  return (
    <Z3Provider>
    {assets.tracesError && (
      <div className="mb-4"><Alert tone="warn" title="The recorded facts could not be loaded">Recorded sessions can still be replayed, but nothing can be recomputed or scored here until the facts load. Reload the page to try again.</Alert></div>
    )}
    <Tabs
      label="Lab mode"
      value={mode}
      onValueChange={(id) => choose(id as Mode)}
      tabs={[
        { id: 'p1-playground', label: 'Recorded session', badge: 'Playground recordings', panel: mode === 'p1-playground' ? <PresetPane slug={'p1-playground' satisfies PresetSlug} {...shared} /> : null },
        { id: 'free', label: 'Free play', panel: mode === 'free' ? <FreePane {...shared} states={states} setStates={setStates} parity={parity} /> : null },
      ]}
    />
    </Z3Provider>
  )
}
