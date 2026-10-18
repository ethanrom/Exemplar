import type { LiveDecision, LiveDoc } from '@/lib/data/types.ts'

// Derivations over the recorded data. Counts are computed here, once, so Home and Live say the same thing.

export type LiveClass = LiveDoc['events'][number]['class']

export const CLASS_NOUN: Record<LiveClass, string> = { pg_package: 'package', pg_vehicle: 'vehicle', pg_bird: 'bird' }
export const CLASS_TITLE: Record<LiveClass, string> = { pg_package: 'Package', pg_vehicle: 'Vehicle', pg_bird: 'Birds' }

/** The two deployed rules, by the slugs the export uses. */
export const PACKAGE_RULE = 'package-deployed'
export const VEHICLE_RULE = 'vehicle-deployed'
export const RULE_NAME: Record<string, string> = { [PACKAGE_RULE]: 'Package rule', [VEHICLE_RULE]: 'Vehicle rule' }

export const decisionOf = (decisions: LiveDecision[], rule: string): LiveDecision | undefined => decisions.find((d) => d.rule === rule)

export type ClassOutcome = {
  cls: LiveClass
  /** Recorded events of this class. */
  events: number
  /** How many of them fired each deployed rule. */
  packageFired: number
  vehicleFired: number
  /** The first event of the class, in recorded order (used for its still). */
  first: LiveDoc['events'][number]
}

/** One row per class, in the order package, vehicle, bird, with how often each deployed rule fired. */
export function classOutcomes(live: LiveDoc): ClassOutcome[] {
  const order: LiveClass[] = ['pg_package', 'pg_vehicle', 'pg_bird']
  const out: ClassOutcome[] = []
  for (const cls of order) {
    const events = live.events.filter((e) => e.class === cls)
    const first = events[0]
    if (!first) continue
    out.push({
      cls,
      events: events.length,
      packageFired: events.filter((e) => decisionOf(e.decisions, PACKAGE_RULE)?.fired).length,
      vehicleFired: events.filter((e) => decisionOf(e.decisions, VEHICLE_RULE)?.fired).length,
      first,
    })
  }
  return out
}

/** The playground class of a library alias (pg-pkg-07 is a package recording), or null for other clips. */
export function playgroundClass(alias: string): LiveClass | null {
  if (alias.startsWith('pg-pkg-')) return 'pg_package'
  if (alias.startsWith('pg-veh-')) return 'pg_vehicle'
  if (alias.startsWith('pg-bird-')) return 'pg_bird'
  return null
}

export type BacktestCount = { cls: LiveClass; fired: number; total: number }

/** Per-class counts of a rule's backtest over the Playground recordings (fired = the recorded `matched`). */
export function playgroundBacktest(backtest: { alias: string; matched: boolean }[]): BacktestCount[] {
  const order: LiveClass[] = ['pg_package', 'pg_vehicle', 'pg_bird']
  return order.map((cls) => {
    const rows = backtest.filter((b) => playgroundClass(b.alias) === cls)
    return { cls, fired: rows.filter((r) => r.matched).length, total: rows.length }
  })
}
