'use client'

import Link from 'next/link'
import { useApp } from '../_lib/app'
import { useApi } from '../_lib/hooks'
import type { Firing, RuleSummary } from '../_lib/types'
import { GuaranteeBadge } from './CalibrationPanel'
import { Dsl } from './Dsl'
import { Icon } from './Icon'
import { Skeleton, StatusDot } from './ui'

/** A real rule from the engine (the deployed one, if any) shown on the home page. Renders nothing if there is none. */
export function HomeExample() {
  const { concepts, conceptsLoading } = useApp()
  const ruleId = concepts.find((c) => c.deployed_rule_id)?.deployed_rule_id ?? null
  const rule = useApi<RuleSummary>(ruleId ? `/rules/${encodeURIComponent(ruleId)}` : null)
  const firings = useApi<Firing[]>(ruleId ? '/monitor/firings?limit=30' : null)
  const r = rule.data
  if (conceptsLoading && !ruleId) return <Skeleton className="h-64 rounded-xl" label="Loading the deployed rule" />
  if (!r) return null
  const fired = (firings.data ?? []).filter((f) => f.rule_id === r.id && f.fired).length
  return (
    <aside aria-label="A rule Exemplar learned" className="relative overflow-hidden rounded-xl border border-ex-line2 bg-ex-panel">
      <div className="flex items-center justify-between gap-3 border-b border-ex-line px-5 py-3">
        <p className="flex items-center gap-2 text-xs font-medium text-ex-ink2">
          <StatusDot tone="pos" pulse>A rule it learned</StatusDot>
          <span className="text-ex-ink3">· live right now</span>
        </p>
        {fired > 0 && <p className="text-xs text-ex-ink3"><span className="tabular-nums text-ex-ink2">{fired}</span> alert{fired === 1 ? '' : 's'} so far</p>}
      </div>
      <div className="px-5 pb-5 pt-4">
        <p className="text-lg font-medium leading-snug tracking-tight text-ex-ink">{r.english}</p>
        <p className="mt-4 rounded-lg border border-ex-line bg-ex-bg px-3.5 py-3 font-mono text-[13px] leading-6" aria-label="Rule in the Exemplar logic language">
          <Dsl text={r.dsl_text} />
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          {r.calibration && <GuaranteeBadge cal={r.calibration} />}
          <Link href={`/rule?rule=${encodeURIComponent(r.id)}`} className="inline-flex items-center gap-1 rounded text-sm font-medium text-ex-accent-ink hover:text-ex-ink">
            See its backtest <Icon name="arrow-right" className="h-3.5 w-3.5" />
          </Link>
        </div>
      </div>
    </aside>
  )
}
