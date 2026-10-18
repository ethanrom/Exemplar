'use client'

import { forwardRef, memo, useState } from 'react'
import { cx } from '../cx.ts'
import { Dsl } from '../CodeBlock.tsx'
import { Icon, type IconName } from '../Icon.tsx'
import type { Tone } from '../tone.ts'
import type { ClipCard, RunEvent, RunEventType } from '../../lib/data/types.ts'
import { fmtPlain } from './core/format.ts'

/** What the agent is doing, as a vertical stepper: sketch -> type check -> solve -> check -> counterexample -> candidates. */
const STEP: Partial<Record<RunEventType, { icon: IconName; tone: Tone; title: (e: RunEvent) => string }>> = {
  sketch_proposed: { icon: 'spark', tone: 'accent', title: () => 'Rule sketch proposed' },
  typecheck_failed: { icon: 'cross', tone: 'neg', title: () => 'Type check failed, sketch sent back' },
  solve_started: { icon: 'clock', tone: 'neutral', title: () => 'The solver is filling in the numbers' },
  solve_result: {
    icon: 'check', tone: 'pos',
    title: (e) => ((e.result as string | null | undefined) === 'sat' ? 'The solver found the numbers that fit best' : e.result === 'unsat' ? 'The solver showed no numbers fit' : e.result === 'timeout' ? 'The solver timed out' : e.result === 'grid_fallback' ? 'Fell back to a grid search' : (e.result as string | null | undefined) === 'budget_exceeded' ? 'Too large to re-solve in the browser' : 'Solver finished'),
  },
  differential_check: { icon: 'shield', tone: 'pos', title: () => 'Re-checked with the evaluator' },
  counterexample: { icon: 'info', tone: 'neutral', title: () => 'A labelled clip does not fit this rule' },
  candidates: { icon: 'check', tone: 'pos', title: () => 'Candidate rules ready' },
  question_ready: { icon: 'question', tone: 'info', title: () => 'One question is ready' },
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

const Step = memo(function Step({ e, clips, last }: { e: RunEvent; clips: ReadonlyMap<string, ClipCard>; last: boolean }) {
  const s = STEP[e.type]
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
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <p className="text-sm font-medium text-ex-ink">{s.title(e)}</p>
          <span className="font-mono text-xs tabular-nums text-ex-ink3">+{(e.t_ms / 1000).toFixed(1)} s</span>
        </div>
        {e.sketch && (
          <pre className="mt-2 whitespace-pre-wrap break-words rounded-md border border-ex-line bg-ex-bg px-3 py-2 font-mono text-xs leading-5"><code><Dsl text={e.sketch} /></code></pre>
        )}
        {e.error && <p className="mt-1.5 whitespace-pre-wrap break-words text-sm text-ex-neg"><span className="sr-only">Error: </span>{e.error.split('\n')[0]}</p>}
        {(holes.length > 0 || e.margin != null) && (
          <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs tabular-nums text-ex-ink2">
            {holes.map(([k, v]) => (
              <span key={k}><span className="text-ex-syn-hole">{k}</span> <span className="text-ex-ink3">=</span> {fmtPlain(v)}</span>
            ))}
            {e.margin != null && <span><span className="font-sans text-ex-ink3">margin</span> {fmtPlain(e.margin)}</span>}
          </p>
        )}
        {e.message && e.type !== 'counterexample' && <p className="mt-1 text-sm text-ex-ink2">{e.message}</p>}
        {e.type === 'counterexample' && (e.violated_clip_ids?.length ?? 0) > 0 && (
          <ul className="mt-2 grid gap-1.5">
            {e.violated_clip_ids!.map((id) => {
              const c = clips.get(id)
              return (
                <li key={id} className="flex items-center gap-2.5">
                  {c?.poster
                    // eslint-disable-next-line @next/next/no-img-element
                    ? <img src={c.poster} alt="" loading="lazy" width={56} height={32} className="h-8 w-14 shrink-0 rounded object-cover" />
                    : <span aria-hidden="true" className="grid h-8 w-14 shrink-0 place-items-center rounded bg-ex-raised text-ex-ink3"><Icon name="image" className="h-3.5 w-3.5" /></span>}
                  <span className="min-w-0 flex-1 truncate text-xs text-ex-ink2" title={c?.title}>{c?.title ?? id}</span>
                </li>
              )
            })}
          </ul>
        )}
        {e.type === 'counterexample' && <p className="mt-1 text-xs text-ex-ink3">The facts read from these clips disagree with their labels, so the rule does not fit them. Either the label or the reading may be off.</p>}
      </div>
    </li>
  )
})

const RoundDivider = memo(function RoundDivider({ e }: { e: RunEvent }) {
  return (
    <li className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 motion-safe:animate-ex-in" aria-label={`Round ${e.round ?? '?'}`}>
      <span className="text-xs font-medium uppercase tracking-wider text-ex-ink3">Round {e.round ?? '?'}</span>
      <span aria-hidden="true" className="h-px min-w-6 flex-1 bg-ex-line" />
      {e.message && <span className="max-w-full text-xs text-ex-ink3">{e.message}</span>}
    </li>
  )
})

/** One-line tally of what the loop has done so far. */
function Tally({ timeline }: { timeline: readonly RunEvent[] }) {
  const sketches = timeline.filter((e) => e.type === 'sketch_proposed').length
  const solved = timeline.filter((e) => e.type === 'solve_result' && e.result === 'sat').length
  const counter = timeline.filter((e) => e.type === 'counterexample').length
  const secs = timeline.length > 1 ? ((timeline[timeline.length - 1] as RunEvent).t_ms - (timeline[0] as RunEvent).t_ms) / 1000 : 0
  const item = (n: number, label: string) => (<span><span className="font-medium tabular-nums text-ex-ink">{n}</span> {label}</span>)
  return (
    <p className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ex-ink3">
      {item(sketches, sketches === 1 ? 'sketch' : 'sketches')}
      {item(solved, 'solved')}
      {item(counter, counter === 1 ? 'counterexample' : 'counterexamples')}
      <span className="font-mono tabular-nums">{secs.toFixed(1)} s</span>
    </p>
  )
}

/** The agent's run as a stepper. `events` is whatever should be visible now (a replay shows a growing prefix). */
export const AgentTimeline = forwardRef<HTMLDivElement, {
  events: readonly RunEvent[]
  clips: ReadonlyMap<string, ClipCard>
  running?: boolean
  label?: string
  maxHeight?: string
  /** Show only the newest N steps until the reader asks for all of them (long streams). */
  limit?: number
}>(function AgentTimeline({ events, clips, running = false, label = 'Agent timeline', maxHeight = 'max-h-[420px]', limit }, ref) {
  const [all, setAll] = useState(false)
  const steps = events.filter((e) => e.type === 'round_started' || STEP[e.type])
  const cut = limit !== undefined && !all && steps.length > limit
  const shown = cut ? steps.slice(steps.length - limit) : steps
  let lastStep = -1
  shown.forEach((e, i) => { if (e.type !== 'round_started') lastStep = i })
  return (
    <div>
      <Tally timeline={events} />
      <div ref={ref} tabIndex={0} role="log" aria-live="polite" aria-relevant="additions" aria-label={label} className={cx(maxHeight, 'overflow-y-auto pr-2')}>
        {shown.length === 0 && !running && <p className="text-sm text-ex-ink2">Nothing has run yet.</p>}
        {cut && (
          <p className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ex-ink3">
            <span>Showing the newest {limit} of {steps.length} steps.</span>
            <button type="button" onClick={() => setAll(true)} className="underline decoration-ex-line2 underline-offset-2 hover:text-ex-ink">Show all steps</button>
          </p>
        )}
        <ol>
          {shown.map((e, i) => (
            e.type === 'round_started'
              ? <RoundDivider key={e.seq} e={e} />
              : <Step key={e.seq} e={e} clips={clips} last={i === lastStep && !running} />
          ))}
          {running && (
            <li className="relative flex items-center gap-3.5" aria-hidden="true">
              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-ex-line2"><span className="h-1.5 w-1.5 rounded-full bg-ex-accent-ink motion-safe:animate-ex-pulse" /></span>
              <span className="text-sm text-ex-ink3 motion-safe:animate-ex-pulse">Working…</span>
            </li>
          )}
        </ol>
      </div>
    </div>
  )
})
