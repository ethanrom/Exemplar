'use client'

import Link from 'next/link'
import { useApp } from '../_lib/app'
import { useApi } from '../_lib/hooks'
import type { RuleSummary } from '../_lib/types'
import { GuaranteeBadge } from './CalibrationPanel'
import { Icon } from './Icon'
import { RuleHeadline } from './RuleCard'

/** A real rule from the engine (the deployed one, if any) shown on the home page. Renders nothing if there is none. */
export function HomeExample() {
  const { concepts } = useApp()
  const ruleId = concepts.find((c) => c.deployed_rule_id)?.deployed_rule_id ?? null
  const rule = useApi<RuleSummary>(ruleId ? `/rules/${encodeURIComponent(ruleId)}` : null)
  const r = rule.data
  if (!r) return null
  return (
    <aside aria-label="A rule Exemplar learned" className="rounded-xl border border-ex-line bg-ex-bg/80 p-4">
      <p className="flex items-center gap-2 text-sm font-medium text-ex-accent"><Icon name="bolt" /> A rule it learned, live right now</p>
      <div className="mt-2"><RuleHeadline rule={r} /></div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {r.calibration && <GuaranteeBadge cal={r.calibration} />}
        <Link href={`/rule?rule=${encodeURIComponent(r.id)}`} className="text-sm text-ex-info underline">See its backtest</Link>
      </div>
    </aside>
  )
}
