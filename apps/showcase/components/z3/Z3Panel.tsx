'use client'

import { useEffect, useRef } from 'react'
import { Button } from '../Button.tsx'
import { Icon, type IconName } from '../Icon.tsx'
import { LiveRegion } from '../lab/Announce.tsx'
import { cx } from '../cx.ts'
import { TONE_PANEL, TONE_TEXT, type Tone } from '../tone.ts'
import { UNAVAILABLE_NOTE } from '../../lib/synth/z3/capability.ts'
import { summarize, summaryText } from '../../lib/synth/z3/model.ts'
import { Z3_SHIPPED, Z3_TRANSFER_MB } from './assets.ts'
import { useZ3, type Z3Ctl } from './Z3Provider.tsx'

const seconds = (ms: number): string => `${(ms / 1000).toFixed(1)} s`

/** The one line for the status row and the live region, from the control state. */
export function statusText(ctl: Z3Ctl): string {
  const { state, run } = ctl
  if (state.phase === 'failed') return `Z3 could not run here (${state.failure ?? 'it failed to start'}). The results above are unchanged.`
  if (state.phase === 'loading') return `Loading Z3 (WebAssembly, about ${Z3_TRANSFER_MB} MB). This can take a few seconds.`
  if (state.phase !== 'ready') return ''
  if (run.status === 'running') return `Z3 is checking ${run.expected} rule${run.expected === 1 ? '' : 's'}.`
  if (run.status === 'done') {
    const text = summaryText(summarize(Object.values(run.results)))
    return run.ms !== null && run.ms > 0 ? `${text} Solved in ${Math.round(run.ms)} ms.` : text
  }
  return ctl.hasInputs ? 'Z3 is ready. Waiting for the Lab to finish its own result.' : 'Z3 is ready.'
}

function look(ctl: Z3Ctl): { tone: Tone; icon: IconName } {
  const { state, run } = ctl
  if (state.phase === 'failed') return { tone: 'warn', icon: 'warning' }
  if (state.phase === 'loading') return { tone: 'neutral', icon: 'clock' }
  if (run.status === 'done') {
    const s = summarize(Object.values(run.results))
    if (s.differs > 0 || s.failed > 0) return { tone: 'warn', icon: 'warning' }
    if (s.agree === s.checked && s.checked > 0) return { tone: 'pos', icon: 'check' }
    return { tone: 'info', icon: 'info' }
  }
  return { tone: 'neutral', icon: 'clock' }
}

/**
 * The opt-in control (SPEC 8) for the Lab's "Z3 agrees" slot: the "Check with real Z3" button, what it costs, and while it is
 * on, its status in words with a polite live region. Hidden on browsers that cannot run Z3 (one line of explanation instead).
 * Renders nothing in a build without Z3. Nothing is downloaded until the button is pressed.
 */
export function Z3Panel({ className }: { className?: string }) {
  const ctl = useZ3()
  const root = useRef<HTMLDivElement>(null)
  const refocus = useRef(false)
  const enabled = ctl?.enabled
  const phase = ctl?.state.phase
  // The button that was pressed is replaced by the next one; keep the keyboard focus on the toggle so it is not lost.
  useEffect(() => {
    if (!refocus.current) return
    refocus.current = false
    root.current?.querySelector<HTMLElement>('[data-z3-toggle]')?.focus()
  }, [enabled, phase])
  const press = (f: () => void) => () => {
    refocus.current = true
    f()
  }
  if (!Z3_SHIPPED || ctl === null || ctl.capability === null) return null
  if (!ctl.capability.ok) {
    return <p data-z3="unavailable" className={cx('text-xs text-ex-ink3', className)}>{UNAVAILABLE_NOTE}</p>
  }
  const text = ctl.enabled ? statusText(ctl) : ''
  const { tone, icon } = look(ctl)
  const ready = ctl.state.info
  return (
    <div
      ref={root}
      data-z3="panel"
      data-z3-phase={ctl.state.phase}
      data-z3-ready-ms={ready ? Math.round(ready.totalMs) : undefined}
      data-z3-solve-ms={ctl.run.ms !== null ? Math.round(ctl.run.ms) : undefined}
      className={cx('rounded-lg border px-3 py-2 text-sm', ctl.enabled ? TONE_PANEL[tone] : 'border-ex-line bg-ex-panel', className)}
    >
      {!ctl.enabled ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button size="sm" icon="bolt" data-z3-toggle onClick={press(ctl.enable)}>Check with real Z3</Button>
          <p className="min-w-0 flex-1 basis-64 text-xs text-ex-ink2">
            Also solve with Z3 (WebAssembly, downloads about {Z3_TRANSFER_MB} MB, may reserve up to 2 GB of memory). It re-solves only the selected rule and the top candidates. Nothing is downloaded until you click.
          </p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="flex min-w-0 flex-1 basis-64 items-start gap-2 font-medium text-ex-ink">
            <Icon name={icon} className={cx('mt-0.5 h-4 w-4 shrink-0', TONE_TEXT[tone])} />
            <span className="min-w-0">{text}</span>
          </p>
          {ctl.state.phase === 'failed' && <Button size="sm" icon="refresh" onClick={press(ctl.enable)}>Try again</Button>}
          <Button size="sm" variant="ghost" icon="stop" data-z3-toggle onClick={press(ctl.disable)} title="Stop Z3 and release the memory it reserved">Turn off Z3</Button>
        </div>
      )}
      <LiveRegion text={text} delay={150} />
    </div>
  )
}
