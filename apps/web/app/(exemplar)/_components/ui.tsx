import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

export type Tone = 'neutral' | 'pos' | 'neg' | 'warn' | 'info' | 'accent'

const TONE: Record<Tone, string> = {
  neutral: 'border-ex-line bg-ex-raised text-ex-ink2',
  pos: 'border-green-500/60 bg-green-950 text-green-200',
  neg: 'border-red-400/60 bg-red-950 text-red-200',
  warn: 'border-amber-400/60 bg-amber-950 text-amber-100',
  info: 'border-sky-400/60 bg-sky-950 text-sky-100',
  accent: 'border-cyan-300/60 bg-cyan-950 text-cyan-100',
}

const TONE_ICON: Record<Tone, IconName> = {
  neutral: 'dot', pos: 'check', neg: 'cross', warn: 'warning', info: 'info', accent: 'spark',
}

/** Status pill. Colour is never the only signal: every tone carries an icon and text. */
export function Badge({
  tone = 'neutral', icon, children, title,
}: { tone?: Tone; icon?: IconName | null; children: ReactNode; title?: string }) {
  const name = icon === undefined ? TONE_ICON[tone] : icon
  return (
    <span className={`inline-flex min-h-[24px] items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${TONE[tone]}`} title={title}>
      {name && <Icon name={name} className="h-3.5 w-3.5" />}
      {children}
    </span>
  )
}

export function PageHeader({
  title, subtitle, actions,
}: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-ex-ink">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-ex-ink2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Alert({
  tone = 'info', title, children, role,
}: { tone?: Tone; title?: string; children?: ReactNode; role?: 'alert' | 'status' }) {
  return (
    <div role={role ?? (tone === 'neg' || tone === 'warn' ? 'alert' : 'status')} className={`flex gap-3 rounded-lg border p-3 text-sm ${TONE[tone]}`}>
      <Icon name={TONE_ICON[tone] === 'dot' ? 'info' : TONE_ICON[tone]} className="mt-0.5 h-4 w-4" />
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
      </div>
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-ex-ink2">
      <svg viewBox="0 0 16 16" className="h-4 w-4 motion-safe:animate-spin" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <circle cx="8" cy="8" r="6" opacity=".25" />
        <path d="M14 8a6 6 0 0 0-6-6" strokeLinecap="round" />
      </svg>
      {label}
    </span>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-ex-line px-4 py-8 text-center">
      <p className="font-medium text-ex-ink">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-md text-sm text-ex-ink2">{children}</div>}
    </div>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-ex-line bg-ex-bg px-3 py-2">
      <dt className="text-xs text-ex-ink3">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold text-ex-ink">{value}</dd>
      {hint && <p className="text-xs text-ex-ink3">{hint}</p>}
    </div>
  )
}
