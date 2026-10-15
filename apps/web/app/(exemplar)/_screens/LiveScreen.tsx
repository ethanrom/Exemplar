'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { processorRegistry } from '@/lib/video-processors'
import { useVideoProcessing } from '@/lib/video-processors/useVideoProcessing'
import '@/lib/video-processors' // registers the built-in processors (and the Exemplar frame grabber when present)
import { useWebRTCStream } from '../../hooks/useWebRTCStream'
import { useApp } from '../_lib/app'
import { errorMessage, post } from '../_lib/api'
import { fmtClock, fmtInt, fmtNum, fmtUsd } from '../_lib/format'
import { useApi, useEventStream, useNow } from '../_lib/hooks'
import type { CostSummary, Device, Firing, LiveFact, MonitorEvent, MonitorEventType, RuleSummary } from '../_lib/types'
import { Icon } from '../_components/Icon'
import { RuleHeadline } from '../_components/RuleCard'
import { Alert, Badge, Empty, PageHeader, Spinner } from '../_components/ui'
import { WitnessTimeline } from '../_components/WitnessTimeline'

const MONITOR_TYPES: MonitorEventType[] = [
  'event_ingested', 'clip_ready', 'trace_ready', 'live_facts', 'rule_fired', 'rule_dropped',
  'escalated', 'action_result', 'cost_update', 'auth_expiring', 'error',
]
const FRAME_GRAB_ID = 'exemplar-frame-grab'
const FRESH_MS = 8000

interface TickerRow { key: number; at: number; facts: LiveFact[] }
interface RuleState { kind: 'fired' | 'dropped'; firing: Firing; at: number }
interface LogRow { key: string; at: number; rule?: string | null; action: string; status: 'ok' | 'skipped' | 'failed'; detail?: string | null }
interface Pipeline { event_id: string; label: string; clip: boolean; trace: boolean; at: number }

// ---------------------------------------------------------------------------------------------
function CostMeter({ cost }: { cost: CostSummary | null }) {
  const c = cost ?? { events: 0, stage0_dropped: 0, stage1_scored: 0, stage2_escalated: 0, tokens_in: 0, tokens_out: 0 }
  const max = Math.max(1, c.events)
  // Ordinal one-hue ramp (funnel stages), steps 250 to 550 of the blue ramp for the dark surface.
  const bars = [
    { label: 'Events seen', n: c.events, color: '#86b6ef', note: '' },
    { label: 'Dropped for free (stage 0)', n: c.stage0_dropped, color: '#5598e7', note: 'sub_type made the rule impossible' },
    { label: 'Scored on the fast model (stage 1)', n: c.stage1_scored, color: '#2a78d6', note: '' },
    { label: 'Escalated to the strong model (stage 2)', n: c.stage2_escalated, color: '#1c5cab', note: 'score within δ of τ' },
  ]
  return (
    <section className="card" aria-labelledby="cost-h">
      <h2 id="cost-h" className="card-title">Cost meter</h2>
      <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1">
        <p><span className="text-3xl font-semibold text-ex-ink">{fmtUsd(c.per_event_usd)}</span> <span className="text-sm text-ex-ink3">per event</span></p>
        <p className="text-sm text-ex-ink2">{fmtUsd(c.usd_estimate)} total · {fmtInt(c.tokens_in)} tokens in · {fmtInt(c.tokens_out)} out</p>
      </div>
      <ul className="mt-3 space-y-2.5" aria-label="Events by stage">
        {bars.map((b) => (
          <li key={b.label}>
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="text-ex-ink2">{b.label}</span>
              <span className="font-mono tabular-nums text-ex-ink">{b.n}</span>
            </div>
            <div className="mt-1 h-3 rounded-sm bg-ex-bg" aria-hidden="true">
              <div className="h-3 rounded-sm" style={{ width: `${(b.n / max) * 100}%`, background: b.color, minWidth: b.n ? 4 : 0 }} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
function MonitorCard({ ruleId, state, now }: { ruleId: string; state: RuleState | undefined; now: number }) {
  const rule = useApi<RuleSummary>(`/rules/${encodeURIComponent(ruleId)}`)
  const fresh = state?.kind === 'fired' && now - state.at < FRESH_MS
  const r = rule.data
  const tone = state?.kind === 'fired' ? 'border-green-400 bg-green-950/40' : 'border-ex-line bg-ex-panel'
  return (
    <article
      aria-label={r ? `Monitor: ${r.english}` : 'Monitor'}
      className={`rounded-xl border-2 p-3 transition-colors ${tone} ${fresh ? 'motion-safe:animate-ex-glow' : ''}`}
    >
      {!r ? <Spinner label="Loading rule" /> : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            {state?.kind === 'fired' ? (
              <Badge tone="pos" icon="bolt">{fresh ? 'FIRED' : 'Fired'}</Badge>
            ) : state?.kind === 'dropped' ? (
              <Badge tone="neutral" icon="minus">Dropped at stage {state.firing.stage}</Badge>
            ) : (
              <Badge tone="neutral" icon="eye">Watching</Badge>
            )}
            {state && <span className="text-xs text-ex-ink3">{fmtClock(state.at)}</span>}
            {state?.firing.score != null && (
              <span className="text-xs text-ex-ink2">
                score <span className="font-mono tabular-nums text-ex-ink">{fmtNum(state.firing.score)}</span>
                {state.firing.tau != null && <> vs τ <span className="font-mono tabular-nums text-ex-ink">{fmtNum(state.firing.tau)}</span></>}
              </span>
            )}
          </div>
          <div className="mt-2"><RuleHeadline rule={r} /></div>
          {state?.kind === 'fired' && state.firing.witness && (
            <div className="mt-3"><WitnessTimeline witness={state.firing.witness} compact /></div>
          )}
        </>
      )}
    </article>
  )
}

// ---------------------------------------------------------------------------------------------
export default function LiveScreen() {
  const { auth, concepts, isMock, refreshConcepts } = useApp()
  const now = useNow(1000)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const connected = !!auth?.connected
  const devices = useApi<Device[]>(connected ? '/ring/devices' : null)
  const deviceId = devices.data?.[0]?.id
  const { streamActive, streamError, startStream, stopStream } = useWebRTCStream({ videoRef: videoRef as React.RefObject<HTMLVideoElement>, deviceId })
  const { processors, toggleProcessor } = useVideoProcessing({
    video: videoRef.current,
    canvas: canvasRef.current,
    enabled: streamActive,
    fps: 2,
  })
  const grab = processors.find((p) => p.id === FRAME_GRAB_ID)
  // The frame grabber (stream A) needs the device id for its uploads. Discovered through the registry
  // so this screen builds with or without that processor being present.
  useEffect(() => {
    const p = processorRegistry.get(FRAME_GRAB_ID) as ({ configure?: (o: { deviceId?: string }) => void } & object) | undefined
    if (deviceId && typeof p?.configure === 'function') p.configure({ deviceId })
  }, [deviceId, grab])

  // ---- monitor stream state
  const [ticker, setTicker] = useState<TickerRow[]>([])
  const [paused, setPaused] = useState(false)
  const pausedRef = useRef(false)
  pausedRef.current = paused
  const lastFacts = useRef('')
  const tickKey = useRef(0)
  const [byRule, setByRule] = useState<Record<string, RuleState>>({})
  const [log, setLog] = useState<LogRow[]>([])
  const [pipe, setPipe] = useState<Pipeline | null>(null)
  const [expiring, setExpiring] = useState<string | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const cost = useApi<CostSummary>('/monitor/cost')
  const [liveCost, setLiveCost] = useState<CostSummary | null>(null)
  const firings = useApi<Firing[]>('/monitor/firings?limit=30')

  useEffect(() => { refreshConcepts() }, [refreshConcepts])

  // seed the monitor cards and the action log from history
  useEffect(() => {
    if (!firings.data) return
    setByRule((prev) => {
      const next = { ...prev }
      for (const f of [...firings.data!].reverse()) next[f.rule_id] = { kind: f.fired ? 'fired' : 'dropped', firing: f, at: f.created_at_ms }
      return next
    })
    setLog((prev) => {
      if (prev.length) return prev
      const rows: LogRow[] = []
      for (const f of firings.data!) for (const a of f.actions ?? []) rows.push({ key: `${f.id}:${a.action}`, at: f.created_at_ms, rule: f.rule_id, action: a.action, status: a.status, detail: a.detail })
      return rows.slice(0, 40)
    })
  }, [firings.data])

  const addLog = useCallback((f: Firing, at: number) => {
    setLog((prev) => {
      const rows = [...prev]
      for (const a of f.actions ?? []) {
        const key = `${f.id}:${a.action}`
        if (!rows.some((r) => r.key === key)) rows.unshift({ key, at, rule: f.rule_id, action: a.action, status: a.status, detail: a.detail })
      }
      return rows.slice(0, 40)
    })
  }, [])

  const streamStatus = useEventStream<MonitorEvent>('/monitor/stream', MONITOR_TYPES, (type, ev) => {
    const at = ev.at_ms || Date.now()
    switch (type) {
      case 'live_facts': {
        if (pausedRef.current) break
        const facts = ev.facts ?? []
        const sig = facts.map((f) => `${f.pred}(${f.args.join(',')})${f.conf}`).join('|')
        if (sig === lastFacts.current) break
        lastFacts.current = sig
        setTicker((prev) => [{ key: ++tickKey.current, at, facts }, ...prev].slice(0, 14))
        break
      }
      case 'event_ingested':
        setPipe({ event_id: ev.event_id ?? '', label: ev.message || 'New event', clip: false, trace: false, at })
        break
      case 'clip_ready':
        setPipe((p) => (p && p.event_id === ev.event_id ? { ...p, clip: true } : p))
        break
      case 'trace_ready':
        setPipe((p) => (p && p.event_id === ev.event_id ? { ...p, trace: true } : p))
        break
      case 'rule_fired':
      case 'rule_dropped':
        if (ev.firing && ev.rule_id) {
          setByRule((prev) => ({ ...prev, [ev.rule_id!]: { kind: type === 'rule_fired' ? 'fired' : 'dropped', firing: ev.firing!, at } }))
          if (type === 'rule_fired') addLog(ev.firing, at)
        }
        break
      case 'action_result':
        if (ev.firing) addLog(ev.firing, at)
        else if (ev.message) setLog((prev) => [{ key: `${at}:${ev.message}`, at, rule: ev.rule_id, action: ev.message!, status: 'ok' as const }, ...prev].slice(0, 40))
        break
      case 'cost_update':
        if (ev.cost) setLiveCost(ev.cost)
        break
      case 'auth_expiring':
        setExpiring(ev.message || 'The Playground token is about to expire.')
        break
      case 'error':
        setErrors((e) => [ev.message || 'The monitor reported an error.', ...e].slice(0, 3))
        break
      default:
    }
  })

  const deployedIds = useMemo(() => concepts.map((c) => c.deployed_rule_id).filter((x): x is string => !!x), [concepts])
  const shownCost = liveCost ?? cost.data ?? null

  // ---- mock helper (only when talking to the mock engine)
  const [mockKind, setMockKind] = useState('package')
  const [mockMsg, setMockMsg] = useState('')
  async function trigger() {
    try { await post(`/__mock/trigger?kind=${mockKind}`); setMockMsg(`Simulated a ${mockKind} event.`) } catch (e) { setMockMsg(errorMessage(e)) }
  }

  return (
    <>
      <PageHeader
        title="Live"
        subtitle="Your deployed rules watch new events as they arrive. When one fires you see why, and the cost of watching."
        actions={
          <Badge tone={streamStatus === 'open' ? 'pos' : streamStatus === 'reconnecting' ? 'warn' : 'neutral'} icon={streamStatus === 'open' ? 'check' : 'clock'}>
            Monitor {streamStatus === 'open' ? 'connected' : streamStatus === 'reconnecting' ? 'reconnecting' : streamStatus}
          </Badge>
        }
      />

      {(expiring || (auth?.expires_at_ms != null && auth.expires_at_ms - now < 5 * 60_000)) && (
        <div className="mb-4">
          <Alert tone="warn" title="The Playground token is about to expire">
            {expiring ?? 'Live events stop arriving when it does.'}{' '}
            <Link href="/connect" className="font-semibold underline">Paste a fresh token</Link>
          </Alert>
        </div>
      )}
      {errors.length > 0 && <div className="mb-4"><Alert tone="neg" title="Monitor error">{errors[0]}</Alert></div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        {/* ----------------------------------------------------------- video + ticker */}
        <div className="grid min-w-0 grid-cols-1 content-start gap-4">
          <section aria-labelledby="vid-h" className="card">
            <h2 id="vid-h" className="sr-only">Live view</h2>
            {/* Ring requires its watermark (logo top-left, device and time top-right) to stay visible: nothing is ever drawn over the video. */}
            <div className="relative aspect-video overflow-hidden rounded-lg bg-black">
              <video ref={videoRef} autoPlay playsInline muted className="h-full w-full object-contain" aria-label="Live view from the Ring camera" />
              <canvas ref={canvasRef} className="hidden" aria-hidden="true" />
              {!streamActive && (
                <div className="absolute inset-0 grid place-items-center">
                  <div className="text-center">
                    <button type="button" className="btn-primary !px-5 !py-2.5 text-base" onClick={startStream} disabled={!deviceId}>
                      <Icon name="play" /> {deviceId ? 'Start live view' : connected ? 'Finding the camera…' : 'Connect Ring first'}
                    </button>
                    {streamError && <p className="mt-2 max-w-sm text-sm text-red-300" role="alert">{streamError}</p>}
                    {!connected && <p className="mt-2 text-sm text-ex-ink2"><Link href="/connect" className="underline">Paste a Playground token</Link></p>}
                  </div>
                </div>
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {streamActive && <button type="button" className="btn-danger" onClick={stopStream}><Icon name="stop" /> Stop live view</button>}
              <label className={`flex items-center gap-2 text-sm ${grab ? 'cursor-pointer text-ex-ink' : 'text-ex-ink3'}`}>
                <input
                  type="checkbox"
                  role="switch"
                  className="h-4 w-4 accent-cyan-400"
                  checked={!!grab?.enabled}
                  disabled={!grab}
                  onChange={() => toggleProcessor(FRAME_GRAB_ID)}
                  aria-describedby="grab-help"
                />
                Send frames to Exemplar (about 2 per second)
              </label>
            </div>
            <p id="grab-help" className="mt-1 text-xs text-ex-ink3">
              {grab
                ? 'Frames are read from the video, turned into facts, and run through your deployed rules. Nothing is drawn over the picture.'
                : 'Frame capture is not registered in this build (the exemplar-frame-grab processor). Deployed rules still score Playground events as they land in history.'}
            </p>
            {isMock && (
              <details className="mt-3 rounded-lg border border-ex-line bg-ex-bg p-2 text-sm">
                <summary className="cursor-pointer rounded text-ex-info">Mock engine: simulate an event</summary>
                <div className="mt-2 flex flex-wrap items-end gap-2">
                  <div>
                    <label htmlFor="mock-kind" className="field-label">Event</label>
                    <select id="mock-kind" className="field" value={mockKind} onChange={(e) => setMockKind(e.target.value)}>
                      <option value="package">Playground: package</option>
                      <option value="vehicle">Playground: vehicle</option>
                      <option value="motion">Playground: motion (birds)</option>
                      <option value="human">Signed webhook: motion.human</option>
                    </select>
                  </div>
                  <button type="button" className="btn" onClick={trigger}>Simulate</button>
                  <span role="status" className="text-xs text-ex-ink2">{mockMsg}</span>
                </div>
              </details>
            )}
          </section>

          <section aria-labelledby="tick-h" className="card">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 id="tick-h" className="card-title">Live facts</h2>
              <button type="button" className="btn" aria-pressed={paused} onClick={() => setPaused(!paused)}>
                <Icon name={paused ? 'play' : 'pause'} /> {paused ? 'Resume ticker' : 'Pause ticker'}
              </button>
            </div>
            <p className="mt-1 text-xs text-ex-ink3">What the model currently sees, as predicates. Repeated frames are collapsed.</p>
            <div role="log" aria-live="polite" aria-relevant="additions" aria-atomic="false" aria-label="Live fact ticker" className="mt-3 max-h-64 overflow-y-auto" tabIndex={0}>
            <ol className="space-y-1.5">
              {ticker.length === 0 && <li className="text-sm text-ex-ink2">Waiting for facts…</li>}
              {ticker.map((row) => (
                <li key={row.key} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-md bg-ex-bg px-2 py-1.5 text-sm motion-safe:animate-ex-in">
                  <span className="font-mono text-xs tabular-nums text-ex-ink3">{fmtClock(row.at)}</span>
                  {row.facts.length === 0 ? (
                    <span className="text-ex-ink2">No entities in view</span>
                  ) : (
                    row.facts.map((f, i) => (
                      <span key={i} className="font-mono text-[13px] text-cyan-100">
                        {f.pred}({f.args.join(', ')}) <span className="text-xs text-ex-ink3">{f.conf}</span>
                      </span>
                    ))
                  )}
                </li>
              ))}
            </ol>
            </div>
          </section>
        </div>

        {/* ----------------------------------------------------------- monitors, log, cost */}
        <div className="grid min-w-0 grid-cols-1 content-start gap-4">
          <section aria-labelledby="mon-h" className="card">
            <h2 id="mon-h" className="card-title">Deployed rules</h2>
            {pipe && (
              <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ex-ink2">
                <span className="text-ex-ink">{pipe.label}</span>
                <Badge tone="pos" icon="check">ingested</Badge>
                <Badge tone={pipe.clip ? 'pos' : 'neutral'} icon={pipe.clip ? 'check' : 'clock'}>clip</Badge>
                <Badge tone={pipe.trace ? 'pos' : 'neutral'} icon={pipe.trace ? 'check' : 'clock'}>facts</Badge>
              </p>
            )}
            <div className="mt-3 grid gap-3">
              {deployedIds.length === 0 ? (
                <Empty title="No rule is deployed">Deploy a rule on the <Link className="underline" href="/rule">Rule</Link> screen and it will show up here.</Empty>
              ) : (
                deployedIds.map((id) => <MonitorCard key={id} ruleId={id} state={byRule[id]} now={now} />)
              )}
            </div>
          </section>

          <section aria-labelledby="log-h" className="card">
            <h2 id="log-h" className="card-title">Action log</h2>
            <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Action log" className="mt-3 max-h-56 overflow-y-auto" tabIndex={0}>
            <ol className="space-y-1.5">
              {log.length === 0 && <li className="text-sm text-ex-ink2">Nothing has fired yet.</li>}
              {log.map((r) => (
                <li key={r.key} className="flex items-start gap-2 rounded-md bg-ex-bg px-2 py-1.5 text-sm">
                  <Badge tone={r.status === 'ok' ? 'pos' : r.status === 'failed' ? 'neg' : 'neutral'} icon={r.status === 'ok' ? 'check' : r.status === 'failed' ? 'cross' : 'minus'}>{r.status}</Badge>
                  <span className="min-w-0 flex-1">
                    <span className="font-mono text-ex-ink">{r.action}</span>
                    {r.detail && <span className="text-ex-ink2"> · {r.detail}</span>}
                  </span>
                  <span className="font-mono text-xs tabular-nums text-ex-ink3">{fmtClock(r.at)}</span>
                </li>
              ))}
            </ol>
            </div>
          </section>

          <CostMeter cost={shownCost} />
        </div>
      </div>
    </>
  )
}
