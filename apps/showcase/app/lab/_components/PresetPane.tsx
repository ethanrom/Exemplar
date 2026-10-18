'use client'

import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Button } from '@/components/Button.tsx'
import { Section } from '@/components/SectionHeader.tsx'
import { LiveRegion } from '@/components/lab/Announce.tsx'
import type { CandidateView } from '@/components/lab/CandidateList.tsx'
import { MatchBadge, Z3AgreesSlot } from '@/components/lab/MatchBadge.tsx'
import { Segmented } from '@/components/lab/Segmented.tsx'
import { asTrace } from '@/components/lab/core/rules.ts'
import { labInputs, recordedPlacement } from '@/components/z3/inputs.ts'
import { useZ3Inputs } from '@/components/z3/Z3Provider.tsx'
import type { ClipCard, RunEvent } from '@/lib/data/types.ts'
import type { CandidateItem } from '@/lib/synth/session.ts'
import { comparePreset, recordedCandidateTexts, type PresetCheck } from '../_lib/compare.ts'
import { describePreset } from '../_lib/describe.ts'
import type { LabProps, LabRule, PresetSlug } from '../_lib/types.ts'
import type { Assets } from '../_lib/useLabAssets.ts'
import type { useLabWorker } from '../_lib/useLabWorker.ts'
import { useEventBuffer } from '../_lib/useEventBuffer.ts'
import { defaultSelection, itemViews, recordedViews, rulesByText, stamp } from '../_lib/views.ts'
import { ExamplesPreset } from './ExamplesPreset.tsx'
import { ResultsColumn } from './ResultsColumn.tsx'

export type PaneProps = {
  props: LabProps
  cards: ReadonlyMap<string, ClipCard>
  assets: Assets
  engine: ReturnType<typeof useLabWorker>
}

type Recompute = {
  /** Which recompute this is (1, 2, ...): the Z3 check is keyed to it. */
  seq: number
  status: 'idle' | 'running' | 'done' | 'error'
  items: CandidateItem[] | null
  check: PresetCheck | null
  ms: number | null
  error: string | null
}
const IDLE: Recompute = { seq: 0, status: 'idle', items: null, check: null, ms: null, error: null }

/** Preset P1: the recorded session, replayable, and the same loop recomputed in the browser and compared with it. */
export function PresetPane({ slug, props, cards, assets, engine }: PaneProps & { slug: PresetSlug }) {
  const run = props.runs[slug]
  const recorded = useMemo(() => recordedViews(run, props.rules), [run, props.rules])
  const byText = useMemo(() => rulesByText(run, props.rules), [run, props.rules])
  const [timelineView, setTimelineView] = useState<'recorded' | 'recomputed'>('recorded')
  const [shown, setShown] = useState(run.events.length)
  const [playing, setPlaying] = useState<1 | 4 | null>(null)
  const [rc, setRc] = useState<Recompute>(IDLE)
  const rcSeq = useRef(0)
  const [selectedKey, setSelectedKey] = useState<string | null>(() => defaultSelection(recorded))
  const [announce, setAnnounce] = useState('')
  const buffer = useEventBuffer<RunEvent>()

  // Replay: the recorded events at their recorded relative times, divided by the speed.
  useEffect(() => {
    if (playing === null) return
    let stopped = false
    let timer = 0
    const step = (i: number) => {
      if (stopped) return
      if (i >= run.events.length) {
        setPlaying(null)
        setAnnounce('Replay finished.')
        return
      }
      const prev = i === 0 ? 0 : (run.events[i - 1] as RunEvent).t_ms
      timer = window.setTimeout(() => {
        if (stopped) return
        setShown(i + 1)
        step(i + 1)
      }, Math.max(0, ((run.events[i] as RunEvent).t_ms - prev) / playing))
    }
    step(0)
    return () => { stopped = true; window.clearTimeout(timer) }
  }, [playing, run.events])

  const startReplay = (speed: 1 | 4) => {
    setTimelineView('recorded')
    setShown(0)
    setPlaying(speed)
    setAnnounce(`Replaying the recorded session at ${speed} times speed.`)
  }
  const stepOnce = () => {
    setTimelineView('recorded')
    setPlaying(null)
    setShown((s) => (s >= run.events.length ? 1 : s + 1))
  }
  const showAll = () => { setPlaying(null); setShown(run.events.length); setTimelineView('recorded') }

  // Recompute in the browser: the worker replays the recorded proposals through the loop; the page compares afterwards.
  const recompute = useCallback((switchView = true) => {
    if (!assets.traces) return
    const traces = assets.traces
    const t0 = performance.now()
    const collected: RunEvent[] = []
    let items: CandidateItem[] = []
    let seq = 0
    setPlaying(null)
    buffer.reset()
    setRc({ ...IDLE, seq: ++rcSeq.current, status: 'running' })
    if (switchView) setTimelineView('recomputed')
    if (switchView) setAnnounce('Recomputing the run in your browser.')
    const examples = run.examples.map((e) => ({ alias: e.alias, positive: e.label === 'pos', weight: e.weight }))
    const id = engine.send({ type: 'preset', run: { examples, rounds: run.proposals_by_round } }, {
      onEvent: (e) => { const ev = stamp(e, ++seq, t0); collected.push(ev); buffer.push(ev) },
      onCandidates: (it) => { items = it },
      onError: (message) => setRc((s) => ({ ...s, status: 'error', error: message })),
      onDone: () => {
        const ms = Math.round(performance.now() - t0)
        buffer.flush()
        startTransition(() => setRc((s) => ({ ...s, status: 'done', items, ms })))
        const trs = Object.fromEntries(run.examples.map((e) => [e.alias, asTrace(traces[e.alias] as never)]))
        void comparePreset(
          run, collected as never, items.map((i) => i.dsl_text), recordedCandidateTexts(props.rules, run), trs, examples, () => engine.isCurrent(id),
        ).then((check) => {
          if (check === null) return
          startTransition(() => setRc((s) => ({ ...s, check })))
          setSelectedKey((k) => (items.some((i) => i.dsl_text === k) ? k : (items[0]?.dsl_text ?? k)))
          setAnnounce(`Recomputed in ${ms} milliseconds. ${describePreset(check, false).headline}.`)
        })
      },
    })
  }, [assets.traces, engine, run, props.rules, buffer.push, buffer.reset, buffer.flush])

  // Run it once when the pane opens, so the engine check is already there; the recorded session stays on screen.
  const auto = useRef(false)
  useEffect(() => {
    if (auto.current || !assets.traces || !engine.ready) return
    auto.current = true
    recompute(false)
  }, [assets.traces, engine.ready, recompute])

  // Candidates follow the timeline view: the recorded list, or the recomputed one once it exists.
  const recomputedViews = useMemo(() => (rc.items ? itemViews(rc.items, byText) : null), [rc.items, byText])
  const views: CandidateView[] = timelineView === 'recomputed' && recomputedViews ? recomputedViews : recorded
  const selectedKeyShown = views.some((v) => v.key === selectedKey) ? selectedKey : defaultSelection(views)

  const events: RunEvent[] = timelineView === 'recomputed' ? buffer.events : run.events.slice(0, shown)
  const checkView = describePreset(rc.check, rc.status === 'running')
  const ready = assets.traces !== null && engine.ready
  const selectedRecorded = byText.get((views.find((v) => v.key === selectedKeyShown) ?? { dsl_text: '' }).dsl_text)
  const deployedRecordedMessage = selectedRecorded?.calibration?.message ?? null

  // Z3 (opt-in) re-solves the selected rule and the top candidates of whichever list is on screen.
  const z3Examples = useMemo(
    () => (assets.traces ? run.examples.map((e) => ({ alias: e.alias, positive: e.label === 'pos', weight: e.weight, trace: asTrace(assets.traces![e.alias] as never) })) : null),
    [assets.traces, run.examples],
  )
  const recomputedShown = timelineView === 'recomputed' && recomputedViews !== null
  const z3 = useMemo(() => labInputs({
    requestKey: recomputedShown ? `${slug}:recomputed:${rc.seq}` : `${slug}:recorded`,
    ready: recomputedShown ? rc.status === 'done' && rc.check !== null : true,
    examples: z3Examples, views, selectedKey: selectedKeyShown, source: recomputedShown ? 'browser' : 'engine',
    extra: (v) => ({ placement: recordedPlacement(run.events, v.sketch_text) }),
  }), [recomputedShown, slug, rc.seq, rc.status, rc.check, z3Examples, views, selectedKeyShown, run.events])
  useZ3Inputs(z3)

  return (
    <>
      <Section id="topbar" title="Mode and checks" description="The solver and what its result was compared with.">
        <div className="flex flex-wrap items-start gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="info" icon="sliders">Exhaustive solver, TypeScript, in a Web Worker</Badge>
          </div>
          <MatchBadge kind={checkView.kind} headline={checkView.headline} details={checkView.details} className="min-w-0 flex-1 basis-80" />
        </div>
        <Z3AgreesSlot className="mt-3" />
      </Section>

      <div className="grid gap-x-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div>
          <Section id="examples" title="Examples" description="The real examples this recorded run was taught from.">
            <ExamplesPreset run={run} cards={cards} credits={props.credits} />
          </Section>
        </div>

        <ResultsColumn
          props={props}
          cards={cards}
          assets={assets}
          mode={slug}
          experimental={false}
          contradiction={false}
          recordedRules={byText}
          recordedMessage={deployedRecordedMessage}
          timeline={{
            events,
            running: rc.status === 'running' && timelineView === 'recomputed',
            label: timelineView === 'recomputed' ? 'Agent timeline, recomputed in your browser' : 'Agent timeline, recorded session',
            controls: (
              <div className="mb-3 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" icon="play" onClick={() => startReplay(1)} disabled={playing === 1}>Replay 1×</Button>
                  <Button size="sm" icon="play" onClick={() => startReplay(4)} disabled={playing === 4}>Replay 4×</Button>
                  <Button size="sm" icon="chevron-right" onClick={stepOnce}>Step</Button>
                  <Button size="sm" variant="ghost" onClick={showAll} disabled={playing === null && shown >= run.events.length && timelineView === 'recorded'}>Show all</Button>
                  <span className="text-xs text-ex-ink3" aria-hidden="true">{timelineView === 'recorded' ? `${shown} of ${run.events.length} recorded events` : `${buffer.events.length} events recomputed`}</span>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="primary" size="sm" icon="refresh" onClick={() => recompute(true)} disabled={!ready || rc.status === 'running'}>
                    {rc.status === 'running' ? 'Recomputing…' : rc.status === 'done' ? 'Recompute again' : 'Recompute in your browser'}
                  </Button>
                  {!ready && !engine.failed && <span className="text-xs text-ex-ink3">Loading the recorded facts…</span>}
                  {engine.failed && <span className="text-xs text-ex-warn">The solver could not start in this browser.</span>}
                  {rc.status === 'error' && <span className="text-xs text-ex-neg">{rc.error}</span>}
                  {rc.ms !== null && <span className="text-xs text-ex-ink3">Re-solved in <span className="font-mono tabular-nums">{rc.ms} ms</span> in your browser.</span>}
                </div>
                {rc.status === 'done' && (
                  <Segmented
                    label="Which timeline to show"
                    size="sm"
                    value={timelineView}
                    onChange={(v) => { setPlaying(null); setTimelineView(v) }}
                    options={[{ id: 'recorded', label: 'Recorded session' }, { id: 'recomputed', label: 'Recomputed here' }]}
                  />
                )}
                <p className="text-xs text-ex-ink2">
                  Recomputing replays the recorded sketches through the same loop.
                </p>
              </div>
            ),
          }}
          candidates={{
            views,
            selectedKey: selectedKeyShown,
            onSelect: setSelectedKey,
            busy: rc.status === 'running' && timelineView === 'recomputed',
            empty: 'This run produced no candidate rules.',
          }}
        />
      </div>
      <LiveRegion text={announce} delay={100} />
    </>
  )
}
