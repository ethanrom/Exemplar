import type { Conf, TraceJson } from '@/lib/data/types.ts'
import { cx } from '../cx.ts'
import { factRows, type FactRow } from './facts.ts'
import { fmtSeconds, pluralise } from './format.ts'

// What Claude read from a clip, as the rule language sees it: one row per distinct fact, a cell per sampled frame.
// Everything is computed from the recorded trace; confidence words are the trace's own (high, med, low).

const CONF_CELL: Record<Conf, string> = { high: 'bg-ex-accent-ink', med: 'bg-ex-accent-ink/60', low: 'bg-ex-accent-ink/30' }

const VISIBLE_ROWS = 6

function Row({ row, frames }: { row: FactRow; frames: number }) {
  return (
    <li className="grid gap-x-4 gap-y-1 border-t border-ex-line py-2.5 first:border-t-0 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
      <code className="min-w-0 break-words font-mono text-xs leading-5 text-ex-ink">{row.text}</code>
      <div className="min-w-0">
        <div aria-hidden="true" className="flex gap-px">
          {row.cells.map((c, i) => (
            <span key={i} className={cx('h-3 min-w-0 flex-1 rounded-[2px]', c ? CONF_CELL[c] : 'bg-white/[0.06]')} />
          ))}
        </div>
        <p className="mt-1 text-xs text-ex-ink2">
          In {row.seen} of {frames} {pluralise(frames, 'frame')}; confidence {row.levels.join(', ')}
        </p>
      </div>
    </li>
  )
}

/** The facts of one clip. The first rows show at once; a native expander holds the rest. */
export function FactsStrip({ trace, label }: { trace: TraceJson; label: string }) {
  const rows = factRows(trace)
  const frames = trace.frames.length
  const first = trace.frames[0]
  const last = trace.frames[frames - 1]
  const shown = rows.slice(0, VISIBLE_ROWS)
  const more = rows.slice(VISIBLE_ROWS)
  if (rows.length === 0) {
    return <p className="text-sm text-ex-ink2">Claude read no facts from this clip.</p>
  }
  return (
    <div aria-label={label} role="group">
      <div className="mb-1 flex justify-between text-xs tabular-nums text-ex-ink3 sm:pl-[calc(15rem+1rem)]">
        <span>Frame 1{first ? `, ${fmtSeconds(first.t_ms, 2)}` : ''}</span>
        <span>Frame {frames}{last ? `, ${fmtSeconds(last.t_ms, 2)}` : ''}</span>
      </div>
      <ul className="m-0 list-none p-0">
        {shown.map((r) => <Row key={r.key} row={r} frames={frames} />)}
      </ul>
      {more.length > 0 && (
        <details className="group mt-1 border-t border-ex-line pt-2">
          <summary className="cursor-pointer list-none rounded text-sm text-ex-accent-ink underline decoration-ex-accent-line underline-offset-2 [&::-webkit-details-marker]:hidden">
            <span className="group-open:hidden">Show {more.length} more {pluralise(more.length, 'fact')}</span>
            <span className="hidden group-open:inline">Show fewer facts</span>
          </summary>
          <ul className="m-0 mt-1 list-none p-0">
            {more.map((r) => <Row key={r.key} row={r} frames={frames} />)}
          </ul>
        </details>
      )}
      <p className="mt-2 text-xs text-ex-ink3">
        Darker cells are higher confidence; an empty cell means the fact was not asserted in that frame.
      </p>
    </div>
  )
}
