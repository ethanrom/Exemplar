import type { WitnessJson, WitnessSpan } from '@/lib/data/types.ts'
import { Dsl } from '../CodeBlock.tsx'
import { cx } from '../cx.ts'
import { Icon } from '../Icon.tsx'
import { fmtScore, fmtSeconds, fmtSpan } from './format.ts'

// "Why it fired": the recorded witness of a rule that fired. Every span is the engine's own (path, operator, time
// window, robustness). The sentence for each span is built from those fields by code, never by a model.

const OP_LABEL: Record<string, string> = {
  holds_for: 'Held continuously',
  atom: 'Seen in a frame',
  or: 'Either of',
  and: 'All of',
  not: 'Absent',
  eventually: 'Happened at some point',
  always: 'Held at every moment',
  then: 'Happened in order',
}

const spanLabel = (op: string): string => OP_LABEL[op] ?? op

function describe(span: WitnessSpan): string {
  const a = span.t_start_ms
  const b = span.t_end_ms
  if (a === b) return `at ${fmtSeconds(a, 2)}`
  return `from ${fmtSeconds(a, 2)} to ${fmtSeconds(b, 2)} (${fmtSpan(a, b)})`
}

function Row({ span, durationMs }: { span: WitnessSpan; durationMs: number }) {
  const start = Math.max(0, Math.min(100, (span.t_start_ms / durationMs) * 100))
  const end = Math.max(0, Math.min(100, (span.t_end_ms / durationMs) * 100))
  const point = span.t_start_ms === span.t_end_ms
  const width = Math.max(end - start, 0)
  return (
    <li className="border-t border-ex-line py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
        <p className="text-sm font-medium text-ex-ink">{spanLabel(span.op)}</p>
        <p className="text-xs tabular-nums text-ex-ink2">
          {describe(span)}; ρ {fmtScore(span.rho)}
        </p>
      </div>
      {span.text && <p className="mt-0.5 break-words font-mono text-xs leading-5"><Dsl text={span.text} /></p>}
      <div aria-hidden="true" className="relative mt-1.5 h-3 rounded bg-white/[0.06]">
        {point ? (
          <span className="absolute top-1/2 h-3 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-[2px] bg-ex-accent-ink" style={{ left: `${start}%` }} />
        ) : (
          <span className={cx('absolute top-0 h-3 rounded bg-ex-accent-ink/70')} style={{ left: `${start}%`, width: `${width}%` }} />
        )}
      </div>
    </li>
  )
}

/** The witness of one firing: what was bound, then the spans in the engine's order on a shared time axis. */
export function WitnessTimeline({ witness, durationMs }: { witness: WitnessJson; durationMs: number }) {
  const bound = Object.entries(witness.bindings)
  const entityOf = (id: string) => witness.entities?.find((e) => e.id === id)
  return (
    <div>
      {bound.length > 0 && (
        <p className="mb-2 text-sm text-ex-ink2">
          Bound to{' '}
          {bound.map(([name, id], i) => {
            const e = entityOf(id)
            return (
              <span key={name}>
                {i > 0 && ', '}
                <code className="font-mono text-xs text-ex-ink">{name} = {id}</code>
                {e && <> ({e.type}: {e.attrs.map((a) => a.replace(/_/g, ' ')).join(', ')})</>}
              </span>
            )
          })}
        </p>
      )}
      <ol className="m-0 list-none rounded-lg border border-ex-line bg-ex-bg px-3 py-1">
        {witness.spans.map((s, i) => <Row key={`${s.path}-${i}`} span={s} durationMs={durationMs} />)}
      </ol>
      <div aria-hidden="true" className="mt-1 flex justify-between text-xs tabular-nums text-ex-ink3">
        <span>0 s</span>
        <span>{fmtSeconds(durationMs)}</span>
      </div>
    </div>
  )
}

/** "Why it fired" as a native expander, open by default; it is keyboard operable without any script. */
export function WhyItFired({ witness, durationMs, defaultOpen = true }: { witness: WitnessJson; durationMs: number; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className="group rounded-lg border border-ex-line bg-ex-bg">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-3 py-2 text-base font-medium text-ex-ink [&::-webkit-details-marker]:hidden">
        Why it fired
        <Icon name="chevron" className="h-4 w-4 text-ex-ink3 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-ex-line px-3 py-3">
        {witness.english && <p className="mb-3 text-sm text-ex-ink" data-src={`live.json#${witness.rule_id}.witness.english`}>{witness.english}</p>}
        <WitnessTimeline witness={witness} durationMs={durationMs} />
      </div>
    </details>
  )
}
