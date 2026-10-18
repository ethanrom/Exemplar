import type { ReactNode } from 'react'
import { cx } from './cx.ts'
import { Icon, type IconName } from './Icon.tsx'
import { TONE_BADGE, TONE_ICON, type Tone } from './tone.ts'

/**
 * Quiet status tag. Colour is never the only signal: every tone carries an icon and a word.
 * A short label stays on one line; a long one wraps inside the width it is given instead of overflowing.
 */
export function Badge({
  tone = 'neutral', icon, children, title, className,
}: { tone?: Tone; icon?: IconName | null; children: ReactNode; title?: string; className?: string }) {
  const name = icon === undefined ? TONE_ICON[tone] : icon
  return (
    <span
      className={cx('inline-flex min-h-5 max-w-full items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium', TONE_BADGE[tone], className)}
      title={title}
    >
      {name && <Icon name={name} className="h-3 w-3 shrink-0" />}
      {children}
    </span>
  )
}

/** Pill-shaped label for sources, classes and filters. Larger and rounder than a Badge; no icon by default. */
export function Chip({
  tone = 'neutral', icon, children, title, className,
}: { tone?: Tone; icon?: IconName; children: ReactNode; title?: string; className?: string }) {
  return (
    <span
      className={cx('inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border border-ex-line2 px-2.5 text-xs font-medium', TONE_BADGE[tone], className)}
      title={title}
    >
      {icon && <Icon name={icon} className="h-3 w-3" />}
      {children}
    </span>
  )
}
