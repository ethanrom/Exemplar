import type { ReactNode } from 'react'
import { cx } from '../cx.ts'
import { Icon, type IconName } from '../Icon.tsx'
import { TONE_PANEL, TONE_TEXT, type Tone } from '../tone.ts'
import { Z3Panel } from '../z3/Z3Panel.tsx'

export type MatchKind = 'idle' | 'pending' | 'match' | 'partial' | 'mismatch' | 'unchecked'

const LOOK: Record<MatchKind, { tone: Tone; icon: IconName }> = {
  idle: { tone: 'neutral', icon: 'info' },
  pending: { tone: 'neutral', icon: 'clock' },
  match: { tone: 'pos', icon: 'check' },
  partial: { tone: 'info', icon: 'check' },
  mismatch: { tone: 'neg', icon: 'cross' },
  unchecked: { tone: 'warn', icon: 'warning' },
}

/**
 * The engine-check badge (SPEC 6.4): what the in-browser result was compared with, and how it came out. A colour is never
 * the only signal: every state carries an icon and its words. Further sentences sit under a native expander.
 */
export function MatchBadge({
  kind, headline, details = [], children, className,
}: { kind: MatchKind; headline: string; details?: string[]; children?: ReactNode; className?: string }) {
  const { tone, icon } = LOOK[kind]
  return (
    <div className={cx('rounded-lg border px-3 py-2 text-sm', TONE_PANEL[tone], className)}>
      <p role="status" aria-live="polite" className="flex items-start gap-2 font-medium text-ex-ink">
        <Icon name={icon} className={cx('mt-0.5 h-4 w-4 shrink-0', TONE_TEXT[tone])} />
        <span className="min-w-0">{headline}</span>
      </p>
      {details.length > 0 && (
        <details className="mt-1 pl-6 text-ex-ink2">
          <summary className="cursor-pointer text-xs text-ex-ink2 underline decoration-ex-line2 underline-offset-2">Details</summary>
          <ul className="mt-1 list-disc space-y-1 pl-4 text-xs">
            {details.map((d) => (<li key={d} className="break-words">{d}</li>))}
          </ul>
        </details>
      )}
      {children}
    </div>
  )
}

/**
 * The Z3 slot (SPEC 8): the opt-in "Check with real Z3" control. It renders nothing in a build without Z3 and downloads nothing
 * until the button is pressed; the per-candidate "Z3 agrees" badges (components/z3/Z3Badge.tsx) appear on the candidates.
 */
export function Z3AgreesSlot({ className }: { className?: string }) {
  return <div data-slot="z3-agrees" className="contents"><Z3Panel className={className} /></div>
}
