import type { Witness, WitnessSpan } from '../_lib/types'
import { fmtNum, fmtScore } from '../_lib/format'
import { Icon } from './Icon'

const STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]

function niceStep(domainS: number): number {
  const target = domainS / 6
  return STEPS.find((s) => s >= target) ?? STEPS[STEPS.length - 1]
}

const depth = (path: string) => Math.max(0, path.split('.').length - 1)

const interval = (s: WitnessSpan) =>
  s.t_start_ms === s.t_end_ms
    ? `${(s.t_start_ms / 1000).toFixed(1)} s`
    : `${(s.t_start_ms / 1000).toFixed(1)}–${(s.t_end_ms / 1000).toFixed(1)} s`

function Bar({ span, domain }: { span: WitnessSpan; domain: number }) {
  const left = (span.t_start_ms / domain) * 100
  const width = Math.max(0, ((span.t_end_ms - span.t_start_ms) / domain) * 100)
  const pos = span.rho > 0
  const color = pos ? 'bg-green-400' : span.rho < 0 ? 'bg-red-400' : 'bg-slate-400'
  if (span.t_end_ms === span.t_start_ms) {
    return (
      <span
        className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px] border-2 border-ex-panel ${color}`}
        style={{ left: `${left}%` }}
      />
    )
  }
  return (
    <span
      className={`absolute top-1/2 h-3 -translate-y-1/2 rounded-sm border-y-2 border-ex-panel ${color}`}
      style={{ left: `${left}%`, width: `${Math.max(width, 0.8)}%` }}
    />
  )
}

/**
 * Why a rule fired: one row per subformula span from the engine's Witness (text, chosen interval, rho),
 * on a shared time axis over the clip, with the bound entities as chips. Reused on Rule and Live.
 */
export function WitnessTimeline({
  witness, durationMs, compact = false,
}: { witness: Witness; durationMs?: number | null; compact?: boolean }) {
  const maxEnd = Math.max(0, ...witness.spans.map((s) => s.t_end_ms))
  const domain = Math.max(durationMs ?? 0, maxEnd, 1000)
  const step = niceStep(domain / 1000)
  const ticks: number[] = []
  for (let t = 0; t * 1000 <= domain; t += step) ticks.push(t)
  const entities = witness.entities ?? []

  return (
    <div className="rounded-lg border border-ex-line bg-ex-panel p-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="font-semibold text-ex-ink">Why it fired</span>
        <span className="text-ex-ink2">
          score <span className="font-mono tabular-nums text-ex-ink">{fmtScore(witness.score)}</span>
          {witness.tau != null && (
            <>
              {' '}vs threshold τ <span className="font-mono tabular-nums text-ex-ink">{fmtNum(witness.tau)}</span>
            </>
          )}
          {witness.margin != null && (
            <>
              {' '}(margin <span className="font-mono tabular-nums text-ex-ink">{fmtScore(witness.margin)}</span>)
            </>
          )}
        </span>
      </div>

      {Object.keys(witness.bindings).length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Bound entities">
          {Object.entries(witness.bindings).map(([v, id]) => {
            const ent = entities.find((e) => e.id === id)
            return (
              <li key={v} className="chip">
                <span className="font-mono text-ex-ink">{v}</span>
                <span aria-hidden="true">→</span>
                <span className="sr-only">bound to</span>
                <span className="font-mono text-ex-ink">{id}</span>
                {ent && (
                  <span className="text-ex-ink3">
                    {ent.type}
                    {ent.attrs && ent.attrs.length ? `: ${ent.attrs.join(', ')}` : ''}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {witness.english && !compact && <p className="mt-2 text-sm text-ex-ink2">{witness.english}</p>}

      <div className="relative mt-3 overflow-x-auto" tabIndex={0} role="region" aria-label="Witness timeline (scrolls sideways on narrow screens)">
        <table className={`w-full table-fixed border-separate border-spacing-0 text-sm ${compact ? 'min-w-[340px]' : 'min-w-[520px]'}`}>
          <caption className="sr-only">
            Witness timeline for rule {witness.rule_id} on clip {witness.clip_id}: each row is a subformula with the interval the monitor chose and its robustness ρ.
          </caption>
          <colgroup>
            <col className={compact ? 'w-[40%]' : 'w-[34%]'} />
            <col />
            {!compact && <col className="w-[92px]" />}
            <col className="w-[72px]" />
          </colgroup>
          <thead>
            <tr className="text-left text-xs text-ex-ink3">
              <th scope="col" className="pb-1 pr-2 font-medium">Subformula</th>
              <th scope="col" className="pb-1 font-medium">
                <span className="sr-only">Time axis in seconds</span>
                <span aria-hidden="true" className="relative block h-4">
                  {ticks.map((t) => (
                    <span
                      key={t}
                      className="absolute -translate-x-1/2 font-mono tabular-nums first:translate-x-0"
                      style={{ left: `${((t * 1000) / domain) * 100}%` }}
                    >
                      {t}{t === 0 ? ' s' : ''}
                    </span>
                  ))}
                </span>
              </th>
              {!compact && <th scope="col" className="pb-1 pl-2 font-medium">Interval</th>}
              <th scope="col" className="pb-1 pl-2 text-right font-medium">ρ</th>
            </tr>
          </thead>
          <tbody>
            {witness.spans.map((s, i) => {
              const pos = s.rho > 0
              return (
                <tr key={`${s.path}-${i}`} className="align-middle">
                  <th scope="row" className="border-t border-ex-line py-1.5 pr-2 text-left font-normal">
                    <span style={{ paddingLeft: `${depth(s.path) * 14}px` }} className="flex items-start gap-1.5">
                      <span className="mt-0.5 rounded bg-ex-bg px-1 font-mono text-[11px] text-ex-ink3">{s.op}</span>
                      <span className="min-w-0">
                        <code className="break-words font-mono text-[12.5px] text-cyan-100">{s.text ?? s.path}</code>
                        {compact && <span className="block font-mono text-[11px] tabular-nums text-ex-ink3">{interval(s)}</span>}
                      </span>
                    </span>
                  </th>
                  <td className="border-t border-ex-line py-1.5">
                    <span aria-hidden="true" className="relative block h-5 rounded bg-ex-bg">
                      {ticks.map((t) => (
                        <span key={t} className="absolute inset-y-0 w-px bg-ex-line/70" style={{ left: `${((t * 1000) / domain) * 100}%` }} />
                      ))}
                      <Bar span={s} domain={domain} />
                    </span>
                  </td>
                  {!compact && (
                    <td className="border-t border-ex-line py-1.5 pl-2 font-mono text-xs tabular-nums text-ex-ink2">{interval(s)}</td>
                  )}
                  <td className="border-t border-ex-line py-1.5 pl-2 text-right">
                    <span className={`inline-flex items-center gap-1 font-mono text-xs tabular-nums ${pos ? 'text-green-300' : 'text-red-300'}`}>
                      <Icon name={pos ? 'check' : 'cross'} className="h-3.5 w-3.5" />
                      {fmtScore(s.rho)}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
