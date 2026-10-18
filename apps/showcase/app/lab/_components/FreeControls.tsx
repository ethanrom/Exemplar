'use client'

import { Badge } from '@/components/Badge.tsx'
import { Button } from '@/components/Button.tsx'
import { Card } from '@/components/Card.tsx'
import { cx } from '@/components/cx.ts'
import { Poster } from '@/components/lab/FrameCell.tsx'
import type { ClipCard, Tri } from '@/lib/data/types.ts'

export type TriState = 0 | 1 | 2 // 0 not used, 1 yes, 2 no (the order of the grid's base-3 digits)

const OPTIONS: { value: TriState; label: string }[] = [
  { value: 1, label: 'Yes' },
  { value: 2, label: 'No' },
  { value: 0, label: 'Not used' },
]

const recordedWord = (t: Tri) => (t === 'pos' ? 'yes' : t === 'neg' ? 'no' : 'not used')

/**
 * The curated clips, each a keyboard-operable radio group (yes, no, not used). Arrow keys move within a clip; Tab moves
 * to the next. The recorded label of each clip is shown so a change is a visible change.
 */
export function FreeControls({
  clips, states, onChange, onReset, cards, recorded, atRecorded,
}: {
  clips: readonly string[]
  states: readonly TriState[]
  onChange: (index: number, value: TriState) => void
  onReset: () => void
  cards: ReadonlyMap<string, ClipCard>
  recorded: readonly Tri[]
  atRecorded: boolean
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ex-ink2">Set each clip to yes, no, or not used. At least one yes and one no are needed. Every example weighs 3, as a label you give does.</p>
        <Button size="sm" icon="refresh" onClick={onReset} disabled={atRecorded}>Back to the recorded labels</Button>
      </div>
      <ul className="space-y-2">
        {clips.map((alias, i) => {
          const c = cards.get(alias)
          const state = states[i] as TriState
          const rec = recorded[i] as Tri
          const changed = (state === 1 ? 'pos' : state === 2 ? 'neg' : null) !== rec
          return (
            <li key={alias}>
              <Card padding="sm">
                <fieldset className="flex min-w-0 gap-3">
                  <legend className="sr-only">{c?.title ?? alias}: use as a yes example, a no example, or not at all</legend>
                  <div className="w-24 shrink-0 sm:w-28"><Poster src={c?.poster} label={c ? `Poster: ${c.title}` : alias} compact /></div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ex-ink">{c?.title ?? alias}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-ex-ink2">{c?.summary}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      <div role="presentation" className="inline-flex rounded-lg border border-ex-line bg-ex-bg p-0.5">
                        {OPTIONS.map((o) => (
                          <label key={o.value} className="relative">
                            <input
                              type="radio"
                              name={`free-${alias}`}
                              className="peer sr-only"
                              checked={state === o.value}
                              onChange={() => onChange(i, o.value)}
                            />
                            <span className={cx(
                              'inline-flex h-8 min-w-[44px] cursor-pointer items-center justify-center rounded-md px-2.5 text-sm font-medium transition-colors',
                              'text-ex-ink2 hover:bg-ex-hover hover:text-ex-ink',
                              'peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-1 peer-focus-visible:outline-ex-accent-ink',
                              o.value === 1 && 'peer-checked:bg-ex-pos-soft peer-checked:text-ex-pos peer-checked:ring-1 peer-checked:ring-ex-pos-line',
                              o.value === 2 && 'peer-checked:bg-ex-neg-soft peer-checked:text-ex-neg peer-checked:ring-1 peer-checked:ring-ex-neg-line',
                              o.value === 0 && 'peer-checked:bg-white/[0.08] peer-checked:text-ex-ink peer-checked:ring-1 peer-checked:ring-ex-line2',
                            )}>
                              {o.label}
                            </span>
                          </label>
                        ))}
                      </div>
                      <Badge tone={changed ? 'warn' : 'neutral'} icon={changed ? 'warning' : 'flag'}>recorded: {recordedWord(rec)}{changed ? ' (changed)' : ''}</Badge>
                    </div>
                  </div>
                </fieldset>
              </Card>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
