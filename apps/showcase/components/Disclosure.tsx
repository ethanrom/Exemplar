import type { ReactNode } from 'react'
import { cx } from './cx.ts'
import { Icon } from './Icon.tsx'
import { TONE_PANEL, TONE_TEXT, type Tone } from './tone.ts'

/**
 * A disclosure callout: the plain statement of what a thing is or is not (what runs here, how a candidate was
 * selected, what a result does not cover). It carries `data-disclosure` so the copy audit can tell wording
 * that sits inside a disclosure from wording that does not (SPEC section 10.2). Put it next to the result it qualifies.
 */
export function Disclosure({
  title, children, tone = 'neutral', as: Heading = 'h2', className, id,
}: {
  title?: string
  children: ReactNode
  tone?: Tone
  as?: 'h2' | 'h3' | 'h4' | 'p'
  className?: string
  id?: string
}) {
  return (
    <div id={id} data-disclosure="" className={cx('flex items-start gap-3 rounded-lg border px-3.5 py-3 text-sm', TONE_PANEL[tone], className)}>
      <Icon name="info" className={cx('mt-0.5 h-4 w-4', tone === 'neutral' ? 'text-ex-ink3' : TONE_TEXT[tone])} />
      <div className="min-w-0 flex-1 space-y-1.5 text-ex-ink2">
        {title && <Heading className="font-medium text-ex-ink">{title}</Heading>}
        {children}
      </div>
    </div>
  )
}

/** A native, keyboard-operable expander for long material (the transcript, a long table). No JavaScript needed. */
export function Collapsible({
  summary, children, className, defaultOpen,
}: { summary: ReactNode; children: ReactNode; className?: string; defaultOpen?: boolean }) {
  return (
    <details open={defaultOpen} className={cx('group rounded-lg border border-ex-line bg-ex-panel', className)}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-3.5 py-2.5 text-base font-medium text-ex-ink [&::-webkit-details-marker]:hidden">
        {summary}
        <Icon name="chevron" className="h-4 w-4 text-ex-ink3 transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-ex-line px-3.5 py-3 text-sm text-ex-ink2">{children}</div>
    </details>
  )
}

/** A status or notice banner (not a disclosure): info, warning, error. */
export function Alert({
  tone = 'info', title, children,
}: { tone?: Tone; title?: string; children?: ReactNode }) {
  return (
    <div role={tone === 'neg' || tone === 'warn' ? 'alert' : 'status'} className={cx('flex items-start gap-3 rounded-lg border px-3.5 py-3 text-sm', TONE_PANEL[tone])}>
      <Icon name={tone === 'neg' ? 'cross' : tone === 'warn' ? 'warning' : tone === 'pos' ? 'check' : 'info'} className={cx('mt-0.5 h-4 w-4', TONE_TEXT[tone])} />
      <div className="min-w-0 flex-1 text-ex-ink2">
        {title && <p className="font-medium text-ex-ink">{title}</p>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
      </div>
    </div>
  )
}
