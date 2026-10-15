import type { Witness, WitnessSpan } from '../_lib/types'
import { fmtNum, fmtScore } from '../_lib/format'
import { Dsl } from './Dsl'
import { Icon } from './Icon'
import { cx } from './ui'

const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]

function niceStep(domainS: number): number {
  const target = domainS / 6
  return STEPS.find((s) => s >= target) ?? STEPS[STEPS.length - 1]
}

const depth = (path: string) => Math.max(0, path.split('.').length - 1)

const secs = (ms: number) => (ms / 1000).toFixed(1)
const interval = (s: WitnessSpan) => (s.t_start_ms === s.t_end_ms ? `${secs(s.t_start_ms)} s` : `${secs(s.t_start_ms)}–${secs(s.t_end_ms)} s`)

/** The interval a subformula was satisfied on, drawn on the shared time axis and labelled in place. */
function Lane({ span, domain, minor }: { span: WitnessSpan; domain: number; minor: number }) {
  const left = (span.t_start_ms / domain) * 100
  const width = ((span.t_end_ms - span.t_start_ms) / domain) * 100
  const pos = span.rho > 0
  const point = span.t_end_ms === span.t_start_ms
  const label = interval(span)
  // Put the label inside a wide bar; otherwise beside it, on whichever side has room.
  const inside = !point && width >= 24
  const beforeBar = !inside && left + width > 62
  return (
    <span aria-hidden="true" className="relative block h-7 rounded bg-white/[0.03]" style={{ backgroundImage: 'linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px)', backgroundSize: `${minor}% 100%` }}>
      {point ? (
        <span
          className={cx('absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px] border-2 border-ex-bg', pos ? 'bg-ex-accent-ink' : 'bg-ex-neg')}
          style={{ left: `${left}%` }}
        />
      ) : (
        <span
          className={cx(
            'absolute top-1/2 flex h-[18px] -translate-y-1/2 items-center overflow-hidden rounded-[5px] px-1.5 font-mono text-xs tabular-nums',
            pos ? 'bg-ex-accent text-white' : 'border border-ex-neg-line bg-ex-neg-soft text-ex-neg',
          )}
          style={{ left: `${left}%`, width: `${Math.max(width, 0.8)}%` }}
        >
          {inside && <span className="whitespace-nowrap">{label}</span>}
        </span>
      )}
      {!inside && (
        <span
          className="absolute top-1/2 -translate-y-1/2 whitespace-nowrap font-mono text-xs tabular-nums text-ex-ink2"
          style={beforeBar ? { right: `${100 - left + 1.2}%` } : { left: `${left + (point ? 2 : width + 1.2)}%` }}
        >
          {label}
        </span>
      )}
    </span>
  )
}

/** Tick labels on the shared time axis. */
function Axis({ ticks, domain }: { ticks: number[]; domain: number }) {
  return (
    <span aria-hidden="true" className="relative block h-4 text-xs text-ex-ink3">
      {ticks.map((t) => {
        const pct = ((t * 1000) / domain) * 100
        return (
          <span
            key={t}
            className={cx('absolute font-mono tabular-nums', pct < 3 ? '' : pct > 94 ? '-translate-x-full' : '-translate-x-1/2')}
            style={{ left: `${pct}%` }}
          >
            {t}{t === 0 ? ' s' : ''}
          </span>
        )
      })}
    </span>
  )
}

const showOp = (s: WitnessSpan) => s.op !== 'atom' && !(s.text ?? '').trimStart().startsWith(s.op)

function RhoCell({ rho }: { rho: number }) {
  const pos = rho > 0
  return (
    <span className={cx('inline-flex items-center gap-1 font-mono text-xs tabular-nums', pos ? 'text-ex-pos' : 'text-ex-neg')}>
      <Icon name={pos ? 'check' : 'cross'} className="h-3.5 w-3.5" />
      {fmtScore(rho)}
    </span>
  )
}

function SpanLabel({ s }: { s: WitnessSpan }) {
  const d = depth(s.path)
  return (
    <span style={{ marginLeft: `${d * 10}px` }} className={cx('flex min-w-0 items-baseline gap-2', d > 0 && 'border-l border-ex-line2 pl-2.5')}>
      {showOp(s) && <span className="shrink-0 font-mono text-xs text-ex-ink3">{s.op}</span>}
      <code className="min-w-0 break-words font-mono text-xs leading-5"><Dsl text={s.text ?? s.path} /></code>
    </span>
  )
}

const spoken = (s: WitnessSpan) => (s.t_start_ms === s.t_end_ms ? `at ${secs(s.t_start_ms)} s` : `from ${secs(s.t_start_ms)} to ${secs(s.t_end_ms)} s`)

/**
 * Why a rule fired: one row per subformula span from the engine's Witness (text, chosen interval, rho),
 * on a shared time axis over the clip, with the bound entities as chips. Reused on Rule and Live.
 */
export function WitnessTimeline({
  witness, durationMs, compact = false, title = 'Why it fired',
}: { witness: Witness; durationMs?: number | null; compact?: boolean; title?: string }) {
  const maxEnd = Math.max(0, ...witness.spans.map((s) => s.t_end_ms))
  const domain = Math.max(durationMs ?? 0, maxEnd, 1000)
  const step = niceStep(domain / 1000)
  const ticks: number[] = []
  for (let t = 0; t * 1000 <= domain; t += step) ticks.push(t)
  const minor = ((step / 4) * 1000 / domain) * 100
  const entities = witness.entities ?? []

  return (
    <div className={cx('rounded-lg border border-ex-line bg-ex-bg', compact ? 'p-3' : 'p-4 sm:p-5')}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-sm font-semibold text-ex-ink">{title}</p>
        <p className="font-mono text-xs tabular-nums text-ex-ink2">
          <span className="font-sans text-ex-ink3">score</span> {fmtScore(witness.score)}
          {witness.tau != null && <><span className="mx-1.5 text-ex-ink3">vs</span><span className="font-sans text-ex-ink3">τ</span> {fmtNum(witness.tau)}</>}
          {witness.margin != null && <><span className="mx-1.5 text-ex-ink3">·</span><span className="font-sans text-ex-ink3">margin</span> {fmtScore(witness.margin)}</>}
        </p>
      </div>

      {Object.keys(witness.bindings).length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Bound entities">
          {Object.entries(witness.bindings).map(([v, id]) => {
            const ent = entities.find((e) => e.id === id)
            return (
              <li key={v} className="inline-flex items-center gap-1.5 rounded-md border border-ex-line2 bg-ex-panel px-2 py-1 text-xs">
                <span className="font-mono text-ex-ink2">{v}</span>
                <span aria-hidden="true" className="text-ex-ink3">→</span>
                <span className="sr-only">bound to</span>
                <span className="font-mono font-medium text-ex-ink">{id}</span>
                {ent && (
                  <span className="text-ex-ink3">
                    {ent.type}
                    {ent.attrs && ent.attrs.length ? ` · ${ent.attrs.join(', ')}` : ''}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {witness.english && !compact && <p className="mt-3 text-sm text-ex-ink2">{witness.english}</p>}

      {compact ? (
        <div className="mt-4" tabIndex={0} role="region" aria-label="Witness timeline">
          <p className="sr-only">
            Witness timeline for rule {witness.rule_id} on clip {witness.clip_id}: each item is a part of the rule with the interval the monitor chose and its robustness ρ.
          </p>
          <div className="mb-1"><Axis ticks={ticks} domain={domain} /></div>
          <ol className="divide-y divide-ex-line border-t border-ex-line">
            {witness.spans.map((s, i) => (
              <li key={`${s.path}-${i}`} className="py-2">
                <div className="flex items-start justify-between gap-3">
                  <SpanLabel s={s} />
                  <span className="shrink-0"><RhoCell rho={s.rho} /></span>
                </div>
                <div className="mt-1.5">
                  <Lane span={s} domain={domain} minor={minor} />
                  <span className="sr-only">{spoken(s)}</span>
                </div>
              </li>
            ))}
          </ol>
        </div>
      ) : (
        <div className="relative mt-4 overflow-x-auto" tabIndex={0} role="region" aria-label="Witness timeline (scrolls sideways on narrow screens)">
          <table className="w-full min-w-[560px] table-fixed border-separate border-spacing-0 text-sm">
            <caption className="sr-only">
              Witness timeline for rule {witness.rule_id} on clip {witness.clip_id}: each row is a subformula with the interval the monitor chose and its robustness ρ.
            </caption>
            <colgroup>
              <col className="w-[34%]" />
              <col />
              <col className="w-[76px]" />
            </colgroup>
            <thead>
              <tr className="text-left text-xs text-ex-ink3">
                <th scope="col" className="pb-2 pr-3 font-medium">Part of the rule</th>
                <th scope="col" className="pb-2 font-medium">
                  <span className="sr-only">Time axis in seconds</span>
                  <Axis ticks={ticks} domain={domain} />
                </th>
                <th scope="col" className="pb-2 pl-3 text-right font-medium">ρ</th>
              </tr>
            </thead>
            <tbody>
              {witness.spans.map((s, i) => (
                <tr key={`${s.path}-${i}`} className="align-middle">
                  <th scope="row" className="border-t border-ex-line py-1.5 pr-3 text-left font-normal"><SpanLabel s={s} /></th>
                  <td className="border-t border-ex-line py-1.5">
                    <Lane span={s} domain={domain} minor={minor} />
                    <span className="sr-only">{spoken(s)}</span>
                  </td>
                  <td className="border-t border-ex-line py-1.5 pl-3 text-right"><RhoCell rho={s.rho} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!compact && (
        <p className="mt-3 text-xs text-ex-ink3">Each bar is the window of the clip where that part of the rule held. ρ says how strongly, from −0.5 (clearly not) to +0.5 (clearly yes).</p>
      )}
    </div>
  )
}
