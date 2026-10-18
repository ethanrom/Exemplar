import { Fragment } from 'react'
import { Card, Icon } from '@/components/index.ts'

// An event flow as an ordered list: numbered steps with arrows between them on wide screens, a plain vertical list
// on a phone. A list reads in order for assistive technology too, so no separate text alternative is needed.
export type FlowStep = { title: string; detail?: string }

export function FlowSteps({ steps, label }: { steps: FlowStep[]; label: string }) {
  return (
    <ol aria-label={label} className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-stretch">
      {steps.map((s, i) => (
        <Fragment key={s.title}>
          <Card as="li" padding="sm" className="min-w-0 lg:basis-[calc(25%-1.5rem)] lg:grow">
            <p className="flex items-start gap-2 text-sm font-medium text-ex-ink">
              <span aria-hidden="true" className="mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full border border-ex-line2 text-xs tabular-nums text-ex-ink2">{i + 1}</span>
              <span className="min-w-0">{s.title}</span>
            </p>
            {s.detail && <p className="mt-1 pl-7 text-xs text-ex-ink2">{s.detail}</p>}
          </Card>
          {i < steps.length - 1 && (
            <li aria-hidden="true" className="hidden items-center text-ex-ink3 lg:flex"><Icon name="arrow-right" className="h-4 w-4" /></li>
          )}
        </Fragment>
      ))}
    </ol>
  )
}
