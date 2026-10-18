// What the server page hands to the Lab's client components (plain JSON, read from the export at build time).
import type { CalDoc, ClipCard, CreditEntry, CuratedDoc, RuleDoc, RunDoc, Sketch } from '../../../lib/data/types.ts'

export type PresetSlug = 'p1-playground'
export type Mode = PresetSlug | 'free'

/** A rule without its AST (the Lab parses the DSL text); the backtest is kept for the cross-check. */
export type LabRule = Omit<RuleDoc, 'ast'>

export type CreditBrief = Pick<CreditEntry, 'id' | 'group' | 'title'> & { basis: CreditEntry['permission']['basis'] }

export type LabProps = {
  library: ClipCard[]
  credits: Record<string, CreditBrief>
  runs: Record<PresetSlug, RunDoc>
  /** Every candidate rule of the preset run, by slug. */
  rules: Record<string, LabRule>
  curated: CuratedDoc
  sketches: Sketch[]
  cal: CalDoc
}
