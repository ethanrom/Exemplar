// Props the server page hands to the client chapters (plain JSON; the data folder is read on the server at build time).
import type { CalDoc, ClipCard, LiveDoc, RuleDoc, RunDoc, TraceJson } from '../../../lib/data/types.ts'

/** A rule without the fields the How page does not use (the backtest list alone is 64 entries). */
export type SlimRule = Omit<RuleDoc, 'backtest' | 'ast'>

export type HowRun = {
  slug: 'p1-playground'
  title: string
  /** The recorded rule shown on the number line: the deployed rule of the P1 run. */
  rule: SlimRule
  examples: RunDoc['examples']
}

export type HowData = {
  /** Every trace the chapters evaluate, by clip alias. */
  traces: Record<string, TraceJson>
  /** Library cards of every clip the chapters mention. */
  cards: Record<string, ClipCard>
  live: LiveDoc
  /** Deployed rules by slug (package-deployed, vehicle-deployed). */
  deployed: Record<string, SlimRule>
  /** P1's recorded events, for chapter 2. */
  p1: Pick<RunDoc, 'slug' | 'title' | 'events' | 'proposer_note' | 'candidates' | 'proposals_by_round'>
  runs: HowRun[]
  cal: CalDoc
  /** The package-deployed rule's calibration object, verbatim (chapter 5 checks the recomputation against it). */
  packageRule: SlimRule
}
