'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../_lib/app'
import { errorMessage, get, post, put, api } from '../_lib/api'
import { clipName, fmtDuration, fmtRelative, negativesNeeded } from '../_lib/format'
import type { Concept, EventSummary, LabelSummary } from '../_lib/types'
import { ConceptSelect } from '../_components/ConceptSelect'
import { EventDialog } from '../_components/EventDialog'
import { EventThumb, LabelControl, LabelIndicator, SourceTag, TraceStatusBadge } from '../_components/EventBits'
import { Icon } from '../_components/Icon'
import { Alert, Empty, PageHeader, Skeleton, Spinner, cx } from '../_components/ui'

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
/** Where a clip comes from decides its group; groups carry the attribution once instead of every card. */
type GroupKey = 'ring' | 'upload' | 'meva' | 'fixture'
const GROUP_ORDER: GroupKey[] = ['ring', 'upload', 'meva', 'fixture']
const groupOf = (e: EventSummary): GroupKey => (e.source === 'ring' || e.source === 'ring_live' ? 'ring' : e.source)

// ---------------------------------------------------------------------------------------------
function ConceptSummary({ concept }: { concept: Concept }) {
  const c = concept.counts ?? {}
  const need = negativesNeeded(concept.alpha)
  const have = c.random_neg ?? 0
  const ok = have >= need
  const pair = (label: string, pos?: number, neg?: number, hint?: string) => (
    <div className="flex items-baseline gap-2" title={hint}>
      <dt className="text-xs text-ex-ink3">{label}</dt>
      <dd className="flex gap-2 text-sm font-medium tabular-nums">
        <span className="text-ex-pos"><span aria-hidden="true">+</span><span className="sr-only">positive </span>{pos ?? 0}</span>
        <span className="text-ex-neg"><span aria-hidden="true">−</span><span className="sr-only">negative </span>{neg ?? 0}</span>
      </dd>
    </div>
  )
  return (
    <dl className="flex flex-wrap items-center gap-x-6 gap-y-2">
      {pair('Your examples', c.example_pos, c.example_neg, 'Clips you chose as examples: used for learning')}
      {pair('Asked of you', c.active_pos, c.active_neg, 'Answers to the question Exemplar asked: used for learning')}
      {pair('Calibration', c.random_pos, c.random_neg, 'Random clips you labelled: these set the false-alarm guarantee')}
      <div className="flex items-center gap-2.5">
        <dt className="text-xs text-ex-ink3">Guarantee at α = {concept.alpha}</dt>
        <dd className="flex items-center gap-2">
          <progress className="sr-only" max={need} value={Math.min(have, need)} aria-label="Random negatives collected" />
          <span aria-hidden="true" className="h-1.5 w-20 overflow-hidden rounded-full bg-white/[0.1]">
            <span className={cx('block h-full rounded-full', ok ? 'bg-ex-pos' : 'bg-ex-warn')} style={{ width: `${Math.min(1, have / Math.max(1, need)) * 100}%` }} />
          </span>
          {ok ? (
            <span className="inline-flex items-center gap-1 text-xs text-ex-pos"><Icon name="check" className="h-3.5 w-3.5" /> {have} random negatives: enough</span>
          ) : (
            <span className="text-xs tabular-nums text-ex-ink2">{have} of {need} random negatives needed</span>
          )}
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
      headingRef.current?.focus()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const done = clips ? clips.filter((c) => answers[c.clip_id]).length : 0

  return (
    <section aria-labelledby="calib-h" className="rounded-xl border border-ex-line2 bg-ex-panel p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <p className="flex items-center gap-1.5 text-xs font-medium text-ex-warn"><Icon name="shuffle" className="h-3.5 w-3.5" /> Calibration</p>
          <h2 id="calib-h" ref={headingRef} tabIndex={-1} className="mt-1.5 text-md font-semibold tracking-tight focus:outline-none">
            Calibration labels: 10 random clips
          </h2>
          <p className="mt-1.5 text-sm text-ex-ink2">
            Does each clip show <strong className="font-medium text-ex-ink">“{concept.name}”</strong>? These clips were drawn uniformly at random from your history,
            and your answers set the false-alarm guarantee. That only works if the sample is random and honest, so answer every clip, including the
            hard ones. Clips you pick yourself elsewhere are used for learning only and are never counted here.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn" onClick={draw} disabled={busy}><Icon name="shuffle" /> Draw another 10</button>
          <button type="button" className="btn" onClick={onClose}><Icon name="check" /> Done</button>
        </div>
      </div>

      {error && <div className="mt-4"><Alert tone="neg" title="Could not save that label">{error}</Alert></div>}
      {!clips && (
        <div role="status" aria-label="Drawing a random sample" className="mt-5 grid gap-3 md:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[88px]" />)}
        </div>
      )}
      {clips && clips.length === 0 && !error && (
        <div className="mt-5"><Empty title="Nothing left to sample">Every clip with a trace already has a label for this concept.</Empty></div>
      )}
      {clips && clips.length > 0 && (
        <>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-ex-line pt-4">
            <p className="text-sm tabular-nums text-ex-ink2" role="status"><span className="font-medium text-ex-ink">{done}</span> of {clips.length} answered</p>
            <button type="button" className="btn btn-sm" onClick={allRestNegative} disabled={busy || done === clips.length}>
              <Icon name="minus" className="h-3.5 w-3.5" /> Mark all unanswered as not matching
            </button>
          </div>
          <ol className="mt-3 grid grid-cols-1 gap-x-8 md:grid-cols-2">
            {clips.map((c, i) => {
              const a = answers[c.clip_id]
              return (
                <li key={c.id} className="flex gap-3.5 border-b border-ex-line py-3">
                  <EventThumb event={c} className="h-[68px] w-[120px] shrink-0 rounded-md" />
                  <div className="min-w-0 flex-1">
                    <p className="line-clamp-2 text-sm text-ex-ink"><span className="mr-1.5 tabular-nums text-ex-ink3">{i + 1}.</span>{clipName(c)}</p>
                    <div role="group" aria-label={`Does clip ${i + 1} show ${concept.name}?`} className="mt-2 flex gap-1.5">
                      <button
                        type="button"
                        aria-pressed={a === 'pos'}
                        onClick={() => answer(c, 'pos')}
                        className={cx('btn btn-sm', a === 'pos' && '!border-ex-pos-line !bg-ex-pos-soft !text-ex-pos')}
                      >
                        <Icon name="check" className="h-3.5 w-3.5" /> Matches
                      </button>
                      <button
                        type="button"
                        aria-pressed={a === 'neg'}
                        onClick={() => answer(c, 'neg')}
                        className={cx('btn btn-sm', a === 'neg' && '!border-ex-neg-line !bg-ex-neg-soft !text-ex-neg')}
                      >
                        <Icon name="cross" className="h-3.5 w-3.5" /> Doesn’t match
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
      className="m-auto w-[min(560px,94vw)] rounded-xl border border-ex-line2 bg-ex-panel p-0 text-ex-ink shadow-2xl shadow-black/60"
    >
      <form onSubmit={submit} className="p-6">
        <h2 id="upload-h" className="text-md font-semibold tracking-tight">Upload footage</h2>
        <p className="mt-1.5 text-sm text-ex-ink2">
          Add third-party video (for example CC BY footage). It is cut into windows, each window becomes an <em>upload</em> event and is read by the model.
          Uploads never reach live monitors.
        </p>
        <div className="mt-5 grid gap-4">
          <div>
            <label className="field-label" htmlFor="up-file">Video file (MP4)</label>
            <input id="up-file" name="file" type="file" accept="video/mp4,video/*" required className="field h-auto py-1.5 file:mr-3 file:rounded file:border-0 file:bg-ex-hover file:px-3 file:py-1 file:text-sm file:text-ex-ink" />
          </div>
          <div>
            <label className="field-label" htmlFor="up-attr">Credit line (required)</label>
            <input id="up-attr" name="attribution" required className="field" placeholder={'"Thief stealing our package" by frollard, CC BY 4.0'} />
          </div>
          <div>
            <label className="field-label" htmlFor="up-url">Source URL (optional)</label>
            <input id="up-url" name="source_url" type="url" className="field" placeholder="https://www.youtube.com/watch?v=TfTFu8lGrwk" />
          </div>
          <div className="grid grid-cols-2 gap-4">
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
        {error && <div className="mt-4"><Alert tone="neg" title="Upload failed">{error}</Alert></div>}
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={() => ref.current?.close()}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={busy}><Icon name="upload" /> {busy ? 'Uploading…' : 'Upload and cut'}</button>
        </div>
      </form>
    </dialog>
  )
}

// ---------------------------------------------------------------------------------------------
function EventCard({
  ev, concept, selected, anySelected, onToggle, onOpen, onLabel,
}: {
  ev: EventSummary
  concept: Concept | null
  selected: boolean
  anySelected: boolean
  onToggle: () => void
  onOpen: () => void
  onLabel: (v: 'pos' | 'neg' | null) => void
}) {
  // A clip the engine cannot read (e.g. Bedrock is not set up) says why in plain language, in the summary slot.
  const unread = ev.trace_status === 'perception_failed' && !!ev.summary
  const title = ev.summary || (ev.trace_status === 'none' ? 'Waiting for the model to read this clip' : clipName(ev))
  const label = ev.label?.value ?? null
  const reveal = 'transition-opacity [@media(hover:none)]:opacity-100 group-hover:opacity-100 group-focus-within:opacity-100'
  return (
    <li className="group min-w-0">
      <div
        className={cx(
          'relative aspect-video overflow-hidden rounded-lg bg-ex-raised',
          selected && 'outline outline-2 outline-offset-2 outline-ex-accent-ink',
        )}
      >
        <button type="button" onClick={onOpen} aria-label={`View details: ${title}${ev.has_snapshot ? '' : ' (No snapshot)'}`} className="block h-full w-full rounded-none">
          <EventThumb event={ev} className="h-full w-full transition-transform duration-200 group-hover:scale-[1.02]" />
        </button>
        {/* Overlays stay on the bottom edge: Ring's watermark occupies the top-left and top-right of its frames. */}
        <span
          aria-hidden="true"
          className={cx(
            'pointer-events-none absolute inset-0 rounded-lg',
            label === 'pos' && 'shadow-[inset_0_0_0_2px_var(--ex-pos)]',
            label === 'neg' && 'shadow-[inset_0_0_0_2px_var(--ex-neg)]',
            !label && 'shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]',
          )}
        />
        <div className="pointer-events-none absolute inset-x-1.5 bottom-1.5 flex items-end justify-between gap-2">
          <SourceTag source={ev.source} />
          {ev.duration_ms != null && (
            <span aria-hidden="true" className="rounded bg-black/70 px-1.5 py-0.5 font-mono text-[11px] leading-none text-white">{fmtDuration(ev.duration_ms)}</span>
          )}
        </div>
      </div>

      <p className={cx('mt-2.5 text-sm leading-5', unread ? 'text-ex-warn' : 'line-clamp-2 min-h-[2.5rem] text-ex-ink')}>{title}</p>

      <div className="mt-1.5 flex min-h-[28px] items-center justify-between gap-2">
        <div className="min-w-0 truncate text-xs text-ex-ink3">
          {ev.trace_status !== 'ok' ? (
            <TraceStatusBadge event={ev} />
          ) : ev.label?.value ? (
            <LabelIndicator label={ev.label} />
          ) : ev.source === 'fixture' ? (
            'Fixture'
          ) : (
            <span title={new Date(ev.start_ms).toLocaleString()}>{fmtRelative(ev.start_ms)}</span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {concept && (
            <div className={cx(label ? 'opacity-100' : 'opacity-0', reveal)}>
              <LabelControl conceptName={concept.name} clipSummary={title} value={label} disabled={ev.trace_status !== 'ok'} onSet={onLabel} />
            </div>
          )}
          <label className={cx('grid h-7 w-7 cursor-pointer place-items-center rounded-md hover:bg-ex-hover', selected || anySelected ? 'opacity-100' : 'opacity-0', reveal)}>
            <input type="checkbox" className="h-4 w-4 accent-[#2A6BE0]" checked={selected} onChange={onToggle} aria-label={`Select: ${title}`} />
          </label>
        </div>
      </div>
    </li>
  )
}

function GroupSection({
  id, title, count, note, collapsed, onToggle, children,
}: { id: string; title: string; count: number; note?: React.ReactNode; collapsed: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`${id}-h`} className="pt-10 first:pt-6">
      <div className="mb-5 flex items-start gap-2">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-controls={`${id}-body`}
          aria-label={`${collapsed ? 'Show' : 'Hide'} ${title}`}
          className="btn-icon -ml-1.5 mt-px"
        >
          <Icon name="chevron" className={cx('h-4 w-4 transition-transform', collapsed && '-rotate-90')} />
        </button>
        <div className="min-w-0">
          <h2 id={`${id}-h`} className="flex items-baseline gap-2 text-md font-semibold leading-8 tracking-tight text-ex-ink">
            {title} <span className="text-sm font-normal tabular-nums text-ex-ink3">{count}</span>
          </h2>
          {note && <div className="text-xs text-ex-ink3">{note}</div>}
        </div>
      </div>
      <div id={`${id}-body`} hidden={collapsed}>{children}</div>
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
export default function LibraryScreen() {
  const { concept, conceptId, refreshConcepts, setConceptId, auth } = useApp()
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
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
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

  const groups = useMemo(() => {
    const m = new Map<GroupKey, EventSummary[]>()
    for (const e of shown) {
      const k = groupOf(e)
      m.set(k, [...(m.get(k) ?? []), e])
    }
    return GROUP_ORDER.filter((k) => m.has(k)).map((k) => ({ key: k, items: m.get(k)! }))
  }, [shown])

  const ringTitle = auth?.mode === 'oauth' ? 'Ring' : 'Ring Playground'
  const groupMeta = (key: GroupKey, list: EventSummary[]): { title: string; note?: React.ReactNode } => {
    if (key === 'ring') return { title: ringTitle, note: auth?.mode === 'oauth' ? 'Events from your linked Ring account.' : 'Simulated events from the Ring Developer Playground.' }
    if (key === 'upload') {
      const credits = Array.from(new Set(list.map((e) => e.attribution).filter((a): a is string => !!a)))
      return {
        title: 'Uploaded footage',
        note: credits.length > 0
          ? <>Cut into windows. {credits.map((c, i) => <span key={c} className="italic text-ex-ink2">{i > 0 && ' · '}{c}</span>)}</>
          : 'Cut into windows from footage you uploaded.',
      }
    }
    if (key === 'meva') return { title: 'MEVA', note: 'Real outdoor surveillance footage (CC BY 4.0) used for the evaluation runs.' }
    return { title: 'Fixtures', note: 'Built-in examples without a picture, drawn from what the model read in them: entities as rows, facts as ticks over time.' }
  }

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
      setNotice(value ? `Marked ${value === 'pos' ? 'positive' : 'negative'}: ${clipName(ev)}` : `Cleared label: ${clipName(ev)}`)
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
  const toggleGroup = (k: string) =>
    setCollapsed((s) => {
      const n = new Set(s)
      if (n.has(k)) n.delete(k)
      else n.add(k)
      return n
    })

  return (
    <>
      <PageHeader
        title="Library"
        subtitle="Every clip Exemplar has seen: Ring history, live captures and uploaded footage. Label a few as + or − for the concept you want to teach."
        actions={
          <>
            <button type="button" className="btn" onClick={sync} disabled={syncing}><Icon name="refresh" className={cx('h-4 w-4', syncing && 'motion-safe:animate-spin')} /> {syncing ? 'Syncing…' : 'Sync from Ring'}</button>
            <button type="button" className="btn" onClick={() => setUploadOpen(true)}><Icon name="upload" /> Upload footage</button>
            <Link href="/teach" className="btn btn-primary">Teach this concept <Icon name="arrow-right" /></Link>
          </>
        }
      />

      {/* One toolbar: concept, filters, search, bulk actions and selection. */}
      <div className="rounded-xl border border-ex-line bg-ex-panel">
        <div className="flex flex-wrap items-end gap-3 p-4">
          <ConceptSelect label="Label for concept" className="w-full sm:w-auto sm:min-w-[220px]" />
          <div className="w-[calc(50%-0.375rem)] sm:w-auto">
            <label htmlFor="f-source" className="field-label">Source</label>
            <select id="f-source" className="field sm:w-40" value={source} onChange={(e) => setSource(e.target.value)}>
              {SOURCES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="w-[calc(50%-0.375rem)] sm:w-auto">
            <label htmlFor="f-labelled" className="field-label">Label state</label>
            <select id="f-labelled" className="field sm:w-40" value={labelled} onChange={(e) => setLabelled(e.target.value)} disabled={!conceptId}>
              {LABELLED.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div className="min-w-[200px] flex-1">
            <label htmlFor="f-q" className="field-label">Search</label>
            <div className="relative">
              <Icon name="search" className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ex-ink3" />
              <input id="f-q" type="search" className="field pl-8" placeholder="Text in the description" value={query} onChange={(e) => setQuery(e.target.value)} />
            </div>
          </div>
        </div>
        {concept && (
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-t border-ex-line px-4 py-3">
            <ConceptSummary concept={concept} />
            <div className="flex flex-wrap items-center gap-2">
              {selected.size > 0 ? (
                <>
                  <span className="mr-1 text-sm tabular-nums text-ex-ink2" role="status"><span className="font-medium text-ex-ink">{selected.size}</span> selected</span>
                  <button type="button" className="btn btn-sm" onClick={bulkNegative} disabled={busy}>
                    <Icon name="minus" className="h-3.5 w-3.5" /> Mark {selected.size} selected as negative
                  </button>
                  <button type="button" className="btn-ghost btn-sm" onClick={() => setSelected(new Set())}>Clear selection</button>
                </>
              ) : (
                <>
                  <button type="button" className="btn btn-sm" onClick={() => setCalibrating(true)} disabled={calibrating}>
                    <Icon name="shuffle" className="h-3.5 w-3.5" /> Label 10 random (calibration)
                  </button>
                  <button type="button" className="btn-ghost btn-sm" onClick={() => setSelected(new Set(shown.filter((e) => e.trace_status === 'ok').map((e) => e.clip_id)))}>
                    Select all shown
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>

      {calibrating && concept && (
        <div className="mt-6">
          <CalibrationPanel
            concept={concept}
            onClose={() => { setCalibrating(false); load({ silent: true }) }}
            onChanged={() => refreshConcepts()}
          />
        </div>
      )}

      <div role="status" aria-live="polite" className="sr-only">{notice}</div>
      {error && (
        <div className="mt-6">
          <Alert tone="neg" title="The library could not be loaded" action={<button type="button" className="btn btn-sm" onClick={() => load()}>Try again</button>}>
            {error}
          </Alert>
        </div>
      )}

      {loading && items.length === 0 ? (
        <div role="status" aria-label="Loading the library" className="mt-10 grid grid-cols-1 gap-x-5 gap-y-8 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <div key={i} aria-hidden="true">
              <Skeleton className="aspect-video rounded-lg" />
              <Skeleton className="mt-3 h-4 w-11/12" />
              <Skeleton className="mt-2 h-4 w-2/3" />
            </div>
          ))}
        </div>
      ) : shown.length === 0 && error ? null : shown.length === 0 ? (
        <div className="mt-10">
          <Empty
            title="No clips match these filters"
            icon="search"
            action={<div className="flex gap-2"><button type="button" className="btn" onClick={sync} disabled={syncing}><Icon name="refresh" /> Sync from Ring</button><button type="button" className="btn" onClick={() => setUploadOpen(true)}><Icon name="upload" /> Upload footage</button></div>}
          >
            Try another source or label state, sync history from Ring, or upload some footage.
          </Empty>
        </div>
      ) : (
        <>
          <p className="mt-6 flex items-center gap-3 text-sm text-ex-ink3">
            <span><span className="tabular-nums text-ex-ink2">{shown.length}</span> clip{shown.length === 1 ? '' : 's'}</span>
            {pending && <Spinner label="Reading new clips…" />}
          </p>
          {groups.map((g) => {
            const meta = groupMeta(g.key, g.items)
            return (
              <GroupSection key={g.key} id={`grp-${g.key}`} title={meta.title} note={meta.note} count={g.items.length} collapsed={collapsed.has(g.key)} onToggle={() => toggleGroup(g.key)}>
                <ul className="grid grid-cols-1 gap-x-5 gap-y-8 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  {g.items.map((ev) => (
                    <EventCard
                      key={ev.id}
                      ev={ev}
                      concept={concept}
                      selected={selected.has(ev.clip_id)}
                      anySelected={selected.size > 0}
                      onToggle={() => toggle(ev.clip_id)}
                      onOpen={() => setOpenId(ev.id)}
                      onLabel={(v) => setLabel(ev, v)}
                    />
                  ))}
                </ul>
              </GroupSection>
            )
          })}
          {cursor && (
            <div className="mt-10 text-center">
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
