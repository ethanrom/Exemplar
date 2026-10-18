import { Fragment, type ReactNode } from 'react'
import { cx } from './cx.ts'

// Syntax highlighting for the Exemplar rule language (docs/DSL.md). Presentation only: the text always
// comes from the exported data (`dsl_text`, `sketch_text`, witness spans) and is never rewritten here.
// Ported from apps/web (Dsl.tsx); the token classes and colours are identical.

const KEYWORDS = new Set(['exists', 'when', 'and', 'or', 'not', 'in', 'hour', 'subtype', 'device'])
const TEMPORAL = new Set(['eventually', 'always', 'then', 'holds_for'])
const TYPES = new Set(['Entity', 'Person', 'Vehicle', 'Package', 'Animal', 'Object', 'Carryable', 'Zone', 'Label'])
const ZONES = new Set(['door', 'porch', 'steps', 'yard', 'driveway', 'sidewalk', 'street', 'dock'])

export type DslTokenKind = 'kw' | 'temporal' | 'type' | 'zone' | 'num' | 'hole' | 'pred' | 'var' | 'punct' | 'space'

const CLASS: Record<DslTokenKind, string> = {
  kw: 'text-ex-syn-kw',
  temporal: 'text-ex-syn-temporal font-medium',
  type: 'text-ex-syn-type',
  zone: 'text-ex-syn-zone',
  num: 'text-ex-syn-num tabular-nums',
  hole: 'text-ex-syn-hole underline decoration-dotted decoration-1 underline-offset-4',
  pred: 'text-ex-ink font-medium',
  var: 'text-ex-ink2',
  punct: 'text-ex-ink3',
  space: '',
}

const TOKEN = /(\s+)|(\?[A-Za-z_]\w*)|(\d+(?:\.\d+)?)|([A-Za-z_]\w*)|(>=|<=|[^\sA-Za-z0-9_?])/g

export function tokenizeDsl(text: string): { kind: DslTokenKind; text: string }[] {
  // Variables are whatever the rule declares as `name: Type`; short lower-case names are variables too
  // (witness fragments carry no declaration).
  const declared = new Set<string>()
  for (const m of Array.from(text.matchAll(/([A-Za-z_]\w*)\s*:\s*[A-Z]\w*/g))) declared.add(m[1] as string)
  const out: { kind: DslTokenKind; text: string }[] = []
  for (const m of Array.from(text.matchAll(TOKEN))) {
    const [raw, space, hole, num, word, punct] = m
    if (space) out.push({ kind: 'space', text: raw })
    else if (hole) out.push({ kind: 'hole', text: raw })
    else if (num) out.push({ kind: 'num', text: raw })
    else if (word) {
      const next = text[(m.index ?? 0) + raw.length]
      let kind: DslTokenKind
      if (KEYWORDS.has(word)) kind = 'kw'
      else if (TEMPORAL.has(word)) kind = 'temporal'
      else if (TYPES.has(word)) kind = 'type'
      else if (ZONES.has(word)) kind = 'zone'
      else if (next === '(') kind = 'pred'
      else if (declared.has(word) || word.length <= 2) kind = 'var'
      else kind = 'zone' // literal labels such as cardboard_box
      out.push({ kind, text: raw })
    } else if (punct) out.push({ kind: 'punct', text: raw })
  }
  return out
}

/** Inline highlighted rule text. */
export function Dsl({ text, className }: { text: string; className?: string }) {
  const nodes: ReactNode[] = tokenizeDsl(text).map((t, i) =>
    t.kind === 'space' ? <Fragment key={i}>{t.text}</Fragment> : <span key={i} className={CLASS[t.kind]}>{t.text}</span>,
  )
  return <span className={className}>{nodes}</span>
}

/** A rule as a block: monospace, wrapped (never horizontally scrolling), highlighted. */
export function DslBlock({
  text, className, size = 'md', label = 'Rule in the Exemplar rule language',
}: { text: string; className?: string; size?: 'sm' | 'md' | 'lg'; label?: string }) {
  const sz = size === 'lg' ? 'px-4 py-3.5 text-[15px] leading-7' : size === 'sm' ? 'px-3 py-2 text-xs leading-5' : ''
  return (
    <figure aria-label={label} className="m-0">
      <pre className={cx('code', sz, className)}>
        <code><Dsl text={text} /></code>
      </pre>
    </figure>
  )
}

/** A plain monospace block for commands and file excerpts. Not highlighted. */
export function CodeBlock({
  children, className, label,
}: { children: string; className?: string; label?: string }) {
  return (
    <figure aria-label={label} className="m-0">
      <pre className={cx('code', className)}>
        <code>{children}</code>
      </pre>
    </figure>
  )
}
