'use client'

import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Section } from '@/components/SectionHeader.tsx'
import { LiveRegion } from '@/components/lab/Announce.tsx'
import type { CandidateView } from '@/components/lab/CandidateList.tsx'
import { MatchBadge, Z3AgreesSlot } from '@/components/lab/MatchBadge.tsx'
import { Segmented } from '@/components/lab/Segmented.tsx'
import type { RunEvent } from '@/lib/data/types.ts'
import { examplesOf, isValid, slotOf } from '@/lib/synth/session.ts'
import type { Trace } from '@/lib/dsl/index.ts'
import { labInputs } from '@/components/z3/inputs.ts'
import { useZ3Inputs } from '@/components/z3/Z3Provider.tsx'
import type { CandidateItem, LabData, SketchOutcome, States } from '@/lib/synth/session.ts'
import { compareFree, type FreeCheck } from '../_lib/compare.ts'
import { describeFree } from '../_lib/describe.ts'
import { asTrace } from '@/components/lab/core/rules.ts'
import { useEventBuffer } from '../_lib/useEventBuffer.ts'
import { engineViews, itemViews, stamp } from '../_lib/views.ts'
import type { PaneProps } from './PresetPane.tsx'
import { FreeControls, type TriState } from './FreeControls.tsx'
import { ResultsColumn } from './ResultsColumn.tsx'

export type ParityReport = {
  slots: number; entries: number; identical: number; tie_verified: number; engine_supplied: number; mismatch: number
  top6_same: number; top6_explained: number; top6_mismatch: number
}

type Run = {
  id: number
  states: States
  status: 'running' | 'done' | 'error'
  items: CandidateItem[] | null
  outcomes: SketchOutcome[] | null
  ms: number | null
  error: string | null
}

const n = (x: number) => x.toLocaleString('en-US')

/** Free play: toggle the curated clips; the exhaustive solver re-runs in the worker and the result is checked against the grid. */
export function FreePane({
  props, cards, assets, engine, states, setStates, parity,
}: PaneProps & { states: TriState[]; setStates: (s: TriState[]) => void; parity: ParityReport | null }) {
  const clips = props.curated.clips
  const recorded = props.curated.default
  const recordedStates = useMemo(() => recorded.map((t) => (t === 'pos' ? 1 : t === 'neg' ? 2 : 0)) as TriState[], [recorded])
  const atRecorded = states.every((s, i) => s === recordedStates[i])
  const valid = isValid(states)

  const [run, setRun] = useState<Run | null>(null)
  const [check, setCheck] = useState<{ id: number; value: FreeCheck } | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [engineList, setEngineList] = useState<'mine' | 'engine'>('mine')
  const [announce, setAnnounce] = useState('')
  const buffer = useEventBuffer<RunEvent>()

  const labData: LabData | null = useMemo(
    () => (assets.traces ? { curated: clips.map((a) => ({ alias: a, trace: asTrace(assets.traces![a] as never) })), sketches: props.sketches.map((s) => ({ id: s.id, text: s.text })) } : null),
    [assets.traces, clips, props.sketches],
  )

  // Every change (debounced 150 ms) is a new request; the worker abandons the old one and the page drops its messages.
  useEffect(() => {
    if (!engine.ready) return
    if (!valid) {
      engine.cancel()
      setRun(null)
      setCheck(null)
      return
    }
    const timer = window.setTimeout(() => {
      const t0 = performance.now()
      let seq = 0
      const snapshot = [...states] as States
      let id = 0
      id = engine.send({ type: 'free', states: snapshot }, {
        onEvent: (e) => buffer.push(stamp(e, ++seq, t0)),
        onCandidates: (items) => startTransition(() => setRun((r) => (r && r.id === id ? { ...r, items } : r))),
        onOutcomes: (outcomes) => startTransition(() => setRun((r) => (r && r.id === id ? { ...r, outcomes } : r))),
        onError: (message) => setRun((r) => (r && r.id === id ? { ...r, status: 'error', error: message } : r)),
        onDone: () => {
          const ms = Math.round(performance.now() - t0)
          buffer.flush()
          startTransition(() => setRun((r) => (r && r.id === id ? { ...r, status: 'done', ms } : r)))
        },
      })
      buffer.reset()
      setRun((prev) => ({ id, states: snapshot, status: 'running', items: prev?.items ?? null, outcomes: null, ms: null, error: null }))
      setCheck(null)
      setAnnounce('Re-solving in your browser.')
    }, 150)
    return () => window.clearTimeout(timer)
  }, [states, valid, engine.ready]) // eslint-disable-line react-hooks/exhaustive-deps

  // After a solve has finished for the current request, and only then, the page reads the grid.
  const finished = run && run.status === 'done' && run.items && run.outcomes ? run : null
  useEffect(() => {
    if (!finished || !assets.grid || !labData) return
    let live = true
    const id = finished.id
    void compareFree(assets.grid, labData, finished.states, finished.outcomes as SketchOutcome[], finished.items as CandidateItem[], () => live && engine.isCurrent(id)).then((value) => {
      if (live && value) {
        startTransition(() => setCheck({ id, value }))
        const view = describeFree(value, { running: false, invalid: false, gridStatus: 'ready' })
        setAnnounce(`${view.headline}. ${(finished.items as CandidateItem[]).length} candidates in ${finished.ms} milliseconds.`)
      }
    })
    return () => { live = false }
  }, [finished?.id, assets.grid, labData]) // eslint-disable-line react-hooks/exhaustive-deps

  const thisCheck = check && run && check.id === run.id ? check.value : null
  const running = run?.status === 'running'
  const view = describeFree(thisCheck, { running: !!running, invalid: !valid, gridStatus: assets.gridStatus })

  const mineViews = useMemo(() => (run?.items ? itemViews(run.items, undefined, thisCheck?.engineList ?? null) : []), [run?.items, thisCheck])
  const showEngine = engineList === 'engine' && thisCheck?.engineList
  const views: CandidateView[] = showEngine ? engineViews(thisCheck!.engineList!) : mineViews
  const selKey = views.some((v) => v.key === selectedKey) ? selectedKey : (views[0]?.key ?? null)

  // Z3 (opt-in) re-solves the selected rule and the top candidates of the list on screen, once the engine check is done.
  // For the engine's own list the shown results are the engine's, which Z3 can also confirm where the browser's solver could not.
  const z3 = useMemo(() => {
    if (!finished || !labData) return null
    const examples = examplesOf(labData, finished.states).map((e) => ({ alias: e.clip_id, positive: e.positive, weight: e.weight, trace: e.trace as Trace }))
    const ready = thisCheck !== null || assets.gridStatus === 'unavailable'
    const engineItems = showEngine ? thisCheck.engineList : null
    if (engineItems) {
      const text = new Map(props.sketches.map((s) => [s.id, s.text] as const))
      const slot = slotOf(finished.states)
      const byKey = new Map(engineItems.map((e) => [e.dsl_text, e] as const))
      const withSketch = views.map((v) => ({ ...v, sketch_text: text.get(byKey.get(v.key)?.sketch_id ?? -1) ?? '' }))
      return labInputs({
        requestKey: `free:${finished.id}:engine`, ready, examples, views: withSketch, selectedKey: selKey, source: 'engine',
        extra: (v) => ({ placement: assets.grid?.entry(byKey.get(v.key)?.sketch_id ?? -1, slot)?.placement ?? null }),
      })
    }
    const byDsl = new Map((finished.items ?? []).map((it) => [it.dsl_text, it] as const))
    return labInputs({
      requestKey: `free:${finished.id}`, ready, examples, views: mineViews, selectedKey: selKey, source: 'browser',
      extra: (v) => {
        const it = byDsl.get(v.key)
        const o = it ? finished.outcomes?.find((x) => x.sketch_id === it.sketch_id)?.result : null
        return o ? { placement: o.placement, optimalSets: o.optimalSets } : {}
      },
    })
  }, [finished, labData, thisCheck, assets.gridStatus, assets.grid, showEngine, views, mineViews, selKey, props.sketches])
  useZ3Inputs(z3)

  // The user's labels contradict the recorded package labels on a clip used here (SPEC 7.3).
  const contradiction = clips.some((alias, i) => {
    const st = states[i]
    if (!st) return false
    const rec = cards.get(alias)?.recorded_labels.find((l) => l.concept === 'package' && l.provenance !== 'random')
    return !!rec && rec.label !== (st === 1 ? 'pos' : 'neg')
  })

  const onChange = useCallback((i: number, v: TriState) => {
    const next = [...states]
    next[i] = v
    setStates(next)
  }, [states, setStates])

  return (
    <>
      <Section id="topbar" title="Mode and checks" description="The solver and what its result was compared with.">
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info" icon="sliders">Exhaustive solver, TypeScript, in a Web Worker</Badge>
          </div>
          <MatchBadge kind={view.kind} headline={view.headline} details={view.details} className="min-w-0 flex-1 basis-80" />
        </div>
        <Z3AgreesSlot className="mt-3" />
        {parity && (
          <p className="mt-2 text-xs text-ex-ink3" data-src="data/grid/parity-report.json">
            Checked offline over all <span className="tabular-nums">{n(parity.slots)}</span> valid label combinations: of <span className="tabular-nums">{n(parity.entries)}</span> solves, <span className="tabular-nums">{n(parity.identical)}</span> identical, <span className="tabular-nums">{n(parity.tie_verified)}</span> equally optimal (verified), <span className="tabular-nums">{n(parity.engine_supplied)}</span> engine results, <span className="tabular-nums">{parity.mismatch}</span> mismatches.
          </p>
        )}
      </Section>

      <div className="grid gap-x-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div>
          <Section id="examples" title="Examples" description="The curated clips. Change a label and the rule search re-runs.">
            <FreeControls clips={clips} states={states} onChange={onChange} onReset={() => setStates(recordedStates)} cards={cards} recorded={recorded} atRecorded={atRecorded} />
          </Section>
        </div>

        <ResultsColumn
          props={props}
          cards={cards}
          assets={assets}
          mode="free"
          experimental
          contradiction={contradiction}
          recordedRules={new Map()}
          recordedMessage={null}
          timeline={{
            events: buffer.events,
            running: !!running,
            label: 'Agent timeline, live in your browser',
            controls: !valid ? (
              <p role="status" className="mb-3 rounded-lg border border-ex-warn-line bg-ex-warn-soft px-3 py-2 text-sm text-ex-ink">Pick at least one yes and one no to search for a rule.</p>
            ) : (
              <p className="mb-3 text-xs text-ex-ink2">
                {run?.ms != null ? <>Re-solved in <span className="font-mono tabular-nums">{run.ms} ms</span> in your browser. </> : null}
                {run?.status === 'error' && <span className="ml-1 text-ex-neg">{run.error}</span>}
                {engine.failed && <span className="ml-1 text-ex-warn">The solver could not start in this browser.</span>}
              </p>
            ),
          }}
          candidates={{
            views,
            selectedKey: selKey,
            onSelect: setSelectedKey,
            busy: !!running,
            empty: valid ? (run ? 'No rule in the sketch bank fits these examples.' : 'Searching…') : 'Pick at least one yes and one no.',
            above: thisCheck?.engineList && thisCheck.top6 === 'explained' ? (
              <div className="space-y-2">
                <p className="text-sm text-ex-ink2">Candidate list differs because of tied alternatives. Both lists are equally good by score and margin.</p>
                <Segmented label="Which candidate list" size="sm" value={engineList} onChange={setEngineList} options={[{ id: 'mine', label: 'Computed here' }, { id: 'engine', label: 'Engine’s list' }]} />
              </div>
            ) : null,
          }}
        />
      </div>
      <LiveRegion text={announce} delay={250} />
    </>
  )
}
