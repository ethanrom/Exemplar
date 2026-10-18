import type { ReactNode } from 'react'
import { Card } from './Card.tsx'
import { cx } from './cx.ts'
import { Icon, type IconName } from './Icon.tsx'
import { SmartLink } from './Link.tsx'
import { TONE_TEXT, type Tone } from './tone.ts'

/** A figure: small label, big number, optional hint. Meant for use inside <StatStrip>. */
export function Stat({
  label, value, hint, tone, size = 'md', icon,
}: { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: Tone; size?: 'md' | 'lg'; icon?: IconName }) {
  return (
    <div className="min-w-0 bg-ex-panel px-4 py-3.5">
      <dt className="flex items-center gap-1.5 text-xs text-ex-ink3">
        {icon && <Icon name={icon} className="h-3.5 w-3.5" />}
        {label}
      </dt>
      <dd className={cx('mt-1 font-semibold tracking-tight tabular-nums', size === 'lg' ? 'text-2xl' : 'text-xl', tone ? TONE_TEXT[tone] : 'text-ex-ink')}>{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ex-ink3">{hint}</dd>}
    </div>
  )
}

/** Hairline-separated figures in one rounded strip (no box inside a box). */
export function StatStrip({
  children, cols = 'grid-cols-2 sm:grid-cols-4', label,
}: { children: ReactNode; cols?: string; label?: string }) {
  return (
    <dl aria-label={label} className={cx('grid gap-px overflow-hidden rounded-xl border border-ex-line bg-ex-line', cols)}>
      {children}
    </dl>
  )
}

const VALUE_SIZE = { xl: 'text-xl', lg: 'text-lg', md: 'text-md', base: 'text-base' } as const

/**
 * A proof tile: label, one headline value, a caption, and a link to the page that backs it up.
 * Render the value through a source-bound component (NumberText / DataValue) once those exist.
 */
export function StatTile({
  label, value, valueSize = 'xl', caption, href, linkLabel, tone, className,
}: {
  label: ReactNode
  value: ReactNode
  /** Type size of the headline value: 'xl' (24 px, a short figure) down to 'base' (14 px) for a claim that is a sentence. */
  valueSize?: keyof typeof VALUE_SIZE
  caption?: ReactNode
  href?: string
  linkLabel?: string
  tone?: Tone
  className?: string
}) {
  return (
    <Card as="article" className={cx('flex flex-col', className)}>
      <p className="text-xs font-medium text-ex-ink3">{label}</p>
      <p className={cx('mt-1.5 break-words font-semibold tracking-tight', VALUE_SIZE[valueSize], tone ? TONE_TEXT[tone] : 'text-ex-ink')}>{value}</p>
      {caption && <p className="mt-1.5 text-sm text-ex-ink2">{caption}</p>}
      {href && (
        <p className="mt-auto pt-3">
          <SmartLink href={href} className="link inline-flex items-center gap-1 text-sm">
            {linkLabel ?? 'See the evidence'}
            <Icon name="arrow-right" className="h-3.5 w-3.5" />
          </SmartLink>
        </p>
      )}
    </Card>
  )
}
