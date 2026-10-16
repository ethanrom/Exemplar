'use client'

import Link from 'next/link'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { processorRegistry } from '@/lib/video-processors'
import { useVideoProcessing } from '@/lib/video-processors/useVideoProcessing'
import '@/lib/video-processors' // registers the built-in processors (and the Exemplar frame grabber when present)
import { useWebRTCStream } from '../../hooks/useWebRTCStream'
import { useApp } from '../_lib/app'
import { errorMessage, get, post } from '../_lib/api'
import { fmtClock, fmtInt, fmtNum, fmtUsd, hideDeviceIds, keepUnits } from '../_lib/format'
import { useApi, useEventStream, useNow } from '../_lib/hooks'
import type { CostSummary, Device, EventDetail, Firing, LiveFact, MonitorEvent, MonitorEventType, RuleSummary } from '../_lib/types'
import { Dsl, DslBlock } from '../_components/Dsl'
import { EventThumb } from '../_components/EventBits'
import { Icon } from '../_components/Icon'
import { Alert, Badge, Empty, PageHeader, Skeleton, StatusDot, Switch, cx } from '../_components/ui'
import { WitnessTimeline } from '../_components/WitnessTimeline'

const MONITOR_TYPES: MonitorEventType[] = [
  'event_ingested', 'clip_ready', 'trace_ready', 'live_facts', 'rule_fired', 'rule_dropped',
  'escalated', 'action_result', 'cost_update', 'auth_expiring', 'error',
]
const ACTION_TEXT: Record<string, string> = {
  ui: 'Notification shown in Exemplar',
  webhook_out: 'Webhook sent',
  slack: 'Posted to Slack',
  chime: 'Chime played on the camera',
}
const FRAME_GRAB_ID = 'exemplar-frame-grab'
const FRESH_MS = 8000
const FEED_MAX = 8

interface TickerRow { key: number; at: number; facts: LiveFact[] }
interface RuleState { kind: 'fired' | 'dropped'; firing: Firing; at: number }
interface LogRow { key: string; at: number; rule?: string | null; action: string; status: 'ok' | 'skipped' | 'failed'; detail?: string | null }
interface Outcome { kind: 'fired' | 'dropped'; stage: number; score?: number | null }
interface FeedItem { event_id: string; at: number; label?: string; clip: boolean; trace: boolean; escalated: boolean; outcomes: Record<string, Outcome> }

// ---------------------------------------------------------------------------------------------
/** The cost of watching, as a quiet row of figures rather than a dashboard. */
function CostRow({ cost }: { cost: CostSummary | null }) {
  const c = cost ?? { events: 0, stage0_dropped: 0, stage1_scored: 0, stage2_escalated: 0, tokens_in: 0, tokens_out: 0 }
  const share = (n: number) => (c.events > 0 ? `${Math.round((n / c.events) * 100)}% of events` : 'of events')
  const cell = (label: string, value: React.ReactNode, hint?: React.ReactNode, key?: string) => (
    <div key={key ?? label} className="min-w-0 bg-ex-panel px-4 py-3.5 last:col-span-2 sm:last:col-span-1">
      <dt className="text-xs text-ex-ink3">{label}</dt>
      <dd className="mt-1 text-xl font-semibold tracking-tight tabular-nums text-ex-ink">{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ex-ink3">{hint}</dd>}
    </div>
  )
  return (
    <section aria-label="Cost of watching">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-ex-line bg-ex-line sm:grid-cols-5">
        {cell('Events seen', fmtInt(c.events), <>{fmtInt(c.tokens_in)} tokens in · {fmtInt(c.tokens_out)} out</>)}
        {cell('Dropped free', fmtInt(c.stage0_dropped), <>stage 0 · {share(c.stage0_dropped)}</>)}
        {cell('Scored', fmtInt(c.stage1_scored), <>stage 1, fast model</>)}
        {cell('Escalated', fmtInt(c.stage2_escalated), <>stage 2 · within δ of τ</>)}
        {cell('Cost per event', fmtUsd(c.per_event_usd), <>{fmtUsd(c.usd_estimate)} total</>)}
      </dl>
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
function MonitorCard({ rule, state, now }: { rule: RuleSummary | undefined; state: RuleState | undefined; now: number }) {
  const fresh = state?.kind === 'fired' && now - state.at < FRESH_MS
  const fired = state?.kind === 'fired'
  return (
    <article
      aria-label={rule ? `Monitor: ${rule.english}` : 'Monitor'}
      className={cx(
        'rounded-xl border p-4 transition-colors sm:p-5',
        fired ? 'border-ex-pos-line bg-ex-pos-soft' : 'border-ex-line bg-ex-panel',
        fresh && 'motion-safe:animate-ex-glow',
      )}
    >
      {!rule ? (
        <div role="status" aria-label="Loading rule" className="grid gap-2"><Skeleton className="h-4 w-1/3" /><Skeleton className="h-10" /></div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            {fired ? (
              <Badge tone="pos" icon="bolt">{fresh ? 'Fired just now' : 'Fired'}</Badge>
            ) : state?.kind === 'dropped' ? (
              <Badge tone="neutral" icon="minus">Dropped at stage {state.firing.stage}</Badge>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ex-ink2"><StatusDot tone="info" pulse>Watching</StatusDot></span>
            )}
            {state && <span className="font-mono text-xs tabular-nums text-ex-ink3">{fmtClock(state.at)}</span>}
            {state?.firing.score != null && (
              <span className="font-mono text-xs tabular-nums text-ex-ink2">
                <span className="font-sans text-ex-ink3">score</span> {fmtNum(state.firing.score)}
                {state.firing.tau != null && <> <span className="font-sans text-ex-ink3">vs τ</span> {fmtNum(state.firing.tau)}</>}
              </span>
            )}
          </div>
          <p className="mt-3 text-pretty text-base font-medium leading-snug text-ex-ink">{keepUnits(rule.english)}</p>
          <DslBlock text={rule.dsl_text} size="sm" className="mt-3" />
          {state?.kind === 'fired' && state.firing.witness && (
            <div className="mt-4"><WitnessTimeline witness={state.firing.witness} compact /></div>
          )}
        </>
      )}
    </article>
  )
}

// ---------------------------------------------------------------------------------------------
function Stage({ done, label }: { done: boolean; label: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1 text-xs', done ? 'text-ex-ink2' : 'text-ex-ink3')}>
      <Icon name={done ? 'check' : 'clock'} className={cx('h-3 w-3', done && 'text-ex-pos')} />
      {label}
    </span>
  )
}

/** One event on its way through the funnel: ingested, clip, facts, then what each rule decided. */
function FeedRow({ item, rules, deployed }: { item: FeedItem; rules: Record<string, RuleSummary>; deployed: string[] }) {
  const detail = useApi<EventDetail>(`/events/${encodeURIComponent(item.event_id)}`)
  const ev = detail.data
  const title = ev?.summary || item.label || 'New event'
  const outcomes = deployed.filter((id) => item.outcomes[id]).map((id) => ({ id, o: item.outcomes[id] }))
  const short = (s?: string) => (s ? (s.length > 44 ? `${s.slice(0, 42)}…` : s) : 'rule')
  return (
    <li className="flex gap-3 py-3.5 motion-safe:animate-ex-in">
      {ev ? (
        <EventThumb event={ev} compact className="h-[42px] w-[75px] shrink-0 rounded-md" />
      ) : (
        <Skeleton className="h-[42px] w-[75px] shrink-0" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-3">
          <p className="line-clamp-2 text-sm leading-5 text-ex-ink">{title}</p>
          <span className="shrink-0 font-mono text-xs tabular-nums text-ex-ink3">{fmtClock(item.at)}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          <Stage done label="Ingested" />
          <Stage done={item.clip} label="Clip" />
          <Stage done={item.trace} label="Facts" />
          {item.escalated && <span className="inline-flex items-center gap-1 text-xs text-ex-accent-ink"><Icon name="spark" className="h-3 w-3" />Escalated</span>}
        </div>
        {outcomes.length > 0 && (
          <ul className="mt-1.5 grid gap-0.5">
            {outcomes.map(({ id, o }) => (
              <li key={id} className="flex items-center gap-1.5 text-xs">
                {o.kind === 'fired' ? (
                  <span className="inline-flex shrink-0 items-center gap-1 font-medium text-ex-pos"><Icon name="bolt" className="h-3 w-3" />Fired</span>
                ) : (
                  <span className="inline-flex shrink-0 items-center gap-1 text-ex-ink3"><Icon name="minus" className="h-3 w-3" />Dropped at stage {o.stage}</span>
                )}
                <span className="min-w-0 truncate text-ex-ink3" title={rules[id]?.english}>{short(rules[id]?.english)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
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
  // The frame grabber needs the device id for its uploads. Discovered through the registry
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
  const [feed, setFeed] = useState<FeedItem[]>([])
  const [expiring, setExpiring] = useState<string | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const cost = useApi<CostSummary>('/monitor/cost')
  const reloadCost = cost.reload
  const firings = useApi<Firing[]>('/monitor/firings?limit=30')

  useEffect(() => { refreshConcepts() }, [refreshConcepts])

  const touchFeed = useCallback((eventId: string | null | undefined, at: number, patch: (i: FeedItem) => FeedItem) => {
    if (!eventId) return
    setFeed((prev) => {
      const i = prev.findIndex((f) => f.event_id === eventId)
      const base: FeedItem = i >= 0 ? prev[i] : { event_id: eventId, at, clip: false, trace: false, escalated: false, outcomes: {} }
      const next = patch(base)
      const rest = i >= 0 ? prev.filter((_, j) => j !== i) : prev
      return [next, ...rest].sort((a, b) => b.at - a.at).slice(0, FEED_MAX)
    })
  }, [])

  // seed the monitor cards, the feed and the action log from history
  useEffect(() => {
    if (!firings.data) return
    setByRule((prev) => {
      const next = { ...prev }
      for (const f of [...firings.data!].reverse()) next[f.rule_id] = { kind: f.fired ? 'fired' : 'dropped', firing: f, at: f.created_at_ms }
      return next
    })
    setFeed((prev) => {
      if (prev.length) return prev
      const m = new Map<string, FeedItem>()
      for (const f of firings.data!) {
        const it = m.get(f.event_id) ?? { event_id: f.event_id, at: f.created_at_ms, clip: true, trace: true, escalated: false, outcomes: {} }
        it.at = Math.max(it.at, f.created_at_ms)
        it.escalated = it.escalated || f.stage === 2
        it.outcomes[f.rule_id] = { kind: f.fired ? 'fired' : 'dropped', stage: f.stage, score: f.score }
        m.set(f.event_id, it)
      }
      return Array.from(m.values()).sort((a, b) => b.at - a.at).slice(0, FEED_MAX)
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

  const streamStatus = useEventStream<MonitorEvent>('/monitor/stream', MONITOR_TYPES, (type, raw) => {
    const at = raw.at_ms || Date.now()
    const ev = raw.message ? { ...raw, message: hideDeviceIds(raw.message) } : raw
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
        touchFeed(ev.event_id, at, (i) => ({ ...i, at, label: ev.message || i.label }))
        break
      case 'clip_ready':
        touchFeed(ev.event_id, at, (i) => ({ ...i, clip: true }))
        break
      case 'trace_ready':
        touchFeed(ev.event_id, at, (i) => ({ ...i, clip: true, trace: true }))
        break
      case 'escalated':
        touchFeed(ev.event_id, at, (i) => ({ ...i, escalated: true }))
        break
      case 'rule_fired':
      case 'rule_dropped':
        if (ev.firing && ev.rule_id) {
          const f = ev.firing
          setByRule((prev) => ({ ...prev, [ev.rule_id!]: { kind: type === 'rule_fired' ? 'fired' : 'dropped', firing: f, at } }))
          touchFeed(ev.event_id ?? f.event_id, at, (i) => ({
            ...i, clip: true, trace: true, escalated: i.escalated || f.stage === 2,
            outcomes: { ...i.outcomes, [ev.rule_id!]: { kind: type === 'rule_fired' ? 'fired' : 'dropped', stage: f.stage, score: f.score } },
          }))
          if (type === 'rule_fired') addLog(f, at)
        }
        break
      case 'action_result':
        if (ev.firing) addLog(ev.firing, at)
        else if (ev.message) setLog((prev) => [{ key: `${at}:${ev.message}`, at, rule: ev.rule_id, action: ev.message!, status: 'ok' as const }, ...prev].slice(0, 40))
        break
      case 'cost_update':
        // Re-read the figures from the API instead of trusting the event payload; the last value stays on screen until the new one lands.
        reloadCost()
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
  const [ruleMap, setRuleMap] = useState<Record<string, RuleSummary>>({})
  const idsKey = deployedIds.join(',')
  useEffect(() => {
    let alive = true
    for (const id of deployedIds) {
      get<RuleSummary>(`/rules/${encodeURIComponent(id)}`).then((r) => { if (alive) setRuleMap((m) => ({ ...m, [id]: r })) }).catch(() => undefined)
    }
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey])
  const shownCost = cost.data

  // ---- mock helper (only when talking to the mock engine)
  const [mockKind, setMockKind] = useState('package')
  const [mockMsg, setMockMsg] = useState('')
  async function trigger() {
    try { await post(`/__mock/trigger?kind=${mockKind}`); setMockMsg(`Simulated a ${mockKind} event.`) } catch (e) { setMockMsg(errorMessage(e)) }
  }

  const tokenExpired = auth?.expires_at_ms != null && auth.expires_at_ms <= now
  const monitorTone = streamStatus === 'open' ? 'pos' : streamStatus === 'reconnecting' ? 'warn' : 'neutral'

  return (
    <>
      <PageHeader
        title="Live"
        subtitle="Your deployed rules watch new events as they arrive. When one fires you see why, and the cost of watching."
        actions={
          <span className="inline-flex h-8 items-center rounded-md border border-ex-line px-3 text-xs text-ex-ink2">
            <StatusDot tone={monitorTone} pulse={streamStatus === 'reconnecting'}>
              Monitor {streamStatus === 'open' ? 'connected' : streamStatus === 'reconnecting' ? 'reconnecting' : streamStatus}
            </StatusDot>
          </span>
        }
      />

      {(expiring || (auth?.expires_at_ms != null && auth.expires_at_ms - now < 5 * 60_000)) && (
        <div className="mb-6">
          <Alert
            tone={tokenExpired ? 'neg' : 'warn'}
            title={tokenExpired ? 'The Playground token has expired' : 'The Playground token is about to expire'}
            action={<Link href="/connect" className="btn btn-sm">Paste a fresh token</Link>}
          >
            {tokenExpired ? 'New events stopped arriving. Paste a fresh token to start watching again.' : (expiring ?? 'Live events stop arriving when it does.')}
          </Alert>
        </div>
      )}
      {errors.length > 0 && <div className="mb-6"><Alert tone="neg" title="Monitor error">{errors[0]}</Alert></div>}

      <CostRow cost={shownCost} />

      <div className="mt-10 grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] xl:gap-12">
        {/* ----------------------------------------------------------- video + ticker */}
        <div className="grid min-w-0 grid-cols-1 content-start gap-10">
          <section aria-labelledby="vid-h">
            <h2 id="vid-h" className="sr-only">Live view</h2>
            {/* Ring requires its watermark (logo top-left, device and time top-right) to stay visible: nothing is ever drawn over the video. */}
            <div className="relative aspect-video overflow-hidden rounded-xl bg-black shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]">
              <video ref={videoRef} autoPlay playsInline muted className="h-full w-full object-contain" aria-label="Live view from the Ring camera" />
              <canvas ref={canvasRef} className="hidden" aria-hidden="true" />
              {!streamActive && (
                <div className="absolute inset-0 grid place-items-center">
                  <div className="flex flex-col items-center text-center">
                    <span aria-hidden="true" className="grid h-11 w-11 place-items-center rounded-full border border-ex-line2 text-ex-ink2"><Icon name="camera" className="h-5 w-5" /></span>
                    <p className="mt-3 text-sm text-ex-ink2">{connected ? 'Live view is off' : 'Ring is not connected'}</p>
                    <button type="button" className="btn btn-primary btn-lg mt-4" onClick={startStream} disabled={!deviceId}>
                      <Icon name="play" /> {deviceId ? 'Start live view' : connected ? 'Finding the camera…' : 'Connect Ring first'}
                    </button>
                    {streamError && <p className="mt-3 max-w-sm text-sm text-ex-neg" role="alert">{streamError}</p>}
                    {!connected && <p className="mt-3 text-sm text-ex-ink2"><Link href="/connect" className="link">Paste a Playground token</Link></p>}
                  </div>
                </div>
              )}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3">
              {streamActive && <button type="button" className="btn btn-danger" onClick={stopStream}><Icon name="stop" /> Stop live view</button>}
              <div className={cx('flex items-center gap-3 text-sm', grab ? 'text-ex-ink' : 'text-ex-ink3')}>
                <Switch checked={!!grab?.enabled} onChange={() => toggleProcessor(FRAME_GRAB_ID)} labelledBy="grab-label" disabled={!grab} describedBy="grab-help" />
                <span id="grab-label">Send frames to Exemplar (about 2 per second)</span>
              </div>
            </div>
            <p id="grab-help" className="mt-1.5 text-xs text-ex-ink3">
              {grab
                ? 'Frames are read from the video, turned into facts, and run through your deployed rules. Nothing is drawn over the picture.'
                : 'Frame capture is not registered in this build (the exemplar-frame-grab processor). Deployed rules still score Playground events as they land in history.'}
            </p>
            {isMock && (
              <details className="mt-4 rounded-lg border border-ex-line bg-ex-panel p-3 text-sm">
                <summary className="cursor-pointer rounded text-ex-accent-ink">Mock engine: simulate an event</summary>
                <div className="mt-3 flex flex-wrap items-end gap-2">
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

          <section aria-labelledby="tick-h">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 id="tick-h" className="text-md font-semibold tracking-tight text-ex-ink">Live facts</h2>
                <p className="text-sm text-ex-ink2">What the model currently sees, as predicates. Repeated frames are collapsed.</p>
              </div>
              <button type="button" className="btn btn-sm" aria-pressed={paused} onClick={() => setPaused(!paused)}>
                <Icon name={paused ? 'play' : 'pause'} className="h-3.5 w-3.5" /> {paused ? 'Resume ticker' : 'Pause ticker'}
              </button>
            </div>
            <div role="log" aria-live="polite" aria-relevant="additions" aria-atomic="false" aria-label="Live fact ticker" className="max-h-64 overflow-y-auto rounded-xl border border-ex-line bg-ex-panel" tabIndex={0}>
              <ol className="divide-y divide-ex-line">
                {ticker.length === 0 && (
                  <li className="flex items-center gap-2.5 px-4 py-3.5 text-sm text-ex-ink3">
                    <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-ex-ink3 motion-safe:animate-ex-pulse" /> Waiting for facts…
                  </li>
                )}
                {ticker.map((row) => (
                  <li key={row.key} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-4 py-2.5 motion-safe:animate-ex-in">
                    <span className="font-mono text-xs tabular-nums text-ex-ink3">{fmtClock(row.at)}</span>
                    {row.facts.length === 0 ? (
                      <span className="text-sm text-ex-ink2">No entities in view</span>
                    ) : (
                      row.facts.map((f, i) => (
                        <span key={i} className="font-mono text-xs">
                          <Dsl text={`${f.pred}(${f.args.join(', ')})`} /> <span className="text-ex-ink3">{f.conf}</span>
                        </span>
                      ))
                    )}
                  </li>
                ))}
              </ol>
            </div>
          </section>

          <section aria-labelledby="log-h">
            <h2 id="log-h" className="text-md font-semibold tracking-tight text-ex-ink">Action log</h2>
            <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Action log" className="mt-2 max-h-56 overflow-y-auto" tabIndex={0}>
              {log.length === 0 ? (
                <p className="text-sm text-ex-ink3">Nothing has fired yet.</p>
              ) : (
                <ol className="divide-y divide-ex-line border-y border-ex-line">
                  {log.map((r) => (
                    <li key={r.key} className="flex items-center gap-3 py-2.5 text-sm">
                      <Badge tone={r.status === 'ok' ? 'pos' : r.status === 'failed' ? 'neg' : 'neutral'} icon={r.status === 'ok' ? 'check' : r.status === 'failed' ? 'cross' : 'minus'}>{r.status}</Badge>
                      <span className="min-w-0 flex-1 truncate">
                        <span className="text-ex-ink">{ACTION_TEXT[r.action] ?? r.action}</span>
                        {r.detail && <span className="text-ex-ink2"> · {r.detail}</span>}
                      </span>
                      <span className="font-mono text-xs tabular-nums text-ex-ink3">{fmtClock(r.at)}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </section>
        </div>

        {/* ----------------------------------------------------------- monitors, feed */}
        <div className="grid min-w-0 grid-cols-1 content-start gap-10">
          <section aria-labelledby="mon-h">
            <h2 id="mon-h" className="mb-3 text-md font-semibold tracking-tight text-ex-ink">Deployed rules</h2>
            <div className="grid gap-3">
              {deployedIds.length === 0 ? (
                <Empty title="No rule is deployed" icon="bolt" action={<Link href="/rule" className="btn">Go to Rule <Icon name="arrow-right" /></Link>}>
                  Deploy a rule on the Rule screen and it will show up here, ready to watch new events.
                </Empty>
              ) : (
                deployedIds.map((id) => <MonitorCard key={id} rule={ruleMap[id]} state={byRule[id]} now={now} />)
              )}
            </div>
          </section>

          <section aria-labelledby="feed-h">
            <h2 id="feed-h" className="text-md font-semibold tracking-tight text-ex-ink">Event feed</h2>
            <p className="mt-0.5 text-sm text-ex-ink2">Each event is ingested, read once, then scored by every deployed rule.</p>
            <div className="mt-2" role="log" aria-live="polite" aria-relevant="additions" aria-label="Event feed">
              {feed.length === 0 ? (
                <p className="rounded-xl border border-ex-line bg-ex-panel px-4 py-5 text-sm text-ex-ink3">No events yet. New ones appear here as they land in Ring history.</p>
              ) : (
                <ol className="divide-y divide-ex-line border-y border-ex-line">
                  {feed.map((f) => <FeedRow key={f.event_id} item={f} rules={ruleMap} deployed={deployedIds} />)}
                </ol>
              )}
            </div>
          </section>
        </div>
      </div>
    </>
  )
}
