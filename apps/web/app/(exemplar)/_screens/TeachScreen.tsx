'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApp } from '../_lib/app'
import { ApiError, errorMessage, get, post, put } from '../_lib/api'
import { fmtNum } from '../_lib/format'
import { useApi, useEventStream } from '../_lib/hooks'
import type { Concept, EventSummary, LabelSummary, Question, RuleSummary, Run, RunEvent, RunEventType } from '../_lib/types'
import { ConceptSelect } from '../_components/ConceptSelect'
import { EventDialog } from '../_components/EventDialog'
import { EventThumb, LabelChips, ProvenanceBadge } from '../_components/EventBits'
import { Icon, type IconName } from '../_components/Icon'
import { QuestionCard } from '../_components/QuestionCard'
import { RuleCard } from '../_components/RuleCard'
import { Alert, Badge, Empty, PageHeader, Spinner, type Tone } from '../_components/ui'

const RUN_TYPES: RunEventType[] = [
  'round_started', 'sketch_proposed', 'typecheck_failed', 'solve_started', 'solve_result',
  'differential_check', 'counterexample', 'candidates', 'question_ready', 'done', 'error',
]

// ---------------------------------------------------------------------------------------------
// Timeline
const STEP: Record<RunEventType, { icon: IconName; tone: Tone; title: (e: RunEvent) => string }> = {
  round_started: { icon: 'flag', tone: 'neutral', title: (e) => `Round ${e.round ?? '?'}` },
  sketch_proposed: { icon: 'spark', tone: 'accent', title: () => 'Rule sketch proposed' },
  typecheck_failed: { icon: 'cross', tone: 'neg', title: () => 'Type check failed, sketch sent back' },
  solve_started: { icon: 'clock', tone: 'neutral', title: () => 'Z3 is filling in the numbers' },
  solve_result: {
    icon: 'check', tone: 'pos',
    title: (e) => (e.result === 'sat' ? 'Z3 found thresholds that fit every example' : e.result === 'unsat' ? 'Z3 proved no thresholds fit' : e.result === 'timeout' ? 'Z3 timed out' : e.result === 'grid_fallback' ? 'Fell back to a grid search' : 'Solver finished'),
  },
  differential_check: { icon: 'shield', tone: 'pos', title: () => 'Differential check against the independent evaluator' },
  counterexample: { icon: 'warning', tone: 'warn', title: () => 'Counterexample: perception suspect?' },
  candidates: { icon: 'check', tone: 'pos', title: () => 'Candidate rules ready' },
  question_ready: { icon: 'question', tone: 'info', title: () => 'One question is ready for you' },
  done: { icon: 'check', tone: 'pos', title: () => 'Done' },
  error: { icon: 'cross', tone: 'neg', title: () => 'The run failed' },
}

const RING: Record<Tone, string> = {
  neutral: 'bg-ex-raised text-ex-ink2 border-ex-line',
  pos: 'bg-green-950 text-green-300 border-green-500/60',
  neg: 'bg-red-950 text-red-300 border-red-400/60',
  warn: 'bg-amber-950 text-amber-200 border-amber-400/60',
  info: 'bg-sky-950 text-sky-200 border-sky-400/60',
  accent: 'bg-cyan-950 text-cyan-200 border-cyan-300/60',
}

function TimelineItem({ e, t0, clips }: { e: RunEvent; t0: number; clips: Map<string, EventSummary> }) {
  const s = STEP[e.type]
  const tone: Tone = e.type === 'solve_result' && e.result && e.result !== 'sat' ? 'warn' : s.tone
  const icon: IconName = e.type === 'solve_result' && e.result && e.result !== 'sat' ? 'warning' : s.icon
  const holes = Object.entries(e.holes ?? {})
  return (
    <li className="flex gap-3 motion-safe:animate-ex-in">
      <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border ${RING[tone]}`}>
        <Icon name={icon} className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1 border-b border-ex-line pb-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm font-medium text-ex-ink">{s.title(e)}</p>
          <span className="font-mono text-xs tabular-nums text-ex-ink3">+{((e.at_ms - t0) / 1000).toFixed(1)} s</span>
        </div>
        {e.sketch && <pre className="code mt-1.5 text-[12.5px]"><code>{e.sketch}</code></pre>}
        {e.error && <p className="mt-1 text-sm text-red-300"><span className="sr-only">Error: </span>{e.error}</p>}
        {(holes.length > 0 || e.margin != null) && (
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {holes.map(([k, v]) => (
              <li key={k} className="chip"><span className="font-mono text-ex-ink">{k}</span> = <span className="font-mono tabular-nums text-ex-ink">{v}</span></li>
            ))}
            {e.margin != null && <li className="chip">margin <span className="font-mono tabular-nums text-ex-ink">{fmtNum(e.margin)}</span></li>}
          </ul>
        )}
        {e.message && <p className="mt-1 text-sm text-ex-ink2">{e.message}</p>}
        {e.type === 'counterexample' && (e.violated_clip_ids?.length ?? 0) > 0 && (
          <ul className="mt-1.5 flex flex-wrap gap-2">
            {e.violated_clip_ids!.map((id) => {
              const ev = clips.get(id)
              return (
                <li key={id} className="flex items-center gap-2 rounded-md border border-amber-400/40 bg-ex-bg p-1 pr-2">
                  {ev && <EventThumb event={ev} className="h-8 w-14 rounded" />}
                  <span className="max-w-[18rem] truncate text-xs text-ex-ink2">{ev?.summary ?? id}</span>
                </li>
              )
            })}
          </ul>
        )}
        {e.type === 'candidates' && (e.rule_ids?.length ?? 0) > 0 && (
          <p className="mt-1 text-xs text-ex-ink3">{e.rule_ids!.length} rules, ranked by description length then margin.</p>
        )}
      </div>
    </li>
  )
}

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
    <details className="rounded-lg border border-ex-line bg-ex-bg p-3">
      <summary className="cursor-pointer rounded text-sm font-medium text-ex-info">Teach a new concept</summary>
      <form onSubmit={submit} className="mt-3 grid gap-3">
        <div>
          <label htmlFor="nc-name" className="field-label">Name</label>
          <input id="nc-name" className="field" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Someone at the door who doesn’t ring" />
        </div>
        <div>
          <label htmlFor="nc-hint" className="field-label">Hint in your own words (optional)</label>
          <textarea id="nc-hint" className="field min-h-[72px]" value={hint} onChange={(e) => setHint(e.target.value)} aria-describedby="nc-hint-help" />
          <p id="nc-hint-help" className="mt-1 text-xs text-ex-ink3">The model reads this when it drafts rule sketches. The rules you get back are built by the solver, not by the hint.</p>
        </div>
        <div>
          <label htmlFor="nc-alpha" className="field-label">Acceptable false-alarm rate α</label>
          <input id="nc-alpha" className="field w-32" type="number" min={0.01} max={0.5} step={0.01} value={alpha} onChange={(e) => setAlpha(e.target.value)} required />
        </div>
        {error && <Alert tone="neg" title="Could not create the concept">{error}</Alert>}
        <div><button className="btn-primary" type="submit" disabled={busy || !name.trim()}>{busy ? 'Creating…' : 'Create concept'}</button></div>
      </form>
    </details>
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
  const positives = chosen.filter((e) => e.label?.value === 'pos').length
  const negatives = chosen.filter((e) => e.label?.value === 'neg').length
  const picker = pickerTab === 'chosen' ? chosen : events.filter((e) => e.trace_status === 'ok')

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
    } catch (e) {
      setRunError(errorMessage(e))
    } finally {
      setAnswering(false)
    }
  }

  const q = question.data && !skipped.includes(question.data.clip_id) ? question.data : null
  const haveRules = (rules.data?.length ?? 0) > 0
  const canTeach = !!conceptId && positives > 0 && !running
  const t0 = timeline[0]?.at_ms ?? 0

  return (
    <>
      <PageHeader
        title="Teach"
        subtitle="Show Exemplar a few clips of what you care about. It drafts rule sketches, a solver fills in the numbers, and you get readable rules to compare."
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        {/* ---------------------------------------------------------------- 1. examples */}
        <section className="card" aria-labelledby="ex-h">
          <h2 id="ex-h" className="card-title">1. Pick examples</h2>
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <ConceptSelect id="teach-concept" label="Concept" />
          </div>
          {concept && (
            <p className="mt-3 text-sm text-ex-ink2">
              <span className="text-ex-ink3">Your hint: </span>
              {concept.nl_hint ? <>“{concept.nl_hint}”</> : <em>none</em>}
              <span className="text-ex-ink3"> · α = {concept.alpha}</span>
            </p>
          )}
          <div className="mt-3"><NewConcept onCreated={async (c) => { await refreshConcepts(); setConceptId(c.id) }} /></div>

          <div className="mt-4 flex flex-wrap items-center gap-2" role="group" aria-label="Which clips to show">
            <button type="button" className={`btn ${pickerTab === 'chosen' ? '!border-cyan-300' : ''}`} aria-pressed={pickerTab === 'chosen'} onClick={() => setPickerTab('chosen')}>
              Chosen ({chosen.length})
            </button>
            <button type="button" className={`btn ${pickerTab === 'all' ? '!border-cyan-300' : ''}`} aria-pressed={pickerTab === 'all'} onClick={() => setPickerTab('all')}>
              All clips
            </button>
            <span className="ml-auto text-sm text-ex-ink2">
              <span className="text-green-300">+{positives}</span> <span className="sr-only">positive, </span>
              <span className="text-red-300">−{negatives}</span> <span className="sr-only">negative</span>
            </span>
          </div>
          {eventsErr && <div className="mt-2"><Alert tone="neg">{eventsErr}</Alert></div>}
          <div tabIndex={0} role="region" aria-label="Clips to label as examples" className="mt-2 max-h-[520px] overflow-y-auto rounded-lg border border-ex-line bg-ex-bg">
            {picker.length === 0 ? (
              <div className="p-4"><Empty title="No examples yet">Switch to “All clips” and mark at least one clip as + for this concept.</Empty></div>
            ) : (
              <ul className="divide-y divide-ex-line">
                {picker.map((ev) => (
                  <li key={ev.id} className="flex items-center gap-3 p-2">
                    <button type="button" className="shrink-0 overflow-hidden rounded-md" onClick={() => setOpenId(ev.id)} aria-label={`View details: ${ev.summary ?? ev.clip_id}`}>
                      <EventThumb event={ev} className="h-[42px] w-[75px]" />
                    </button>
                    <div className="min-w-0 flex-1">
                      <p className="line-clamp-2 text-sm text-ex-ink">{ev.summary ?? ev.clip_id}</p>
                      <ProvenanceBadge label={ev.label} />
                    </div>
                    {concept && (
                      <LabelChips conceptName={concept.name} clipSummary={ev.summary ?? ev.clip_id} value={ev.label?.value ?? null} onSet={(v) => setLabel(ev, v)} />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="button" className="btn-primary" onClick={startTeach} disabled={!canTeach}>
              <Icon name="bolt" /> {running ? 'Teaching…' : haveRules ? 'Teach again' : 'Teach'}
            </button>
            {!conceptId && <span className="text-sm text-ex-ink2">Create or choose a concept first.</span>}
            {conceptId && positives === 0 && <span className="text-sm text-amber-200">Mark at least one clip as + to teach from.</span>}
          </div>
        </section>

        <div className="grid content-start gap-4">
          {/* -------------------------------------------------------------- 2. timeline */}
          <section className="card" aria-labelledby="tl-h">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="tl-h" className="card-title">2. What the agent is doing</h2>
              {running ? <Spinner label="Running" /> : run ? <Badge tone={runError ? 'neg' : 'pos'}>{runError ? 'Failed' : 'Finished'}</Badge> : null}
            </div>
            {runError && <div className="mt-3"><Alert tone="neg" title="Teaching did not finish">{runError}</Alert></div>}
            {status === 'reconnecting' && <p className="mt-2 text-sm text-amber-200">Connection dropped, reconnecting…</p>}
            {timeline.length === 0 ? (
              <p className="mt-3 text-sm text-ex-ink2">
                {running ? 'Waiting for the first step…' : 'Press Teach to watch the loop: sketch a rule, check its types, let Z3 solve the thresholds, then check the solution with an independent evaluator.'}
              </p>
            ) : (
              <ol role="log" aria-live="polite" aria-relevant="additions" aria-label="Agent timeline" className="mt-4 space-y-3">
                {timeline.map((e) => <TimelineItem key={e.seq} e={e} t0={t0} clips={byClip} />)}
              </ol>
            )}
          </section>

          {/* -------------------------------------------------------------- 3. candidates */}
          <section className="card" aria-labelledby="cand-h">
            <h2 id="cand-h" className="card-title">3. Candidate rules</h2>
            {rules.loading && !rules.data && <div className="mt-3"><Spinner label="Loading rules" /></div>}
            {rules.error && <div className="mt-3"><Alert tone="neg">{rules.error.message}</Alert></div>}
            {!haveRules && !rules.loading && (
              <p className="mt-3 text-sm text-ex-ink2">No rules yet. They appear here, simplest first, when a run finishes.</p>
            )}
            {haveRules && (
              <>
                <p className="mt-1 text-sm text-ex-ink2">Ranked by description length (simplest first), then margin.</p>
                <div className="mt-3 space-y-3">
                  {rules.data!.map((r, i) => (
                    <RuleCard key={r.id} rule={r} rank={i + 1} events={byClip} onInspect={(id) => setOpenId(id)} />
                  ))}
                </div>
              </>
            )}
          </section>

          {/* -------------------------------------------------------------- 4. question */}
          {haveRules && (
            <section aria-label="Question from Exemplar" className="grid gap-3">
              {answered && (
                <Alert tone="pos" title="Answer saved">
                  {answered} Teach again to fold it into the candidates.
                  <div className="mt-2"><button type="button" className="btn" onClick={startTeach} disabled={running}><Icon name="bolt" /> Teach again</button></div>
                </Alert>
              )}
              {q ? (
                <QuestionCard
                  q={q}
                  busy={answering}
                  onAnswer={answer}
                  onSkip={() => setSkipped((s) => [...s, q.clip_id])}
                  onOpen={() => q.event && setOpenId(q.event.id)}
                />
              ) : (
                <div className="card">
                  <h2 className="card-title">4. Question</h2>
                  <p className="mt-1 text-sm text-ex-ink2">
                    {question.data && skipped.includes(question.data.clip_id)
                      ? 'You skipped the question.'
                      : 'Nothing left to ask: your rules agree on every clip in the library.'}
                  </p>
                  {question.data && skipped.includes(question.data.clip_id) && (
                    <button type="button" className="btn mt-2" onClick={() => setSkipped([])}>Ask again</button>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      </div>

      <div role="status" aria-live="polite" className="sr-only">{notice}</div>
      <EventDialog eventId={openId} onClose={() => setOpenId(null)} />
    </>
  )
}
