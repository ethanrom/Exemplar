import { Fragment, type ReactNode } from 'react'

// Syntax highlighting for the Exemplar rule language (docs/DSL.md). Presentation only: the text always
// comes from the engine (`dsl_text`, `sketch`, `WitnessSpan.text`) and is never rewritten here.

const KEYWORDS = new Set(['exists', 'when', 'and', 'or', 'not', 'in', 'hour', 'subtype', 'device'])
const TEMPORAL = new Set(['eventually', 'always', 'then', 'holds_for'])
const TYPES = new Set(['Entity', 'Person', 'Vehicle', 'Package', 'Animal', 'Object', 'Carryable', 'Zone', 'Label'])
const ZONES = new Set(['door', 'porch', 'steps', 'yard', 'driveway', 'sidewalk', 'street', 'dock'])

type Kind = 'kw' | 'temporal' | 'type' | 'zone' | 'num' | 'hole' | 'pred' | 'var' | 'punct' | 'space'

const CLASS: Record<Kind, string> = {
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

export function tokenizeDsl(text: string): { kind: Kind; text: string }[] {
  // Variables are whatever the rule declares as `name: Type`; short lower-case names are variables too
  // (witness fragments carry no declaration).
  const declared = new Set<string>()
  for (const m of Array.from(text.matchAll(/([A-Za-z_]\w*)\s*:\s*[A-Z]\w*/g))) declared.add(m[1])
  const out: { kind: Kind; text: string }[] = []
  for (const m of Array.from(text.matchAll(TOKEN))) {
    const [raw, space, hole, num, word, punct] = m
    if (space) out.push({ kind: 'space', text: raw })
    else if (hole) out.push({ kind: 'hole', text: raw })
    else if (num) out.push({ kind: 'num', text: raw })
    else if (word) {
      const next = text[(m.index ?? 0) + raw.length]
      let kind: Kind
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
export function Dsl({ text, className = '' }: { text: string; className?: string }) {
  const toks = tokenizeDsl(text)
  const nodes: ReactNode[] = toks.map((t, i) =>
    t.kind === 'space' ? <Fragment key={i}>{t.text}</Fragment> : <span key={i} className={CLASS[t.kind]}>{t.text}</span>,
  )
  return <span className={className}>{nodes}</span>
}

/** The rule line as a hero element: monospace block with the highlighted rule. */
export function DslBlock({ text, className = '', size = 'md' }: { text: string; className?: string; size?: 'sm' | 'md' | 'lg' }) {
  const sz = size === 'lg' ? 'px-4 py-3.5 text-[15px] leading-7' : size === 'sm' ? 'px-3 py-2 text-xs leading-5' : ''
  return (
    <pre className={`code ${sz} ${className}`} aria-label="Rule in the Exemplar logic language">
      <code><Dsl text={text} /></code>
    </pre>
  )
}
