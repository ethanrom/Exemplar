'use client'

import { forwardRef } from 'react'
import { fmtNum } from '../_lib/format'
import type { EventSummary, RunEvent, RunEventType } from '../_lib/types'
import { Dsl } from './Dsl'
import { EventThumb } from './EventBits'
import { Icon, type IconName } from './Icon'
import { cx, type Tone } from './ui'

/** What the agent is doing, as a vertical stepper: sketch -> type check -> Z3 -> differential check -> counterexample -> candidates. */
const STEP: Record<Exclude<RunEventType, 'round_started'>, { icon: IconName; tone: Tone; title: (e: RunEvent) => string }> = {
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

const NODE: Record<Tone, string> = {
  neutral: 'border-ex-line2 bg-ex-raised text-ex-ink3',
  pos: 'border-ex-pos-line bg-ex-pos-soft text-ex-pos',
  neg: 'border-ex-neg-line bg-ex-neg-soft text-ex-neg',
  warn: 'border-ex-warn-line bg-ex-warn-soft text-ex-warn',
  info: 'border-ex-accent-line bg-ex-accent-soft text-ex-accent-ink',
  accent: 'border-ex-accent-line bg-ex-accent-soft text-ex-accent-ink',
}

function Step({ e, t0, clips, last }: { e: RunEvent; t0: number; clips: Map<string, EventSummary>; last: boolean }) {
  const s = STEP[e.type as keyof typeof STEP]
  if (!s) return null
  const bad = e.type === 'solve_result' && e.result && e.result !== 'sat'
  const tone: Tone = bad ? 'warn' : s.tone
  const icon: IconName = bad ? 'warning' : s.icon
  const holes = Object.entries(e.holes ?? {})
  return (
    <li className="relative flex gap-3.5 pb-5 motion-safe:animate-ex-in">
      {!last && <span aria-hidden="true" className="absolute bottom-0 left-3 top-7 w-px -translate-x-1/2 bg-ex-line2" />}
      <span className={cx('relative z-10 mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border', NODE[tone])}>
        <Icon name={icon} className="h-3 w-3" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="text-sm font-medium text-ex-ink">{s.title(e)}</p>
          <span className="font-mono text-xs tabular-nums text-ex-ink3">+{((e.at_ms - t0) / 1000).toFixed(1)} s</span>
        </div>
        {e.sketch && (
          <pre className="mt-2 whitespace-pre-wrap break-words rounded-md border border-ex-line bg-ex-bg px-3 py-2 font-mono text-xs leading-5"><code><Dsl text={e.sketch} /></code></pre>
        )}
        {e.error && <p className="mt-1.5 text-sm text-ex-neg"><span className="sr-only">Error: </span>{e.error}</p>}
        {(holes.length > 0 || e.margin != null) && (
          <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs tabular-nums text-ex-ink2">
            {holes.map(([k, v]) => (
              <span key={k}><span className="text-ex-syn-hole">{k}</span> <span className="text-ex-ink3">=</span> {v}</span>
            ))}
            {e.margin != null && <span><span className="font-sans text-ex-ink3">margin</span> {fmtNum(e.margin)}</span>}
          </p>
        )}
        {e.message && <p className="mt-1 text-sm text-ex-ink2">{e.message}</p>}
        {e.type === 'counterexample' && (e.violated_clip_ids?.length ?? 0) > 0 && (
          <ul className="mt-2 grid gap-1.5">
            {e.violated_clip_ids!.map((id) => {
              const ev = clips.get(id)
              return (
                <li key={id} className="flex items-center gap-2.5">
                  {ev && <EventThumb event={ev} compact className="h-8 w-14 shrink-0 rounded" />}
                  <span className="min-w-0 truncate text-xs text-ex-ink2">{ev?.summary ?? id}</span>
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

function RoundDivider({ e }: { e: RunEvent }) {
  return (
    <li className="mb-4 flex items-center gap-3 motion-safe:animate-ex-in" aria-label={`Round ${e.round ?? '?'}`}>
      <span className="text-xs font-medium uppercase tracking-wider text-ex-ink3">Round {e.round ?? '?'}</span>
      <span aria-hidden="true" className="h-px flex-1 bg-ex-line" />
    </li>
  )
}

/** One-line tally of what the loop has done so far. */
function Tally({ timeline }: { timeline: RunEvent[] }) {
  const sketches = timeline.filter((e) => e.type === 'sketch_proposed').length
  const sat = timeline.filter((e) => e.type === 'solve_result' && e.result === 'sat').length
  const counter = timeline.filter((e) => e.type === 'counterexample').length
  const secs = timeline.length > 1 ? (timeline[timeline.length - 1].at_ms - timeline[0].at_ms) / 1000 : 0
  const item = (n: number, label: string) => (
    <span><span className="font-medium tabular-nums text-ex-ink">{n}</span> {label}</span>
  )
  return (
    <p className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ex-ink3">
      {item(sketches, sketches === 1 ? 'sketch' : 'sketches')}
      {item(sat, 'solved')}
      {item(counter, counter === 1 ? 'counterexample' : 'counterexamples')}
      <span className="font-mono tabular-nums">{secs.toFixed(1)} s</span>
    </p>
  )
}

const IDLE: { icon: IconName; title: string; text: string }[] = [
  { icon: 'spark', title: 'Sketch', text: 'A language model proposes the structure of a rule, with numeric holes.' },
  { icon: 'check', title: 'Type check', text: 'Anything that does not fit the ontology is sent back.' },
  { icon: 'sliders', title: 'Z3 solve', text: 'The solver fills the holes so every example is right, or proves none fit.' },
  { icon: 'shield', title: 'Differential check', text: 'An independent evaluator re-scores the solution.' },
  { icon: 'warning', title: 'Counterexamples', text: 'Examples a rule cannot satisfy come back as hints.' },
]

export const AgentTimeline = forwardRef<HTMLDivElement, {
  timeline: RunEvent[]
  clips: Map<string, EventSummary>
  running: boolean
}>(function AgentTimeline({ timeline, clips, running }, ref) {
  const t0 = timeline[0]?.at_ms ?? 0
  if (timeline.length === 0) {
    if (running) {
      return (
        <div role="status" aria-label="Waiting for the first step" className="grid gap-3">
          {[0, 1, 2].map((i) => <div key={i} aria-hidden="true" className="skeleton h-10" style={{ opacity: 1 - i * 0.25 }} />)}
        </div>
      )
    }
    return (
      <div>
        <p className="mb-4 text-sm text-ex-ink2">Press Teach to watch the loop: sketch a rule, check its types, let Z3 solve the thresholds, then check the solution with an independent evaluator.</p>
        <ol className="relative" aria-label="The steps of a run">
          {IDLE.map((s, i) => (
            <li key={s.title} className="relative flex gap-3.5 pb-4 last:pb-0">
              {i < IDLE.length - 1 && <span aria-hidden="true" className="absolute bottom-0 left-3 top-7 w-px -translate-x-1/2 bg-ex-line" />}
              <span className="relative z-10 mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border border-ex-line2 bg-ex-raised text-ex-ink3"><Icon name={s.icon} className="h-3 w-3" /></span>
              <div className="min-w-0">
                <p className="text-sm font-medium text-ex-ink2">{s.title}</p>
                <p className="text-xs text-ex-ink3">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    )
  }
  const shown = timeline.filter((e) => e.type === 'round_started' || STEP[e.type as keyof typeof STEP])
  // index of the last real step (not a round divider) so its connector is dropped when the run is over
  let lastStep = -1
  shown.forEach((e, i) => { if (e.type !== 'round_started') lastStep = i })
  return (
    <div>
      <Tally timeline={timeline} />
      <div ref={ref} tabIndex={0} role="log" aria-live="polite" aria-relevant="additions" aria-label="Agent timeline" className="max-h-[400px] overflow-y-auto pr-2">
        <ol>
          {shown.map((e, i) =>
            e.type === 'round_started'
              ? <RoundDivider key={e.seq} e={e} />
              : <Step key={e.seq} e={e} t0={t0} clips={clips} last={i === lastStep && !running} />,
          )}
          {running && (
            <li className="relative flex items-center gap-3.5" aria-hidden="true">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-ex-line2"><span className="h-1.5 w-1.5 rounded-full bg-ex-accent-ink motion-safe:animate-ex-pulse" /></span>
              <span className="text-sm text-ex-ink3 motion-safe:animate-ex-pulse">Waiting for the next step…</span>
            </li>
          )}
        </ol>
      </div>
    </div>
  )
})

