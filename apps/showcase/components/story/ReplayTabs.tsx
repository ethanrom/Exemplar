'use client'

import { useState } from 'react'
import { Button } from '../Button.tsx'
import { Tabs, type TabItem } from '../Tabs.tsx'

/**
 * The event picker of the Live replay: previous and next buttons, plus the five events as tabs (arrow keys, Home and
 * End move between them). The panels are rendered on the server and handed in; every panel stays in the page.
 */
export function ReplayTabs({ tabs, label, defaultId }: { tabs: TabItem[]; label: string; defaultId?: string }) {
  const [value, setValue] = useState(defaultId ?? tabs[0]?.id ?? '')
  const index = Math.max(0, tabs.findIndex((t) => t.id === value))
  const go = (to: number) => {
    const target = tabs[to]
    if (target) setValue(target.id)
  }
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ex-ink2" aria-live="polite">
          Event <span className="tabular-nums text-ex-ink">{index + 1}</span> of <span className="tabular-nums text-ex-ink">{tabs.length}</span>
        </p>
        <div className="flex items-center gap-2">
          <Button size="sm" icon="chevron-right" className="[&>svg]:rotate-180" disabled={index === 0} onClick={() => go(index - 1)}>
            Previous event
          </Button>
          <Button size="sm" trailingIcon="chevron-right" disabled={index === tabs.length - 1} onClick={() => go(index + 1)}>
            Next event
          </Button>
        </div>
      </div>
      <Tabs tabs={tabs} label={label} value={value} onValueChange={setValue} />
    </div>
  )
}
