'use client'

import { useMemo, useState } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Card } from '@/components/Card.tsx'
import { cx } from '@/components/cx.ts'
import { Stat, StatStrip } from '@/components/Stat.tsx'
import { LiveRegion } from '@/components/lab/Announce.tsx'
import { DV } from '@/components/lab/DataValue.tsx'
import { FrameCell } from '@/components/lab/FrameCell.tsx'
import { Slider } from '@/components/lab/Slider.tsx'
import type { ClipCard, TraceJson } from '@/lib/data/types.ts'

type Conf = 'low' | 'med' | 'high'
const CONF_TONE: Record<Conf, 'pos' | 'warn' | 'neutral'> = { high: 'pos', med: 'warn', low: 'neutral' }
const CONF_FILL: Record<Conf, string> = { high: 'bg-ex-pos', med: 'bg-ex-pos/55', low: 'bg-ex-pos/25' }

const factText = (f: { pred: string; args: string[] }) => `${f.pred}(${f.args.join(', ')})`

/** Chapter 1: the 16 frames Claude read for one recorded event, each with the facts it wrote down. */
export function Chapter1({ card, trace, eventNumber }: { card: ClipCard; trace: TraceJson; eventNumber: number }) {
  const T = trace.frames.length
  const [i, setI] = useState(0)
  const frame = trace.frames[i] as TraceJson['frames'][number]
  const secs = (frame.t_ms / 1000).toFixed(1)
  const entity = (id: string) => trace.entities.find((e) => e.id === id)

  // One lane per distinct fact, with its confidence at each frame.
  const lanes = useMemo(() => {
    const m = new Map<string, { text: string; conf: (Conf | null)[] }>()
    trace.frames.forEach((f, k) => {
      for (const fact of f.facts) {
        const key = factText(fact)
        if (!m.has(key)) m.set(key, { text: key, conf: new Array<Conf | null>(T).fill(null) })
        ;(m.get(key) as { conf: (Conf | null)[] }).conf[k] = fact.conf
      }
    })
    return [...m.values()]
  }, [trace, T])

  const p = trace.perception
  const frameLabel = (k: number) => `Frame ${k + 1} of ${T}, at ${((trace.frames[k] as { t_ms: number }).t_ms / 1000).toFixed(1)} seconds`

  return (
    <div data-src={`data/traces/${card.alias}.json`} className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
        <div>
          <div className="mx-auto max-w-[520px]">
            <FrameCell sheet={card.sheet} index={i} label={frameLabel(i)} />
            <p className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-3 text-xs text-ex-ink2">
              <span>{card.title}</span>
              <span className="font-mono tabular-nums">frame {i + 1} of {T} · {secs} s</span>
            </p>
          </div>
          <div className="mx-auto mt-4 max-w-[520px]">
            <Slider
              label="Scrub through the frames"
              value={i}
              min={0}
              max={T - 1}
              step={1}
              pageStep={4}
              onChange={setI}
              valueText={(v) => `frame ${v + 1} of ${T}, at ${((trace.frames[v] as { t_ms: number }).t_ms / 1000).toFixed(1)} seconds`}
              display={`${i + 1} / ${T}`}
              hint="Arrow keys step one frame, Page Up and Page Down step four."
            />
          </div>
          <ul className="mt-4 grid grid-cols-4 gap-1.5 sm:grid-cols-8" aria-label="All sampled frames">
            {trace.frames.map((f, k) => (
              <li key={f.t_ms}>
                <button
                  type="button"
                  tabIndex={-1}
                  aria-pressed={k === i}
                  onClick={() => setI(k)}
                  className={cx('block w-full rounded-md p-0.5 text-center', k === i ? 'bg-ex-accent-soft ring-2 ring-ex-accent-ink' : 'hover:bg-ex-hover')}
                >
                  <FrameCell sheet={card.sheet} index={k} label="" decorative className="border-0" />
                  <span className="mt-0.5 block font-mono text-[11px] tabular-nums text-ex-ink3"><span className="sr-only">Show frame {k + 1} at </span>{(f.t_ms / 1000).toFixed(1)} s</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="space-y-4">
          <Card padding="sm">
            <h3 className="text-sm font-semibold text-ex-ink">Facts Claude wrote for this frame</h3>
            {frame.facts.length === 0 ? (
              <p className="mt-2 text-sm text-ex-ink2">No facts in this frame.</p>
            ) : (
              <ul className="mt-2 divide-y divide-ex-line">
                {frame.facts.map((f) => {
                  const ent = entity(f.args[0] as string)
                  return (
                    <li key={factText(f)} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2">
                      <div className="min-w-0">
                        <code className="font-mono text-sm text-ex-ink">{factText(f)}</code>
                        {ent && <p className="text-xs text-ex-ink3">{ent.id} is a {ent.type}{ent.attrs.length ? ` (${ent.attrs.join(', ').replaceAll('_', ' ')})` : ''}</p>}
                      </div>
                      <Badge tone={CONF_TONE[f.conf]} icon={f.conf === 'high' ? 'check' : f.conf === 'med' ? 'dot' : 'minus'}>confidence: {f.conf}</Badge>
                    </li>
                  )
                })}
              </ul>
            )}
            <p className="mt-2 text-xs text-ex-ink3">
              A fact is a predicate about an entity (<code className="font-mono">in_zone</code>, <code className="font-mono">enters</code>, <code className="font-mono">picks_up</code>…) with a confidence of low, med or high. These facts, not pixels, are all the later steps see.
            </p>
          </Card>

          <Card padding="sm">
            <h3 className="text-sm font-semibold text-ex-ink">Claude’s one-line summary of the clip</h3>
            <p className="mt-1.5 text-sm text-ex-ink2">{trace.summary}</p>
          </Card>
        </div>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ex-ink">The same facts across all {T} frames</h3>
        <div className="overflow-x-auto rounded-lg border border-ex-line bg-ex-bg p-3" role="region" tabIndex={0} aria-label="Facts across frames (scrolls sideways on narrow screens)">
          <table className="w-full min-w-[520px] border-separate border-spacing-y-1 text-xs">
            <caption className="sr-only">Confidence of each fact at each sampled frame. Filled cells are present; the shade is the confidence.</caption>
            <thead>
              <tr>
                <th scope="col" className="w-[38%] pr-3 text-left font-medium text-ex-ink3">Fact</th>
                <th scope="col" className="text-left font-medium text-ex-ink3"><span className="sr-only">Frames 1 to {T}</span><span aria-hidden="true">frame 1 → {T}</span></th>
              </tr>
            </thead>
            <tbody>
              {lanes.map((l) => (
                <tr key={l.text}>
                  <th scope="row" className="pr-3 text-left font-normal"><code className="break-all font-mono text-ex-ink">{l.text}</code></th>
                  <td>
                    <div className="flex gap-0.5">
                      {l.conf.map((c, k) => (
                        <button
                          key={k}
                          type="button"
                          tabIndex={-1}
                          onClick={() => setI(k)}
                          aria-label={`${l.text} at frame ${k + 1}: ${c ?? 'not present'}`}
                          className={cx('h-5 flex-1 rounded-sm border', c ? `${CONF_FILL[c]} border-transparent` : 'border-ex-line2', k === i && 'ring-2 ring-ex-ink')}
                        />
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ex-ink3">
            <span className="inline-flex items-center gap-1.5"><span className={cx('h-3 w-5 rounded-sm', CONF_FILL.high)} />high</span>
            <span className="inline-flex items-center gap-1.5"><span className={cx('h-3 w-5 rounded-sm', CONF_FILL.med)} />med</span>
            <span className="inline-flex items-center gap-1.5"><span className={cx('h-3 w-5 rounded-sm', CONF_FILL.low)} />low</span>
            <span className="inline-flex items-center gap-1.5"><span className="h-3 w-5 rounded-sm border border-ex-line2" />not seen</span>
          </p>
        </div>
      </div>

      {p && (
        <StatStrip label="What the one perception call cost" cols="grid-cols-2 sm:grid-cols-4">
          <Stat label="Frames read" value={<DV src={`traces/${card.alias}.json#perception.n_frames`}>{p.n_frames}</DV>} hint="in one model call" />
          <Stat label="Samples" value={<DV src={`traces/${card.alias}.json#perception.samples`}>{p.samples}</DV>} hint={`${p.mode} model: each frame set read once`} />
          <Stat label="Tokens in / out" value={<DV src={`traces/${card.alias}.json#perception`}>{p.tokens_in.toLocaleString('en-US')} / {p.tokens_out.toLocaleString('en-US')}</DV>} hint="as recorded" />
          <Stat label="Model time" value={<DV src={`traces/${card.alias}.json#perception.latency_ms`}>{(p.latency_ms / 1000).toFixed(1)} s</DV>} hint="recorded latency" />
        </StatStrip>
      )}
      <p className="text-sm text-ex-ink2">
        This is recorded event {eventNumber} of the 5 in the live run on the Ring Developer Playground. Claude on Amazon Bedrock wrote these facts once, when the clip arrived. Every rule is then scored on these facts alone, which is why checking a new rule costs no model call.
      </p>
      <LiveRegion text={`${frameLabel(i)}: ${frame.facts.length} fact${frame.facts.length === 1 ? '' : 's'}.`} />
    </div>
  )
}
