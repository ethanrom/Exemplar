'use client'

import { useEffect, useRef, useState } from 'react'
import { fmtDateTime, fmtDuration } from '../_lib/format'
import { useApi } from '../_lib/hooks'
import type { EventDetail } from '../_lib/types'
import { Icon } from './Icon'
import { clipUrl, KindBadges, snapshotUrl, SourceBadge, TraceStatusBadge, TraceStrip } from './EventBits'
import { Alert, IconButton, Skeleton } from './ui'

/** Modal (native <dialog>: focus trap, Esc to close, inert background) with the clip and its perceived facts. */
export function EventDialog({ eventId, onClose }: { eventId: string | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const detail = useApi<EventDetail>(eventId ? `/events/${encodeURIComponent(eventId)}` : null)
  const [clipError, setClipError] = useState(false)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (eventId && !d.open) d.showModal()
    if (!eventId && d.open) d.close()
    setClipError(false)
  }, [eventId])

  const ev = detail.data
  return (
    <dialog
      ref={ref}
      aria-labelledby="event-dialog-title"
      onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) ref.current?.close() }}
      className="m-auto w-[min(960px,94vw)] max-h-[92vh] overflow-hidden rounded-xl border border-ex-line2 bg-ex-panel p-0 text-ex-ink shadow-2xl shadow-black/60"
    >
      {eventId && (
        <div className="flex max-h-[92vh] flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-ex-line px-5 py-4">
            <div className="min-w-0">
              <p className="text-xs font-medium text-ex-ink3">Clip details</p>
              <h2 id="event-dialog-title" className="mt-0.5 line-clamp-2 text-md font-semibold leading-6 tracking-tight">
                {ev?.summary || 'Event details'}
              </h2>
            </div>
            <IconButton icon="cross" label="Close" onClick={() => ref.current?.close()} />
          </div>
          <div className="overflow-y-auto p-5">
            {detail.loading && !ev && (
              <div role="status" aria-label="Loading event" className="grid gap-4 md:grid-cols-2">
                <Skeleton className="aspect-video" />
                <div className="grid content-start gap-3"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-16" /></div>
              </div>
            )}
            {detail.error && <Alert tone="neg" title="Could not load this clip">{detail.error.message}</Alert>}
            {ev && (
              <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div>
                  {ev.clip_status === 'ready' && !clipError ? (
                    <video
                      key={ev.id}
                      controls
                      preload="metadata"
                      poster={ev.has_snapshot ? snapshotUrl(ev.id) : undefined}
                      onError={() => setClipError(true)}
                      aria-label={`Clip: ${ev.summary ?? ev.id}`}
                      className="aspect-video w-full rounded-lg bg-black"
                    >
                      <source src={clipUrl(ev.id)} type="video/mp4" />
                    </video>
                  ) : ev.has_snapshot ? (
                    <div>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={snapshotUrl(ev.id)} alt={ev.summary ?? 'Event snapshot'} className="aspect-video w-full rounded-lg bg-black object-cover" />
                      <p className="mt-1.5 text-xs text-ex-ink3">The clip is not available{ev.clip_status !== 'ready' ? ` yet (${ev.clip_status})` : ''}; showing the snapshot.</p>
                    </div>
                  ) : ev.trace?.status === 'ok' ? (
                    <div className="aspect-video overflow-hidden rounded-lg"><TraceStrip trace={ev.trace} /></div>
                  ) : (
                    <Alert tone="warn" title="No clip or snapshot for this event" />
                  )}
                  <dl className="mt-5 grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-2 text-sm">
                    <dt className="text-ex-ink3">Source</dt>
                    <dd className="flex flex-wrap items-center gap-x-2 gap-y-1"><SourceBadge source={ev.source} /><KindBadges event={ev} /><TraceStatusBadge event={ev} /></dd>
                    <dt className="text-ex-ink3">When</dt>
                    <dd className="text-ex-ink2">{ev.source === 'fixture' ? 'Fixture' : fmtDateTime(ev.start_ms)} · <span className="tabular-nums">{fmtDuration(ev.duration_ms)}</span></dd>
                    {ev.attribution && (
                      <>
                        <dt className="text-ex-ink3">Credit</dt>
                        <dd className="text-ex-ink2">{ev.attribution}</dd>
                      </>
                    )}
                    {ev.trace?.perception && (
                      <>
                        <dt className="text-ex-ink3">Perception</dt>
                        <dd className="text-ex-ink2">
                          {ev.trace.perception.mode} model · {ev.trace.perception.n_frames} frames · <span className="tabular-nums">{ev.trace.perception.tokens_in.toLocaleString()}</span> in / <span className="tabular-nums">{ev.trace.perception.tokens_out.toLocaleString()}</span> out tokens
                        </dd>
                      </>
                    )}
                  </dl>
                </div>
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-ex-ink">What the model saw</h3>
                  {ev.trace && ev.trace.status === 'ok' ? (
                    <>
                      <p className="mt-1.5 text-sm text-ex-ink2">{ev.trace.summary}</p>
                      <ul className="mt-4 divide-y divide-ex-line rounded-lg border border-ex-line" aria-label="Entities">
                        {ev.trace.entities.map((e) => (
                          <li key={e.id} className="flex items-baseline gap-3 px-3 py-2 text-sm">
                            <span className="w-8 shrink-0 font-mono text-xs text-ex-ink">{e.id}</span>
                            <span className="text-ex-ink2">{e.type}</span>
                            {e.attrs?.length ? <span className="min-w-0 truncate text-xs text-ex-ink3">{e.attrs.join(', ')}</span> : null}
                          </li>
                        ))}
                        {ev.trace.entities.length === 0 && <li className="px-3 py-2 text-sm text-ex-ink3">No entities detected.</li>}
                      </ul>
                      {ev.trace.entities.length > 0 && (
                        <div className="mt-3">
                          <p className="mb-1.5 text-xs text-ex-ink3">Facts over {fmtDuration(ev.trace.duration_ms)}</p>
                          <div className="h-[84px] overflow-hidden rounded-lg"><TraceStrip trace={ev.trace} /></div>
                        </div>
                      )}
                      <details className="group mt-4">
                        <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded text-sm font-medium text-ex-accent-ink [&::-webkit-details-marker]:hidden">
                          <Icon name="chevron-right" className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                          Symbolic trace ({ev.trace.frames.length} frames)
                        </summary>
                        <pre className="code mt-2 max-h-72 overflow-auto text-xs leading-5">{ev.trace_text}</pre>
                      </details>
                    </>
                  ) : (
                    <p className="mt-1.5 text-sm text-ex-ink2">
                      {ev.trace_status === 'perception_failed' ? ev.trace?.error || 'Perception failed for this clip, so it is excluded from learning and backtests.' : 'No trace yet.'}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </dialog>
  )
}
