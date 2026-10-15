'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../_lib/app'
import { errorMessage, get, post, put, api } from '../_lib/api'
import { fmtDuration, fmtRelative, negativesNeeded } from '../_lib/format'
import type { Concept, EventSummary, LabelSummary } from '../_lib/types'
import { ConceptSelect } from '../_components/ConceptSelect'
import { EventDialog } from '../_components/EventDialog'
import { EventThumb, KindBadges, LabelChips, ProvenanceBadge, SourceBadge, TraceStatusBadge } from '../_components/EventBits'
import { Icon } from '../_components/Icon'
import { Alert, Badge, Empty, PageHeader, Spinner } from '../_components/ui'

const SOURCES = [
  { value: '', label: 'All sources' },
  { value: 'ring', label: 'Ring' },
  { value: 'ring_live', label: 'Ring live capture' },
  { value: 'upload', label: 'Uploads' },
  { value: 'meva', label: 'MEVA' },
  { value: 'fixture', label: 'Fixtures' },
]
const LABELLED = [
  { value: 'any', label: 'Any label state' },
  { value: 'pos', label: 'Positive' },
  { value: 'neg', label: 'Negative' },
  { value: 'unlabelled', label: 'Unlabelled' },
]

const PAGE = 120

// ---------------------------------------------------------------------------------------------
function CountsBar({ concept }: { concept: Concept }) {
  const c = concept.counts ?? {}
  const need = negativesNeeded(concept.alpha)
  const have = c.random_neg ?? 0
  const ok = have >= need
  const item = (label: string, pos?: number, neg?: number) => (
    <div className="rounded-lg border border-ex-line bg-ex-bg px-3 py-2">
      <dt className="text-xs text-ex-ink3">{label}</dt>
      <dd className="mt-0.5 flex gap-3 text-sm font-semibold text-ex-ink">
        <span className="text-green-300"><span aria-hidden="true">+</span><span className="sr-only">positive </span>{pos ?? 0}</span>
        <span className="text-red-300"><span aria-hidden="true">−</span><span className="sr-only">negative </span>{neg ?? 0}</span>
      </dd>
    </div>
  )
  return (
    <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {item('Your examples', c.example_pos, c.example_neg)}
      {item('Asked of you', c.active_pos, c.active_neg)}
      {item('Calibration (random)', c.random_pos, c.random_neg)}
      <div className="rounded-lg border border-ex-line bg-ex-bg px-3 py-2">
        <dt className="text-xs text-ex-ink3">False-alarm guarantee at α = {concept.alpha}</dt>
        <dd className="mt-1">
          <progress className="sr-only" max={need} value={Math.min(have, need)} aria-label="Random negatives collected" />
          <div className="h-2 overflow-hidden rounded-full bg-ex-raised" aria-hidden="true">
            <div className={`h-full ${ok ? 'bg-green-400' : 'bg-amber-400'}`} style={{ width: `${Math.min(1, have / Math.max(1, need)) * 100}%` }} />
          </div>
          <p className="mt-1 text-xs text-ex-ink2">
            {ok ? (
              <span className="inline-flex items-center gap-1 text-green-300"><Icon name="check" className="h-3.5 w-3.5" /> {have} random negatives: enough</span>
            ) : (
              <>{have} of {need} random negatives needed</>
            )}
          </p>
        </dd>
      </div>
    </dl>
  )
}

// ---------------------------------------------------------------------------------------------
function CalibrationPanel({
  concept, onClose, onChanged,
}: { concept: Concept; onClose: () => void; onChanged: () => void }) {
  const [clips, setClips] = useState<EventSummary[] | null>(null)
  const [answers, setAnswers] = useState<Record<string, 'pos' | 'neg'>>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const headingRef = useRef<HTMLHeadingElement>(null)

  const draw = useCallback(async () => {
    setClips(null)
    setAnswers({})
    setError(null)
    try {
      const list = await post<EventSummary[]>(`/concepts/${concept.id}/random-sample?n=10`)
      setClips(list)
    } catch (e) {
      setError(errorMessage(e))
      setClips([])
    }
  }, [concept.id])

  useEffect(() => {
    draw()
  }, [draw])
  useEffect(() => {
    if (clips) headingRef.current?.focus()
  }, [clips])

  async function answer(clip: EventSummary, value: 'pos' | 'neg') {
    setAnswers((a) => ({ ...a, [clip.clip_id]: value }))
    try {
      await put(`/concepts/${concept.id}/labels`, { clip_id: clip.clip_id, value, provenance: 'random' })
      onChanged()
    } catch (e) {
      setAnswers((a) => { const n = { ...a }; delete n[clip.clip_id]; return n })
      setError(errorMessage(e))
    }
  }

  async function allRestNegative() {
    if (!clips) return
    const rest = clips.filter((c) => !answers[c.clip_id]).map((c) => c.clip_id)
    if (!rest.length) return
    setBusy(true)
    try {
      await post(`/concepts/${concept.id}/labels/bulk-negative`, { clip_ids: rest, provenance: 'random' })
      setAnswers((a) => ({ ...a, ...Object.fromEntries(rest.map((id) => [id, 'neg' as const])) }))
      onChanged()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const done = clips ? clips.filter((c) => answers[c.clip_id]).length : 0

  return (
    <section aria-labelledby="calib-h" className="rounded-xl border-2 border-amber-400/70 bg-ex-panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="calib-h" ref={headingRef} tabIndex={-1} className="flex items-center gap-2 text-lg font-semibold focus:outline-none">
            <Icon name="shuffle" className="h-5 w-5 text-amber-300" /> Calibration labels: 10 random clips
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-ex-ink2">
            Does each clip show <strong className="text-ex-ink">“{concept.name}”</strong>? These clips were drawn uniformly at random from your history,
            and your answers set the false-alarm guarantee. That only works if the sample is random and honest, so answer every clip, including the
            hard ones. Clips you pick yourself elsewhere are used for learning only and are never counted here.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn" onClick={draw} disabled={busy}><Icon name="shuffle" /> Draw another 10</button>
          <button type="button" className="btn" onClick={onClose}><Icon name="check" /> Done</button>
        </div>
      </div>

      {error && <div className="mt-3"><Alert tone="neg" title="Could not save that label">{error}</Alert></div>}
      {!clips && <div className="mt-4"><Spinner label="Drawing a random sample" /></div>}
      {clips && clips.length === 0 && !error && (
        <div className="mt-4"><Empty title="Nothing left to sample">Every clip with a trace already has a label for this concept.</Empty></div>
      )}
      {clips && clips.length > 0 && (
        <>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-ex-ink2" role="status">{done} of {clips.length} answered</p>
            <button type="button" className="btn" onClick={allRestNegative} disabled={busy || done === clips.length}>
              <Icon name="minus" /> Mark all unanswered as not matching
            </button>
          </div>
          <ol className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
            {clips.map((c, i) => {
              const a = answers[c.clip_id]
              return (
                <li key={c.id} className="flex gap-3 rounded-lg border border-ex-line bg-ex-bg p-2">
                  <EventThumb event={c} className="h-[72px] w-32 shrink-0 rounded-md" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-ex-ink"><span className="mr-1 text-ex-ink3">{i + 1}.</span>{c.summary || c.clip_id}</p>
                    <div role="group" aria-label={`Does clip ${i + 1} show ${concept.name}?`} className="mt-1.5 flex gap-2">
                      <button
                        type="button"
                        aria-pressed={a === 'pos'}
                        onClick={() => answer(c, 'pos')}
                        className={`inline-flex min-h-[36px] items-center gap-1 rounded-md border px-3 text-sm font-medium ${a === 'pos' ? 'border-transparent bg-green-400 text-slate-950' : 'border-ex-edge bg-ex-raised text-ex-ink hover:bg-[#243556]'}`}
                      >
                        <Icon name="check" /> Matches
                      </button>
                      <button
                        type="button"
                        aria-pressed={a === 'neg'}
                        onClick={() => answer(c, 'neg')}
                        className={`inline-flex min-h-[36px] items-center gap-1 rounded-md border px-3 text-sm font-medium ${a === 'neg' ? 'border-transparent bg-red-400 text-slate-950' : 'border-ex-edge bg-ex-raised text-ex-ink hover:bg-[#243556]'}`}
                      >
                        <Icon name="cross" /> Doesn’t match
                      </button>
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        </>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
function UploadDialog({
  open, onClose, onUploaded,
}: { open: boolean; onClose: () => void; onUploaded: (n: number) => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const fd = new FormData(e.currentTarget)
      const windows = await api<EventSummary[]>('POST', '/uploads', fd)
      onUploaded(windows?.length ?? 0)
      ref.current?.close()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="upload-h"
      onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) ref.current?.close() }}
      className="m-auto w-[min(560px,94vw)] rounded-xl border border-ex-line bg-ex-panel p-0 text-ex-ink backdrop:bg-black/70"
    >
      <form onSubmit={submit} className="p-5">
        <h2 id="upload-h" className="text-lg font-semibold">Upload footage</h2>
        <p className="mt-1 text-sm text-ex-ink2">
          Add third-party video (for example CC BY footage). It is cut into windows, each window becomes an <em>upload</em> event and is read by the model.
          Uploads never reach live monitors.
        </p>
        <div className="mt-4 grid gap-3">
          <div>
            <label className="field-label" htmlFor="up-file">Video file (MP4)</label>
            <input id="up-file" name="file" type="file" accept="video/mp4,video/*" required className="field file:mr-3 file:rounded file:border-0 file:bg-ex-raised file:px-3 file:py-1 file:text-ex-ink" />
          </div>
          <div>
            <label className="field-label" htmlFor="up-attr">Credit line (required)</label>
            <input id="up-attr" name="attribution" required className="field" placeholder={'"Thief stealing our package" by frollard, CC BY 4.0'} />
          </div>
          <div>
            <label className="field-label" htmlFor="up-url">Source URL (optional)</label>
            <input id="up-url" name="source_url" type="url" className="field" placeholder="https://www.youtube.com/watch?v=TfTFu8lGrwk" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="field-label" htmlFor="up-win">Window length (s)</label>
              <input id="up-win" name="window_s" type="number" min={2} step={1} defaultValue={20} className="field" />
            </div>
            <div>
              <label className="field-label" htmlFor="up-stride">Stride (s)</label>
              <input id="up-stride" name="stride_s" type="number" min={1} step={1} defaultValue={10} className="field" />
            </div>
          </div>
        </div>
        {error && <div className="mt-3"><Alert tone="neg" title="Upload failed">{error}</Alert></div>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className="btn" onClick={() => ref.current?.close()}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}><Icon name="upload" /> {busy ? 'Uploading…' : 'Upload and cut'}</button>
        </div>
      </form>
    </dialog>
  )
}

// ---------------------------------------------------------------------------------------------
function EventCard({
  ev, concept, selected, onToggle, onOpen, onLabel,
}: {
  ev: EventSummary
  concept: Concept | null
  selected: boolean
  onToggle: () => void
  onOpen: () => void
  onLabel: (v: 'pos' | 'neg' | null) => void
}) {
  const title = ev.summary || (ev.trace_status === 'none' ? 'Waiting for the model to read this clip' : ev.clip_id)
  return (
    <li className="flex flex-col overflow-hidden rounded-xl border border-ex-line bg-ex-panel">
      <div className="relative">
        <button type="button" onClick={onOpen} aria-label={`View details: ${title}${ev.has_snapshot ? '' : ' (No snapshot)'}`} className="group block aspect-video w-full overflow-hidden rounded-none">
          <EventThumb event={ev} showLabel={false} className="h-full w-full transition-opacity group-hover:opacity-90" />
        </button>
        {ev.duration_ms != null && (
          <span aria-hidden="true" className="pointer-events-none absolute bottom-1.5 right-1.5 rounded bg-black/75 px-1.5 py-0.5 font-mono text-[11px] text-white">{fmtDuration(ev.duration_ms)}</span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <p className="line-clamp-2 min-h-[2.5rem] text-sm text-ex-ink">{title}</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <SourceBadge source={ev.source} />
          <KindBadges event={ev} />
          <TraceStatusBadge event={ev} />
        </div>
        <p className="text-xs text-ex-ink3" title={new Date(ev.start_ms).toLocaleString()}>{fmtRelative(ev.start_ms)}{ev.duration_ms != null && <> · {fmtDuration(ev.duration_ms)} long</>}</p>
        {ev.attribution && <p className="text-xs italic text-ex-ink2">{ev.attribution}</p>}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 border-t border-ex-line pt-2">
          {concept ? (
            <LabelChips
              conceptName={concept.name}
              clipSummary={title}
              value={ev.label?.value ?? null}
              disabled={ev.trace_status !== 'ok'}
              onSet={onLabel}
            />
          ) : (
            <span className="text-xs text-ex-ink3">Pick a concept to label</span>
          )}
          <label className="inline-flex min-h-[36px] cursor-pointer items-center gap-1.5 text-xs text-ex-ink2">
            <input type="checkbox" className="h-4 w-4 accent-cyan-400" checked={selected} onChange={onToggle} aria-label={`Select: ${title}`} />
            Select
          </label>
        </div>
        <ProvenanceBadge label={ev.label} />
      </div>
    </li>
  )
}

// ---------------------------------------------------------------------------------------------
export default function LibraryScreen() {
  const { concept, conceptId, refreshConcepts, setConceptId } = useApp()
  const params = useSearchParams()
  const [source, setSource] = useState('')
  const [labelled, setLabelled] = useState('any')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<EventSummary[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [openId, setOpenId] = useState<string | null>(null)
  const [calibrating, setCalibrating] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const count = useRef(PAGE)

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (conceptId) p.set('concept_id', conceptId)
    if (source) p.set('source', source)
    if (conceptId && labelled !== 'any') p.set('labelled', labelled)
    return p
  }, [conceptId, source, labelled])

  const load = useCallback(
    async (opts: { more?: boolean; silent?: boolean } = {}) => {
      if (!opts.silent) setLoading(true)
      try {
        const p = new URLSearchParams(qs)
        p.set('limit', String(opts.more ? PAGE : Math.min(500, Math.max(PAGE, count.current))))
        if (opts.more && cursor) p.set('cursor', cursor)
        const res = await get<{ items: EventSummary[]; next_cursor?: string | null }>(`/events?${p}`)
        setItems((prev) => (opts.more ? [...prev, ...res.items] : res.items))
        if (!opts.more) count.current = Math.max(PAGE, res.items.length)
        else count.current += res.items.length
        setCursor(res.next_cursor ?? null)
        setError(null)
      } catch (e) {
        setError(errorMessage(e))
      } finally {
        setLoading(false)
      }
    },
    [qs, cursor],
  )

  // Reload when filters / concept change.
  useEffect(() => {
    count.current = PAGE
    setSelected(new Set())
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qs])

  // While some clips are still being fetched or read, poll quietly.
  const pending = items.some((e) => e.trace_status === 'none' && e.clip_status !== 'failed' && e.clip_status !== 'not_found')
  useEffect(() => {
    if (!pending) return
    const t = setInterval(() => load({ silent: true }), 3000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, qs])

  useEffect(() => {
    const wanted = params.get('concept')
    if (wanted && wanted !== conceptId) setConceptId(wanted)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  useEffect(() => {
    if (params.get('calibrate') === '1' && concept) setCalibrating(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [concept?.id])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter((e) => `${e.summary ?? ''} ${e.clip_id} ${e.attribution ?? ''} ${e.kind ?? ''} ${e.sub_type ?? ''}`.toLowerCase().includes(q))
  }, [items, query])

  async function setLabel(ev: EventSummary, value: 'pos' | 'neg' | null) {
    if (!concept) return
    const provenance = ev.label?.provenance ?? 'example'
    const prev = ev.label ?? null
    const next: LabelSummary | null = value
      ? { concept_id: concept.id, clip_id: ev.clip_id, value, provenance, weight: prev?.weight ?? 3 }
      : null
    setItems((list) => list.map((e) => (e.id === ev.id ? { ...e, label: next } : e)))
    try {
      await put(`/concepts/${concept.id}/labels`, { clip_id: ev.clip_id, value, provenance })
      setNotice(value ? `Marked ${value === 'pos' ? 'positive' : 'negative'}: ${ev.summary ?? ev.clip_id}` : `Cleared label: ${ev.summary ?? ev.clip_id}`)
      refreshConcepts()
    } catch (e) {
      setItems((list) => list.map((x) => (x.id === ev.id ? { ...x, label: prev } : x)))
      setError(errorMessage(e))
    }
  }

  async function bulkNegative() {
    if (!concept || selected.size === 0) return
    setBusy(true)
    try {
      await post(`/concepts/${concept.id}/labels/bulk-negative`, { clip_ids: Array.from(selected), provenance: 'example' })
      setNotice(`Marked ${selected.size} clip${selected.size === 1 ? '' : 's'} negative as examples.`)
      setSelected(new Set())
      await Promise.all([load({ silent: true }), refreshConcepts()])
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  async function sync() {
    setSyncing(true)
    try {
      const r = await post<{ new_events?: number }>('/ring/sync')
      setNotice(`Sync started: ${r?.new_events ?? 0} new event${r?.new_events === 1 ? '' : 's'}.`)
      await load({ silent: true })
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSyncing(false)
    }
  }

  const toggle = (clipId: string) =>
    setSelected((s) => {
      const n = new Set(s)
      if (n.has(clipId)) n.delete(clipId)
      else n.add(clipId)
      return n
    })

  return (
    <>
      <PageHeader
        title="Library"
        subtitle="Every clip Exemplar has seen: Ring history, live captures and uploaded footage. Label a few as + or − for the concept you want to teach."
        actions={
          <>
            <button type="button" className="btn" onClick={sync} disabled={syncing}><Icon name="refresh" /> {syncing ? 'Syncing…' : 'Sync from Ring'}</button>
            <button type="button" className="btn" onClick={() => setUploadOpen(true)}><Icon name="upload" /> Upload footage</button>
          </>
        }
      />

      <div className="card mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <ConceptSelect label="Label for concept" />
          <div>
            <label htmlFor="f-source" className="field-label">Source</label>
            <select id="f-source" className="field" value={source} onChange={(e) => setSource(e.target.value)}>
              {SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="f-labelled" className="field-label">Label state</label>
            <select id="f-labelled" className="field" value={labelled} onChange={(e) => setLabelled(e.target.value)} disabled={!conceptId}>
              {LABELLED.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="min-w-[200px] flex-1">
            <label htmlFor="f-q" className="field-label">Search</label>
            <input id="f-q" type="search" className="field" placeholder="Text in the description" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
        </div>
        {concept && (
          <div className="mt-4">
            <CountsBar concept={concept} />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button type="button" className="btn-primary" onClick={() => setCalibrating(true)} disabled={calibrating}>
                <Icon name="shuffle" /> Label 10 random (calibration)
              </button>
              <button type="button" className="btn" onClick={bulkNegative} disabled={busy || selected.size === 0}>
                <Icon name="minus" /> Mark {selected.size || ''} selected as negative
              </button>
              <button type="button" className="btn" onClick={() => setSelected(new Set(shown.filter((e) => e.trace_status === 'ok').map((e) => e.clip_id)))}>Select all shown</button>
              <button type="button" className="btn" onClick={() => setSelected(new Set())} disabled={selected.size === 0}>Clear selection</button>
              <Link href="/teach" className="btn ml-auto">Teach this concept <Icon name="chevron-right" /></Link>
            </div>
          </div>
        )}
      </div>

      {calibrating && concept && (
        <div className="mb-4">
          <CalibrationPanel
            concept={concept}
            onClose={() => { setCalibrating(false); load({ silent: true }) }}
            onChanged={() => refreshConcepts()}
          />
        </div>
      )}

      <div role="status" aria-live="polite" className="sr-only">{notice}</div>
      {error && <div className="mb-4"><Alert tone="neg" title="Something went wrong">{error}</Alert></div>}

      {loading && items.length === 0 ? (
        <Spinner label="Loading the library" />
      ) : shown.length === 0 ? (
        <Empty title="No clips match these filters">Try another source or label state, or sync history from Ring.</Empty>
      ) : (
        <>
          <p className="mb-2 text-sm text-ex-ink3">
            {shown.length} clip{shown.length === 1 ? '' : 's'}
            {pending && <span className="ml-2 inline-flex items-center gap-1"><Badge tone="neutral" icon="clock">Reading new clips…</Badge></span>}
          </p>
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {shown.map((ev) => (
              <EventCard
                key={ev.id}
                ev={ev}
                concept={concept}
                selected={selected.has(ev.clip_id)}
                onToggle={() => toggle(ev.clip_id)}
                onOpen={() => setOpenId(ev.id)}
                onLabel={(v) => setLabel(ev, v)}
              />
            ))}
          </ul>
          {cursor && (
            <div className="mt-4 text-center">
              <button type="button" className="btn" onClick={() => load({ more: true })} disabled={loading}>Load more</button>
            </div>
          )}
        </>
      )}

      <EventDialog eventId={openId} onClose={() => setOpenId(null)} />
      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={(n) => { setNotice(`${n} window${n === 1 ? '' : 's'} added from the upload; the model is reading them.`); load({ silent: true }) }}
      />
    </>
  )
}
