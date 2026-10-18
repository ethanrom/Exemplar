import type { ReactNode } from 'react'
import type { LiveDecision, RuleDoc } from '@/lib/data/types.ts'
import { Badge } from '../Badge.tsx'
import { Card } from '../Card.tsx'
import { DslBlock } from '../CodeBlock.tsx'
import { cx } from '../cx.ts'
import { Icon } from '../Icon.tsx'
import { Src } from './Src.tsx'
import { fmtPlain, fmtScore, ordinal, pluralise } from './format.ts'
import { CLASS_NOUN, type BacktestCount } from './outcomes.ts'

/** Holes the engine measures in seconds (window lengths); the others are hours. */
const HOLE_UNIT = new Set(['d', 'a', 'b'])

export const SELECTION_LABEL: Record<NonNullable<RuleDoc['selection']>, string> = {
  chosen_by_user_and_deployed: 'Chosen by the user and deployed',
  selected_for_display_as_demo_equivalent: 'Selected for display because it means the same as the deployed rule',
}

/** "Ranked 3rd of 6 by description length", straight from the recorded candidates event. `bare` drops the word "Ranked". */
export function RankText({ rule, bare = false }: { rule: RuleDoc; bare?: boolean }) {
  const r = rule.recorded_rank
  if (!r) return null
  return (
    <Src src={`rules/${rule.slug}.json#recorded_rank`}>
      {bare ? '' : 'Ranked '}{ordinal(r.position)} of {r.of} by description length
    </Src>
  )
}

/**
 * A rule as the site shows it: the English printed from the rule by code, the rule text highlighted, and where it
 * stands (recorded rank, who chose it). Text is rendered verbatim from the data.
 */
export function RuleCard({
  rule, title, headingLevel = 'h3', size = 'md', showSketch = false, showRank = true, footer, className,
}: {
  rule: RuleDoc
  title?: string
  headingLevel?: 'h2' | 'h3' | 'h4'
  size?: 'md' | 'lg'
  showSketch?: boolean
  /** The recorded-rank badge; the Home page leaves it out and shows who chose the rule. */
  showRank?: boolean
  footer?: ReactNode
  className?: string
}) {
  const Heading = headingLevel
  const holes = Object.entries(rule.holes)
  return (
    <Card className={className} padding={size === 'lg' ? 'lg' : 'md'}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        {title && <Heading className="card-title mr-1">{title}</Heading>}
        {showRank && rule.recorded_rank && <Badge tone="info" icon="layers"><RankText rule={rule} /></Badge>}
        {rule.selection && (
          <span className="inline-flex min-w-0 items-start gap-1 rounded bg-ex-accent-soft px-1.5 py-0.5 text-xs font-medium text-ex-accent-ink">
            <Icon name="check" className="mt-0.5 h-3 w-3" />
            <span className="min-w-0">{SELECTION_LABEL[rule.selection]}</span>
          </span>
        )}
      </div>
      <p
        data-src={`rules/${rule.slug}.json#english`}
        className={cx('mt-3 font-medium tracking-tight text-ex-ink', size === 'lg' ? 'text-lg sm:text-xl' : 'text-md')}
      >
        {rule.english}
      </p>
      <div className="mt-4">
        <DslBlock text={rule.dsl_text} size={size === 'lg' ? 'lg' : 'md'} label="The rule in the Exemplar rule language" />
      </div>
      {showSketch && (
        <div className="mt-3 text-sm text-ex-ink2">
          <p>
            The agent’s sketch left {holes.length === 1 ? 'one blank' : `${holes.length} blanks`}; the solver filled{' '}
            {holes.length === 1 ? 'it' : 'them'} in:{' '}
            {holes.map(([name, value], i) => (
              <span key={name}>
                {i > 0 && ', '}
                <code className="font-mono text-xs text-ex-ink">{name} = {value}{HOLE_UNIT.has(name) ? ' s' : ''}</code>
              </span>
            ))}
            .
          </p>
          <div className="mt-1.5"><DslBlock text={rule.sketch_text} size="sm" label="The agent’s sketch, with its blank" /></div>
        </div>
      )}
      {footer && <div className="mt-4 text-sm text-ex-ink2">{footer}</div>}
    </Card>
  )
}

/** One deployed rule's recorded verdict on one event. */
export function RuleVerdict({
  name, english, decision, srcBase, children,
}: { name: string; english: string; decision: LiveDecision; srcBase: string; children?: ReactNode }) {
  const fired = decision.fired
  return (
    <Card as="article" tone={fired ? 'pos' : 'neutral'} className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="card-title">{name}</h4>
        <Badge tone={fired ? 'pos' : 'neutral'} icon={fired ? 'check' : 'minus'}>{fired ? 'Fired' : 'Dropped'}</Badge>
      </div>
      <p className="mt-1 text-sm text-ex-ink2">{english}</p>
      <dl className="mt-3 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-ex-line bg-ex-line text-center">
        <div className="bg-ex-panel px-2 py-2">
          <dt className="text-xs text-ex-ink3">Score</dt>
          <dd className="mt-0.5 text-md font-semibold tabular-nums text-ex-ink" data-src={`${srcBase}.score`}>{fmtScore(decision.score)}</dd>
        </div>
        <div className="bg-ex-panel px-2 py-2">
          <dt className="text-xs text-ex-ink3">Threshold τ</dt>
          <dd className="mt-0.5 text-md font-semibold tabular-nums text-ex-ink" data-src={`${srcBase}.tau`}>{fmtPlain(decision.tau)}</dd>
        </div>
        <div className="bg-ex-panel px-2 py-2">
          <dt className="text-xs text-ex-ink3">Stage</dt>
          <dd className="mt-0.5 text-md font-semibold tabular-nums text-ex-ink" data-src={`${srcBase}.stage`}>{decision.stage}</dd>
        </div>
      </dl>
      {children && <div className="mt-3">{children}</div>}
    </Card>
  )
}

/** Verdict chip for a compact table cell or tile: icon and word, never colour alone. */
export function FiredChip({ fired, label }: { fired: boolean; label?: string }) {
  return (
    <Badge tone={fired ? 'pos' : 'neutral'} icon={fired ? 'check' : 'minus'}>
      {label ? `${label}: ` : ''}{fired ? 'fired' : 'dropped'}
    </Badge>
  )
}

/** Bars of how often a rule fired on each class of Playground recording. */
export function BacktestCounts({ counts, srcBase }: { counts: BacktestCount[]; srcBase: string }) {
  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {counts.map((c) => (
        <li key={c.cls}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-ex-ink2">{CLASS_NOUN[c.cls][0]?.toUpperCase()}{CLASS_NOUN[c.cls].slice(1)} {pluralise(c.total, 'recording')}</span>
            <span className="tabular-nums text-ex-ink" data-src={`${srcBase}#${c.cls}`}>
              fired on {c.fired} of {c.total}
            </span>
          </div>
          <div aria-hidden="true" className="mt-1 h-2 overflow-hidden rounded bg-white/[0.06]">
            <div className="h-full rounded bg-ex-accent-ink" style={{ width: `${c.total ? (c.fired / c.total) * 100 : 0}%` }} />
          </div>
        </li>
      ))}
    </ul>
  )
}

