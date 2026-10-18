import { Badge } from '../Badge.tsx'
import { Dsl } from '../CodeBlock.tsx'
import { cx } from '../cx.ts'
import { Z3Badge } from '../z3/Z3Badge.tsx'
import { fmtPlain, ordinal } from './core/format.ts'

export type Selection = 'chosen_by_user_and_deployed' | 'selected_for_display_as_demo_equivalent'

export type CandidateView = {
  /** The closed rule's DSL text: identifies a candidate across views. */
  key: string
  rank: number
  dsl_text: string
  sketch_text: string
  english: string
  holes: Record<string, number>
  margin: number
  mdl: number
  /** Aliases of the labelled examples the rule gets wrong. */
  violated: string[]
  /** Position in the recorded run's candidate list, when this rule is one of the recorded ones. */
  recorded?: { position: number; of: number } | null
  selection?: Selection | null
  /** Free play: the engine's position for the same rule in its own list (null = not in the engine's list). */
  engineRank?: number | null
}

export const SELECTION_TEXT: Record<Selection, string> = {
  chosen_by_user_and_deployed: 'Chosen by the user and deployed',
  selected_for_display_as_demo_equivalent: 'Selected for display because it means the same as the deployed rule',
}

/** The ranked candidates as a radio group: one tab stop, arrow keys move the selection. */
export function CandidateList({
  items, selectedKey, onSelect, titleOf, name, label,
}: {
  items: readonly CandidateView[]
  selectedKey: string | null
  onSelect: (key: string) => void
  titleOf: (alias: string) => string
  name: string
  label: string
}) {
  if (items.length === 0) return <p className="text-sm text-ex-ink2">No candidate rules.</p>
  return (
    <fieldset className="min-w-0">
      <legend className="sr-only">{label}</legend>
      <ol className="space-y-2">
        {items.map((c) => (
          <li key={c.key}>
            <label className="block cursor-pointer">
              <input
                type="radio"
                name={name}
                className="peer sr-only"
                checked={c.key === selectedKey}
                onChange={() => onSelect(c.key)}
              />
              <span className={cx(
                'block rounded-lg border bg-ex-panel p-3 transition-colors hover:bg-ex-hover',
                'peer-checked:border-ex-accent-line peer-checked:bg-ex-accent-soft peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ex-accent-ink',
                'border-ex-line',
              )}>
                <span className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="accent" icon={null}>{ordinal(c.rank)}</Badge>
                  {c.recorded && <Badge tone="neutral" icon="flag" title="Position in the recorded run's candidate list">recorded rank: {ordinal(c.recorded.position)} of {c.recorded.of}</Badge>}
                  {c.engineRank != null && c.engineRank !== c.rank && <Badge tone="info" icon="scale" title="Position of the same rule in the engine's own list">engine rank: {ordinal(c.engineRank)}</Badge>}
                  {c.selection && <Badge tone="pos" icon="check">{SELECTION_TEXT[c.selection]}</Badge>}
                  <Z3Badge itemKey={c.key} />
                </span>
                <span className="mt-2 block text-sm text-ex-ink">{c.english}</span>
                <span className="mt-1.5 block whitespace-pre-wrap break-words font-mono text-xs leading-5"><Dsl text={c.dsl_text} /></span>
                <span className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs tabular-nums text-ex-ink2">
                  <span><span className="font-sans text-ex-ink3">margin</span> {fmtPlain(c.margin)}</span>
                  <span><span className="font-sans text-ex-ink3">description length</span> {fmtPlain(c.mdl)}</span>
                  {Object.entries(c.holes).map(([k, v]) => (<span key={k}><span className="text-ex-syn-hole">{k}</span> = {fmtPlain(v)}</span>))}
                </span>
                {c.violated.length > 0 && (
                  <span className="mt-1.5 block text-xs text-ex-warn">
                    Misses {c.violated.length} labelled example{c.violated.length > 1 ? 's' : ''}: {c.violated.map(titleOf).join('; ')}
                  </span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ol>
    </fieldset>
  )
}
