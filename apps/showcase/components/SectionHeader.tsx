import type { ReactNode, Ref } from 'react'
import { cx } from './cx.ts'

export function PageHeader({
  title, subtitle, actions, eyebrow, className,
}: { title: string; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode; className?: string }) {
  return (
    <header className={cx('mb-10 flex flex-wrap items-end justify-between gap-x-6 gap-y-4', className)}>
      <div className="min-w-0 max-w-2xl">
        {eyebrow && <p className="mb-1.5 text-xs font-medium text-ex-ink3">{eyebrow}</p>}
        <h1 className="text-xl font-semibold tracking-tight text-ex-ink sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1.5 text-base text-ex-ink2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

/** Section title row: optional step number, title, one-line description, actions on the right. */
export function SectionHeader({
  title, description, actions, step, id, headingRef, tabIndex, level = 2,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  step?: number
  /** id of the heading element (the <Section> wrapper sets it for you). */
  id?: string
  headingRef?: Ref<HTMLHeadingElement>
  tabIndex?: number
  level?: 2 | 3
}) {
  const Tag = level === 2 ? 'h2' : 'h3'
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 items-start gap-3">
        {step != null && (
          <span aria-hidden="true" className="mt-px grid h-6 w-6 shrink-0 place-items-center rounded-full border border-ex-line2 text-xs font-medium tabular-nums text-ex-ink2">{step}</span>
        )}
        <div className="min-w-0">
          <Tag id={id} ref={headingRef} tabIndex={tabIndex} className="text-md font-semibold leading-6 tracking-tight text-ex-ink focus:outline-none">
            {step != null && <span className="sr-only">Step {step}: </span>}
            {title}
          </Tag>
          {description && <p className="mt-0.5 text-sm text-ex-ink2">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/**
 * A page section: a labelled landmark region with its heading. `id` becomes the anchor (#id) and the heading
 * id is `${id}-title`. Page tracks fill the children and keep the id so links and tests stay stable.
 */
export function Section({
  id, title, description, actions, step, level = 2, className, children,
}: {
  id: string
  title: string
  description?: ReactNode
  actions?: ReactNode
  step?: number
  level?: 2 | 3
  className?: string
  children?: ReactNode
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={cx('scroll-mt-20', level === 2 ? 'mb-12' : 'mb-8', className)}>
      <SectionHeader id={`${id}-title`} title={title} description={description} actions={actions} step={step} level={level} />
      {children}
    </section>
  )
}
