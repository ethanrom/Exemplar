import type { IconName } from './Icon.tsx'

export type Tone = 'neutral' | 'pos' | 'neg' | 'warn' | 'info' | 'accent'

/** Text / icon colour per tone (all >= 4.5:1 on every surface). */
export const TONE_TEXT: Record<Tone, string> = {
  neutral: 'text-ex-ink2',
  pos: 'text-ex-pos',
  neg: 'text-ex-neg',
  warn: 'text-ex-warn',
  info: 'text-ex-accent-ink',
  accent: 'text-ex-accent-ink',
}

export const TONE_BADGE: Record<Tone, string> = {
  neutral: 'bg-white/[0.06] text-ex-ink2',
  pos: 'bg-ex-pos-soft text-ex-pos',
  neg: 'bg-ex-neg-soft text-ex-neg',
  warn: 'bg-ex-warn-soft text-ex-warn',
  info: 'bg-ex-accent-soft text-ex-accent-ink',
  accent: 'bg-ex-accent-soft text-ex-accent-ink',
}

export const TONE_PANEL: Record<Tone, string> = {
  neutral: 'border-ex-line bg-ex-panel',
  pos: 'border-ex-pos-line bg-ex-pos-soft',
  neg: 'border-ex-neg-line bg-ex-neg-soft',
  warn: 'border-ex-warn-line bg-ex-warn-soft',
  info: 'border-ex-accent-line bg-ex-accent-soft',
  accent: 'border-ex-accent-line bg-ex-accent-soft',
}

export const TONE_ICON: Record<Tone, IconName> = {
  neutral: 'dot',
  pos: 'check',
  neg: 'cross',
  warn: 'warning',
  info: 'info',
  accent: 'spark',
}
