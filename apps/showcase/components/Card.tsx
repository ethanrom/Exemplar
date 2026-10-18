import type { HTMLAttributes, ReactNode } from 'react'
import { cx } from './cx.ts'
import { TONE_PANEL, type Tone } from './tone.ts'

type CardProps = Omit<HTMLAttributes<HTMLElement>, 'children'> & {
  as?: 'div' | 'section' | 'article' | 'li'
  /** Neutral is the default surface; other tones tint the panel (always pair them with an icon or a word). */
  tone?: Tone
  padding?: 'none' | 'sm' | 'md' | 'lg'
  children?: ReactNode
}

const PADDING = { none: 'p-0', sm: 'p-3.5', md: 'p-5', lg: 'p-6 sm:p-8' } as const

/** The standard surface: rounded panel with a hairline border. */
export function Card({ as = 'div', tone = 'neutral', padding = 'md', className, children, ...rest }: CardProps) {
  const Tag = as
  return (
    <Tag {...rest} className={cx('rounded-xl border', TONE_PANEL[tone], PADDING[padding], className)}>
      {children}
    </Tag>
  )
}

export function CardTitle({
  as: Tag = 'h3', children, className,
}: { as?: 'h2' | 'h3' | 'h4'; children: ReactNode; className?: string }) {
  return <Tag className={cx('card-title', className)}>{children}</Tag>
}
