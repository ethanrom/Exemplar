'use client'

import { Badge } from '../Badge.tsx'
import { badgeModel } from '../../lib/synth/z3/model.ts'
import { Z3_SHIPPED } from './assets.ts'
import { useZ3 } from './Z3Provider.tsx'

/**
 * The Z3 verdict of one candidate, to sit in its row of tags. "Z3 agrees" appears only when Z3 finished for the Lab's current
 * request and its answer is identical to the one shown; any other outcome says exactly what differs, or that the rule was not
 * checked. An error or a cancelled run shows nothing. Renders nothing while Z3 is off or in a build without Z3.
 */
export function Z3Badge({ itemKey }: { itemKey: string }) {
  const ctl = useZ3()
  if (!Z3_SHIPPED || ctl === null || !ctl.enabled || ctl.state.phase !== 'ready') return null
  const m = badgeModel(ctl.run.results[itemKey], ctl.run.status === 'running')
  if (m === null) return null
  return (
    <>
      <Badge tone={m.tone} icon={m.icon} title={m.title}>{m.label}</Badge>
      {m.lines.length > 0 && (
        <span data-z3="detail" className="basis-full text-xs text-ex-ink2">
          {m.lines.join('; ')}
        </span>
      )}
    </>
  )
}
