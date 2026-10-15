'use client'

import { useEffect, useRef, useState } from 'react'
import { fmtDateTime, fmtDuration } from '../_lib/format'
import { useApi } from '../_lib/hooks'
import type { EventDetail } from '../_lib/types'
import { Icon } from './Icon'
import { clipUrl, KindBadges, snapshotUrl, SourceBadge, TraceStatusBadge } from './EventBits'
import { Alert, Spinner } from './ui'

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
      className="m-auto w-[min(920px,94vw)] max-h-[92vh] overflow-hidden rounded-xl border border-ex-line bg-ex-panel p-0 text-ex-ink backdrop:bg-black/70"
    >
      {eventId && (
        <div className="flex max-h-[92vh] flex-col">
          <div className="flex items-center justify-between gap-3 border-b border-ex-line px-4 py-3">
            <h2 id="event-dialog-title" className="min-w-0 truncate text-base font-semibold">
              {ev?.summary || 'Event details'}
            </h2>
            <button type="button" className="btn" onClick={() => ref.current?.close()}>
              <Icon name="cross" /> Close
            </button>
          </div>
          <div className="overflow-y-auto p-4">
            {detail.loading && !ev && <Spinner label="Loading event" />}
            {detail.error && <Alert tone="neg" title="Could not load this event">{detail.error.message}</Alert>}
            {ev && (
              <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
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
                      <p className="mt-1 text-xs text-ex-ink3">The clip is not available{ev.clip_status !== 'ready' ? ` yet (${ev.clip_status})` : ''}; showing the snapshot.</p>
                    </div>
                  ) : (
                    <Alert tone="warn" title="No clip or snapshot for this event" />
                  )}
                  <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                    <dt className="text-ex-ink3">Source</dt>
                    <dd className="flex flex-wrap items-center gap-1.5"><SourceBadge source={ev.source} /><KindBadges event={ev} /><TraceStatusBadge event={ev} /></dd>
                    <dt className="text-ex-ink3">When</dt>
                    <dd>{fmtDateTime(ev.start_ms)} · {fmtDuration(ev.duration_ms)}</dd>
                    {ev.attribution && (
                      <>
                        <dt className="text-ex-ink3">Credit</dt>
                        <dd>{ev.attribution}</dd>
                      </>
                    )}
                    {ev.trace?.perception && (
                      <>
                        <dt className="text-ex-ink3">Perception</dt>
                        <dd>
                          {ev.trace.perception.mode} model · {ev.trace.perception.n_frames} frames · {ev.trace.perception.tokens_in.toLocaleString()} in / {ev.trace.perception.tokens_out.toLocaleString()} out tokens
                        </dd>
                      </>
                    )}
                  </dl>
                </div>
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold">What the model saw</h3>
                  {ev.trace && ev.trace.status === 'ok' ? (
                    <>
                      <p className="mt-1 text-sm text-ex-ink2">{ev.trace.summary}</p>
                      <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Entities">
                        {ev.trace.entities.map((e) => (
                          <li key={e.id} className="chip"><span className="font-mono text-ex-ink">{e.id}</span> {e.type}{e.attrs?.length ? `: ${e.attrs.join(', ')}` : ''}</li>
                        ))}
                        {ev.trace.entities.length === 0 && <li className="text-sm text-ex-ink3">No entities detected.</li>}
                      </ul>
                      <details className="mt-3">
                        <summary className="cursor-pointer rounded text-sm font-medium text-ex-info">Symbolic trace ({ev.trace.frames.length} frames)</summary>
                        <pre className="code mt-2 max-h-72 overflow-auto text-xs">{ev.trace_text}</pre>
                      </details>
                    </>
                  ) : (
                    <p className="mt-1 text-sm text-ex-ink2">
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
