'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../_lib/app'
import { ApiError, errorMessage, get, post, put } from '../_lib/api'
import { useApi, useEventStream } from '../_lib/hooks'
import type { Concept, EventSummary, LabelSummary, Question, RuleSummary, Run, RunEvent, RunEventType } from '../_lib/types'
import { AgentTimeline } from '../_components/AgentTimeline'
import { ConceptSelect } from '../_components/ConceptSelect'
import { EventDialog } from '../_components/EventDialog'
import { EventThumb, LabelControl, LabelIndicator } from '../_components/EventBits'
import { Icon } from '../_components/Icon'
import { QuestionCard } from '../_components/QuestionCard'
import { CandidateRow, HeroRuleCard } from '../_components/RuleCard'
import { Alert, Badge, PageHeader, SectionHeader, Segmented, Spinner, cx } from '../_components/ui'

const RUN_TYPES: RunEventType[] = [
  'round_started', 'sketch_proposed', 'typecheck_failed', 'solve_started', 'solve_result',
  'differential_check', 'counterexample', 'candidates', 'question_ready', 'done', 'error',
]

// ---------------------------------------------------------------------------------------------
function NewConcept({ onCreated }: { onCreated: (c: Concept) => void }) {
  const [name, setName] = useState('')
  const [hint, setHint] = useState('')
  const [alpha, setAlpha] = useState('0.1')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const c = await post<Concept>('/concepts', { name: name.trim(), nl_hint: hint.trim() || null, alpha: Number(alpha) })
      setName(''); setHint('')
      onCreated(c)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded text-sm font-medium text-ex-accent-ink hover:text-ex-ink [&::-webkit-details-marker]:hidden">
        <Icon name="plus" className="h-3.5 w-3.5" /> Teach a new concept
      </summary>
      <form onSubmit={submit} className="mt-4 grid gap-4 rounded-lg border border-ex-line bg-ex-bg p-4">
        <div>
          <label htmlFor="nc-name" className="field-label">Name</label>
          <input id="nc-name" className="field" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Someone at the door who doesn’t ring" />
        </div>
        <div>
          <label htmlFor="nc-hint" className="field-label">Hint in your own words (optional)</label>
          <textarea id="nc-hint" className="field min-h-[72px]" value={hint} onChange={(e) => setHint(e.target.value)} aria-describedby="nc-hint-help" />
          <p id="nc-hint-help" className="mt-1.5 text-xs text-ex-ink3">The model reads this when it drafts rule sketches. The rules you get back are built by the solver, not by the hint.</p>
        </div>
        <div>
          <label htmlFor="nc-alpha" className="field-label">Acceptable false-alarm rate α</label>
          <input id="nc-alpha" className="field w-28" type="number" min={0.01} max={0.5} step={0.01} value={alpha} onChange={(e) => setAlpha(e.target.value)} required />
        </div>
        {error && <Alert tone="neg" title="Could not create the concept">{error}</Alert>}
        <div><button className="btn" type="submit" disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create concept'}</button></div>
      </form>
    </details>
  )
}

// ---------------------------------------------------------------------------------------------
function ExampleRow({
  ev, concept, onOpen, onLabel,
}: { ev: EventSummary; concept: Concept | null; onOpen: () => void; onLabel: (v: 'pos' | 'neg' | null) => void }) {
  const title = ev.summary ?? ev.clip_id
  const label = ev.label?.value ?? null
  return (
    <li className="flex items-center gap-3 py-2.5">
      <button
        type="button"
        className="relative shrink-0 overflow-hidden rounded-md"
        onClick={onOpen}
        aria-label={`View details: ${title}`}
      >
        <EventThumb event={ev} compact className="h-[50px] w-[88px]" />
      </button>
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-sm leading-5 text-ex-ink">{title}</p>
        <div className="mt-0.5"><LabelIndicator label={ev.label} /></div>
      </div>
      {concept && <LabelControl conceptName={concept.name} clipSummary={title} value={label} onSet={onLabel} />}
    </li>
  )
}

// ---------------------------------------------------------------------------------------------
export default function TeachScreen() {
  const { concept, conceptId, refreshConcepts, setConceptId } = useApp()
  const [events, setEvents] = useState<EventSummary[]>([])
  const [eventsErr, setEventsErr] = useState<string | null>(null)
  const [pickerTab, setPickerTab] = useState<'chosen' | 'all'>('chosen')
  const [openId, setOpenId] = useState<string | null>(null)

  const [run, setRun] = useState<Run | null>(null)
  const [timeline, setTimeline] = useState<RunEvent[]>([])
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [streamPath, setStreamPath] = useState<string | null>(null)
  const tlRef = useRef<HTMLDivElement>(null)
  const tlHeadRef = useRef<HTMLHeadingElement>(null)
  const answerRef = useRef<HTMLDivElement>(null)

  const rules = useApi<RuleSummary[]>(conceptId ? `/concepts/${conceptId}/rules` : null)
  const question = useApi<Question>(conceptId ? `/concepts/${conceptId}/question` : null)
  const [skipped, setSkipped] = useState<string[]>([])
  const [answering, setAnswering] = useState(false)
  const [answered, setAnswered] = useState<string | null>(null)
  const [notice, setNotice] = useState('')

  const loadEvents = useCallback(async () => {
    if (!conceptId) return
    try {
      const res = await get<{ items: EventSummary[] }>(`/events?concept_id=${encodeURIComponent(conceptId)}&limit=500`)
      setEvents(res.items)
      setEventsErr(null)
    } catch (e) {
      setEventsErr(errorMessage(e))
    }
  }, [conceptId])

  useEffect(() => {
    setTimeline([]); setRun(null); setRunning(false); setStreamPath(null); setRunError(null); setSkipped([]); setAnswered(null)
    loadEvents()
  }, [conceptId, loadEvents])

  const byClip = useMemo(() => new Map(events.map((e) => [e.clip_id, e])), [events])
  const chosen = events.filter((e) => e.label && e.label.provenance !== 'random')
  const chosenPos = chosen.filter((e) => e.label?.value === 'pos')
  const chosenNeg = chosen.filter((e) => e.label?.value === 'neg')
  const positives = chosenPos.length
  const negatives = chosenNeg.length
  const allClips = events.filter((e) => e.trace_status === 'ok')

  async function setLabel(ev: EventSummary, value: 'pos' | 'neg' | null) {
    if (!concept) return
    const provenance = ev.label?.provenance ?? 'example'
    const prev = ev.label ?? null
    const next: LabelSummary | null = value ? { concept_id: concept.id, clip_id: ev.clip_id, value, provenance, weight: 3 } : null
    setEvents((list) => list.map((e) => (e.id === ev.id ? { ...e, label: next } : e)))
    try {
      await put(`/concepts/${concept.id}/labels`, { clip_id: ev.clip_id, value, provenance })
      refreshConcepts()
    } catch (e) {
      setEvents((list) => list.map((x) => (x.id === ev.id ? { ...x, label: prev } : x)))
      setEventsErr(errorMessage(e))
    }
  }

  // keep the newest step in view while the run is going
  useEffect(() => {
    const el = tlRef.current
    if (el && running) el.scrollTop = el.scrollHeight
  }, [timeline.length, running])

  // ---- run
  const status = useEventStream<RunEvent>(streamPath, RUN_TYPES, (type, data) => {
    setTimeline((prev) => (prev.some((e) => e.seq === data.seq) ? prev : [...prev, data].sort((a, b) => a.seq - b.seq)))
    if (type === 'candidates') rules.reload()
    if (type === 'question_ready') question.reload()
    if (type === 'done' || type === 'error') {
      setRunning(false)
      if (type === 'error') setRunError(data.error || data.message || 'The run failed.')
      rules.reload(); question.reload(); refreshConcepts(); loadEvents()
      return false
    }
  })

  async function startTeach() {
    if (!conceptId) return
    setRunError(null); setTimeline([]); setAnswered(null); setSkipped([])
    try {
      const r = await post<Run>(`/concepts/${conceptId}/teach`)
      setRun(r)
      setRunning(true)
      setStreamPath(`/runs/${r.id}/stream`)
      requestAnimationFrame(() => tlHeadRef.current?.focus()) // the Teach button disables itself while the run is going
    } catch (e) {
      setRunError(e instanceof ApiError && e.status === 409 ? 'A run is already in progress for this concept.' : errorMessage(e))
    }
  }

  async function answer(v: 'pos' | 'neg') {
    const q = question.data
    if (!q || !conceptId) return
    setAnswering(true)
    try {
      await put(`/concepts/${conceptId}/labels`, { clip_id: q.clip_id, value: v, provenance: 'active' })
      setAnswered(v === 'pos' ? 'Counted as a positive example.' : 'Counted as a negative example.')
      setNotice(`Answer saved: ${v === 'pos' ? 'yes' : 'no'}.`)
      await Promise.all([question.reload(), refreshConcepts(), loadEvents()])
      requestAnimationFrame(() => answerRef.current?.focus())
    } catch (e) {
      setRunError(errorMessage(e))
    } finally {
      setAnswering(false)
    }
  }

  const q = question.data && !skipped.includes(question.data.clip_id) ? question.data : null
  const ranked = rules.data ?? []
  const haveRules = ranked.length > 0
  const canTeach = !!conceptId && positives > 0 && !running

  const teachButton = (
    <button type="button" className={cx(haveRules ? 'btn' : 'btn-primary')} onClick={startTeach} disabled={!canTeach}>
      <Icon name="bolt" /> {running ? 'Teaching…' : haveRules ? 'Teach again' : 'Teach'}
    </button>
  )

  return (
    <>
      <PageHeader
        title="Teach"
        subtitle="Show Exemplar a few clips of what you care about. It drafts rule sketches, a solver fills in the numbers, and you get readable rules to compare."
      />

      <div className="grid grid-cols-1 gap-12 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] xl:gap-14">
        {/* ---------------------------------------------------------------- 1. examples */}
        <section aria-labelledby="ex-h" className="min-w-0 xl:sticky xl:top-20 xl:self-start">
          <SectionHeader step={1} id="ex-h" title="Pick examples" description="Clips that show the thing (+) and clips that do not (−)." />
          <div className="rounded-xl border border-ex-line bg-ex-panel">
            <div className="grid gap-3 p-4">
              <ConceptSelect id="teach-concept" label="Concept" className="w-full" />
              {concept && (
                <p className="text-sm text-ex-ink2">
                  <span className="text-ex-ink3">Your hint </span>
                  {concept.nl_hint ? <>“{concept.nl_hint}”</> : <em>none</em>}
                  <span className="text-ex-ink3"> · α = {concept.alpha}</span>
                </p>
              )}
              <NewConcept onCreated={async (c) => { await refreshConcepts(); setConceptId(c.id) }} />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ex-line px-4 py-3">
              <Segmented
                label="Which clips to show"
                value={pickerTab}
                onChange={setPickerTab}
                options={[{ value: 'chosen', label: 'Chosen', count: chosen.length }, { value: 'all', label: 'All clips' }]}
              />
              <p className="text-sm tabular-nums">
                <span className="text-ex-pos">+{positives}</span> <span className="sr-only">positive, </span>
                <span className="ml-1.5 text-ex-neg">−{negatives}</span> <span className="sr-only">negative</span>
              </p>
            </div>
            {eventsErr && <div className="px-4 pb-3"><Alert tone="neg">{eventsErr}</Alert></div>}
            <div tabIndex={0} role="region" aria-label="Clips to label as examples" className="max-h-[440px] overflow-y-auto border-t border-ex-line px-4">
              {pickerTab === 'chosen' ? (
                chosen.length === 0 ? (
                  <div className="py-8 text-center">
                    <p className="font-medium text-ex-ink">No examples yet</p>
                    <p className="mx-auto mt-1 max-w-xs text-sm text-ex-ink2">Switch to “All clips” and mark at least one clip as + for this concept.</p>
                  </div>
                ) : (
                  <div>
                    {[{ key: 'pos', title: 'Positives', list: chosenPos }, { key: 'neg', title: 'Negatives', list: chosenNeg }].filter((g) => g.list.length > 0).map((g) => (
                      <div key={g.key}>
                        <p className="sticky top-0 z-10 -mx-4 border-b border-ex-line bg-ex-panel px-4 py-1.5 text-xs font-medium text-ex-ink3">{g.title} <span className="tabular-nums">· {g.list.length}</span></p>
                        <ul className="divide-y divide-ex-line">
                          {g.list.map((ev) => <ExampleRow key={ev.id} ev={ev} concept={concept} onOpen={() => setOpenId(ev.id)} onLabel={(v) => setLabel(ev, v)} />)}
                        </ul>
                      </div>
                    ))}
                  </div>
                )
              ) : (
                <ul className="divide-y divide-ex-line">
                  {allClips.map((ev) => <ExampleRow key={ev.id} ev={ev} concept={concept} onOpen={() => setOpenId(ev.id)} onLabel={(v) => setLabel(ev, v)} />)}
                </ul>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3 border-t border-ex-line p-4">
              {teachButton}
              {!conceptId && <span className="text-sm text-ex-ink2">Create or choose a concept first.</span>}
              {conceptId && positives === 0 && <span className="inline-flex items-center gap-1.5 text-sm text-ex-warn"><Icon name="warning" className="h-3.5 w-3.5" /> Mark at least one clip as + to teach from.</span>}
            </div>
          </div>
        </section>

        <div className="grid min-w-0 grid-cols-1 content-start gap-12">
          {/* -------------------------------------------------------------- 2. timeline */}
          <section aria-labelledby="tl-h">
            <SectionHeader
              step={2}
              id="tl-h"
              headingRef={tlHeadRef}
              tabIndex={-1}
              title="What the agent is doing"
              actions={running ? <Spinner label="Running" /> : run ? <Badge tone={runError ? 'neg' : 'pos'}>{runError ? 'Failed' : 'Finished'}</Badge> : null}
            />
            {runError && <div className="mb-4"><Alert tone="neg" title="Teaching did not finish">{runError}</Alert></div>}
            {status === 'reconnecting' && <p className="mb-3 text-sm text-ex-warn">Connection dropped, reconnecting…</p>}
            <div className="rounded-xl border border-ex-line bg-ex-panel p-5">
              <AgentTimeline ref={tlRef} timeline={timeline} clips={byClip} running={running} />
            </div>
          </section>

          {/* -------------------------------------------------------------- 3. question */}
          {haveRules && (
            <section aria-label="Question from Exemplar" className="grid gap-3">
              {answered && (
                <div ref={answerRef} tabIndex={-1} className="focus:outline-none">
                  <Alert tone="pos" title="Answer saved" action={<button type="button" className="btn btn-sm" onClick={startTeach} disabled={running}><Icon name="bolt" className="h-3.5 w-3.5" /> Teach again</button>}>
                    {answered} Teach again to fold it into the candidates.
                  </Alert>
                </div>
              )}
              {q ? (
                <QuestionCard
                  step={3}
                  q={q}
                  busy={answering}
                  onAnswer={answer}
                  onSkip={() => setSkipped((s) => [...s, q.clip_id])}
                  onOpen={() => q.event && setOpenId(q.event.id)}
                />
              ) : (
                <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-ex-line bg-ex-panel px-5 py-4">
                  <p className="flex items-center gap-2.5 text-sm text-ex-ink2">
                    <Icon name={question.data && skipped.includes(question.data.clip_id) ? 'question' : 'check'} className="h-4 w-4 text-ex-ink3" />
                    <span><span className="mr-1.5 text-ex-ink3">3 ·</span>{question.data && skipped.includes(question.data.clip_id)
                      ? 'You skipped the question.'
                      : 'Nothing left to ask: your rules agree on every clip in the library.'}</span>
                  </p>
                  {question.data && skipped.includes(question.data.clip_id) && (
                    <button type="button" className="btn btn-sm" onClick={() => setSkipped([])}>Ask again</button>
                  )}
                </div>
              )}
            </section>
          )}

          {/* -------------------------------------------------------------- 4. candidates */}
          <section aria-labelledby="cand-h">
            <SectionHeader
              step={haveRules ? 4 : 3}
              id="cand-h"
              title="Candidate rules"
              description={haveRules ? 'Ranked by description length (simplest first), then margin.' : undefined}
            />
            {rules.loading && !rules.data && (
              <div role="status" aria-label="Loading rules" className="grid gap-3"><div className="skeleton h-40" /><div className="skeleton h-16" style={{ opacity: 0.6 }} /></div>
            )}
            {rules.error && <Alert tone="neg" title="Could not load the rules">{rules.error.message}</Alert>}
            {!haveRules && !rules.loading && (
              <div className="rounded-xl border border-ex-line bg-ex-panel px-6 py-10 text-center">
                <span aria-hidden="true" className="mx-auto grid h-9 w-9 place-items-center rounded-lg bg-ex-raised text-ex-ink3"><Icon name="spark" className="h-4 w-4" /></span>
                <p className="mt-3 font-medium text-ex-ink">No rules yet</p>
                <p className="mx-auto mt-1 max-w-sm text-sm text-ex-ink2">They appear here, simplest first, when a run finishes.</p>
              </div>
            )}
            {haveRules && (
              <div className="grid gap-8">
                <HeroRuleCard rule={ranked[0]} events={byClip} onInspect={(id) => setOpenId(id)} />
                {ranked.length > 1 && (
                  <div>
                    <h3 className="text-sm font-semibold text-ex-ink">Other candidates <span className="font-normal tabular-nums text-ex-ink3">· {ranked.length - 1}</span></h3>
                    <ol className="mt-2 divide-y divide-ex-line border-y border-ex-line" start={2}>
                      {ranked.slice(1).map((r, i) => (
                        <CandidateRow key={r.id} rule={r} rank={i + 2} events={byClip} onInspect={(id) => setOpenId(id)} />
                      ))}
                    </ol>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </div>

      <div role="status" aria-live="polite" className="sr-only">{notice}</div>
      <EventDialog eventId={openId} onClose={() => setOpenId(null)} />
    </>
  )
}
