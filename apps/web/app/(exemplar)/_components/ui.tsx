import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ')

export type Tone = 'neutral' | 'pos' | 'neg' | 'warn' | 'info' | 'accent'

/** Text / icon colour per tone (all >= 4.5:1 on every surface; checked by `npm run mock:contrast`). */
export const TONE_TEXT: Record<Tone, string> = {
  neutral: 'text-ex-ink2',
  pos: 'text-ex-pos',
  neg: 'text-ex-neg',
  warn: 'text-ex-warn',
  info: 'text-ex-accent-ink',
  accent: 'text-ex-accent-ink',
}

const TONE_BADGE: Record<Tone, string> = {
  neutral: 'bg-white/[0.06] text-ex-ink2',
  pos: 'bg-ex-pos-soft text-ex-pos',
  neg: 'bg-ex-neg-soft text-ex-neg',
  warn: 'bg-ex-warn-soft text-ex-warn',
  info: 'bg-ex-accent-soft text-ex-accent-ink',
  accent: 'bg-ex-accent-soft text-ex-accent-ink',
}

const TONE_PANEL: Record<Tone, string> = {
  neutral: 'border-ex-line bg-ex-panel',
  pos: 'border-ex-pos-line bg-ex-pos-soft',
  neg: 'border-ex-neg-line bg-ex-neg-soft',
  warn: 'border-ex-warn-line bg-ex-warn-soft',
  info: 'border-ex-accent-line bg-ex-accent-soft',
  accent: 'border-ex-accent-line bg-ex-accent-soft',
}

export const TONE_ICON: Record<Tone, IconName> = {
  neutral: 'dot', pos: 'check', neg: 'cross', warn: 'warning', info: 'info', accent: 'spark',
}

/** Quiet status tag. Colour is never the only signal: every tone carries an icon and a word. */
export function Badge({
  tone = 'neutral', icon, children, title, className = '',
}: { tone?: Tone; icon?: IconName | null; children: ReactNode; title?: string; className?: string }) {
  const name = icon === undefined ? TONE_ICON[tone] : icon
  return (
    <span className={cx('inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded px-1.5 text-xs font-medium', TONE_BADGE[tone], className)} title={title}>
      {name && <Icon name={name} className="h-3 w-3" />}
      {children}
    </span>
  )
}

/** Small coloured dot with a word beside it: the lightest possible status indicator. */
export function StatusDot({ tone = 'neutral', children, pulse = false }: { tone?: Tone; children: ReactNode; pulse?: boolean }) {
  const dot: Record<Tone, string> = {
    neutral: 'bg-ex-ink3', pos: 'bg-ex-pos', neg: 'bg-ex-neg', warn: 'bg-ex-warn', info: 'bg-ex-accent-ink', accent: 'bg-ex-accent-ink',
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span aria-hidden="true" className={cx('h-1.5 w-1.5 rounded-full', dot[tone], pulse && 'motion-safe:animate-ex-pulse')} />
      {children}
    </span>
  )
}

export function PageHeader({
  title, subtitle, actions, eyebrow,
}: { title: string; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 max-w-2xl">
        {eyebrow && <p className="mb-1.5 text-xs font-medium text-ex-ink3">{eyebrow}</p>}
        <h1 className="text-xl font-semibold tracking-tight text-ex-ink sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1.5 text-base text-ex-ink2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

/** Section title row: optional step number, title, one-line description, actions on the right. */
export function SectionHeader({
  title, description, actions, step, id, headingRef, tabIndex,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  step?: number
  id?: string
  headingRef?: React.Ref<HTMLHeadingElement>
  tabIndex?: number
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 items-start gap-3">
        {step != null && (
          <span aria-hidden="true" className="mt-px grid h-6 w-6 shrink-0 place-items-center rounded-full border border-ex-line2 text-xs font-medium tabular-nums text-ex-ink2">{step}</span>
        )}
        <div className="min-w-0">
          <h2 id={id} ref={headingRef} tabIndex={tabIndex} className="text-md font-semibold leading-6 tracking-tight text-ex-ink focus:outline-none">
            {step != null && <span className="sr-only">Step {step}: </span>}
            {title}
          </h2>
          {description && <p className="mt-0.5 text-sm text-ex-ink2">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Alert({
  tone = 'info', title, children, role, action,
}: { tone?: Tone; title?: string; children?: ReactNode; role?: 'alert' | 'status'; action?: ReactNode }) {
  const icon = TONE_ICON[tone] === 'dot' ? 'info' : TONE_ICON[tone]
  return (
    <div role={role ?? (tone === 'neg' || tone === 'warn' ? 'alert' : 'status')} className={cx('flex items-start gap-3 rounded-lg border px-3.5 py-3 text-sm', TONE_PANEL[tone])}>
      <Icon name={icon} className={cx('mt-0.5 h-4 w-4', TONE_TEXT[tone])} />
      <div className="min-w-0 flex-1 text-ex-ink2">
        {title && <p className="font-medium text-ex-ink">{title}</p>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

/** Tiny inline spinner for "something is running right now" (a skeleton is used for content that is loading). */
export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-ex-ink2">
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 motion-safe:animate-spin" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="8" cy="8" r="6" opacity=".25" />
        <path d="M14 8a6 6 0 0 0-6-6" strokeLinecap="round" />
      </svg>
      {label}
    </span>
  )
}

/** Skeleton placeholder block. Announces itself once to assistive tech through `label`. */
export function Skeleton({ className = '', label }: { className?: string; label?: string }) {
  return (
    <div className={cx('skeleton', className)} role={label ? 'status' : undefined} aria-label={label} aria-hidden={label ? undefined : true} />
  )
}

export function SkeletonRows({ rows = 3, label = 'Loading', className = '', rowClass = 'h-12' }: { rows?: number; label?: string; className?: string; rowClass?: string }) {
  return (
    <div role="status" aria-label={label} className={cx('grid gap-3', className)}>
      {Array.from({ length: rows }, (_, i) => <div key={i} aria-hidden="true" className={cx('skeleton', rowClass)} style={{ opacity: 1 - i * 0.18 }} />)}
    </div>
  )
}

export function Empty({
  title, children, icon = 'layers', action, className = '',
}: { title: string; children?: ReactNode; icon?: IconName; action?: ReactNode; className?: string }) {
  return (
    <div className={cx('flex flex-col items-center rounded-xl border border-ex-line bg-ex-panel px-6 py-10 text-center', className)}>
      <span aria-hidden="true" className="grid h-9 w-9 place-items-center rounded-lg bg-ex-raised text-ex-ink3"><Icon name={icon} className="h-4 w-4" /></span>
      <p className="mt-3 font-medium text-ex-ink">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-ex-ink2">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

/** A figure: small label, big number, optional hint. Meant for use inside <StatStrip>. */
export function Stat({
  label, value, hint, tone, size = 'md', icon,
}: { label: ReactNode; value: ReactNode; hint?: ReactNode; tone?: Tone; size?: 'md' | 'lg'; icon?: IconName }) {
  return (
    <div className="min-w-0 bg-ex-panel px-4 py-3.5">
      <dt className="flex items-center gap-1.5 text-xs text-ex-ink3">{icon && <Icon name={icon} className="h-3.5 w-3.5" />}{label}</dt>
      <dd className={cx('mt-1 font-semibold tracking-tight tabular-nums', size === 'lg' ? 'text-2xl' : 'text-xl', tone ? TONE_TEXT[tone] : 'text-ex-ink')}>{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-ex-ink3">{hint}</dd>}
    </div>
  )
}

/** Hairline-separated figures in one rounded strip (no box inside a box). */
export function StatStrip({ children, cols = 'grid-cols-2 sm:grid-cols-4', label }: { children: ReactNode; cols?: string; label?: string }) {
  return (
    <dl aria-label={label} className={cx('grid gap-px overflow-hidden rounded-xl border border-ex-line bg-ex-line', cols)}>
      {children}
    </dl>
  )
}

/** Inline "label value" pair for quiet metadata (replaces chips on rules and clips). */
export function Meta({ label, value, title }: { label: ReactNode; value: ReactNode; title?: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 text-xs text-ex-ink3" title={title}>
      {label}
      <span className="font-mono tabular-nums text-ex-ink2">{value}</span>
    </span>
  )
}

export function Dot() {
  return <span aria-hidden="true" className="text-ex-ink3">·</span>
}

/** A group of mutually exclusive or toggled options rendered as one segmented control. */
export function Segmented<T extends string>({
  options, value, onChange, label,
}: {
  options: { value: T; label: ReactNode; count?: number }[]
  value: T
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-lg border border-ex-line bg-ex-bg p-0.5">
      {options.map((o) => {
        const on = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(o.value)}
            className={cx(
              'inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors',
              on ? 'bg-ex-hover text-ex-ink shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]' : 'text-ex-ink2 hover:text-ex-ink',
            )}
          >
            {o.label}
            {o.count != null && <span className="tabular-nums text-ex-ink3">{o.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

/** Accessible switch (role=switch) with a glyph in the knob so state is never colour-only. */
export function Switch({
  checked, onChange, labelledBy, disabled, describedBy,
}: { checked: boolean; onChange: () => void; labelledBy: string; disabled?: boolean; describedBy?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      aria-disabled={disabled || undefined}
      onClick={() => { if (!disabled) onChange() }}
      className={cx(
        'relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors',
        checked ? 'border-ex-pos-line bg-ex-pos/25' : 'border-ex-edge bg-ex-bg',
        disabled && 'opacity-60',
      )}
    >
      <span
        aria-hidden="true"
        className={cx(
          'absolute grid h-5 w-5 place-items-center rounded-full transition-all',
          checked ? 'left-[26px] bg-ex-pos text-ex-bg' : 'left-[3px] bg-ex-ink2 text-ex-bg',
        )}
      >
        <Icon name={checked ? 'check' : 'minus'} className="h-3 w-3" />
      </span>
    </button>
  )
}

export function IconButton({
  icon, label, onClick, disabled, className = '', pressed, expanded, controls,
}: {
  icon: IconName
  label: string
  onClick?: () => void
  disabled?: boolean
  className?: string
  pressed?: boolean
  expanded?: boolean
  controls?: string
}) {
  return (
    <button type="button" className={cx('btn-icon', className)} aria-label={label} title={label} onClick={onClick} disabled={disabled} aria-pressed={pressed} aria-expanded={expanded} aria-controls={controls}>
      <Icon name={icon} />
    </button>
  )
}

/** Suspense fallback shared by every route: the shape of a page header and a first block. */
export function PageFallback() {
  return (
    <div role="status" aria-label="Loading the page" className="grid gap-6">
      <div aria-hidden="true" className="grid gap-3">
        <div className="skeleton h-8 w-40" />
        <div className="skeleton h-4 w-2/3 max-w-xl" />
      </div>
      <div aria-hidden="true" className="skeleton mt-4 h-40 rounded-xl" />
    </div>
  )
}
