import type { ReactNode } from 'react'
import { cx } from './cx.ts'

/**
 * Marks where a page track puts its content. Delete it when the section is real. `owner` names the track
 * that fills it (SH-G, SH-H, SH-I); `data-placeholder` lets QA find any that were left behind.
 */
export function Placeholder({
  owner, children, className,
}: { owner?: string; children?: ReactNode; className?: string }) {
  return (
    <div
      data-placeholder={owner ?? ''}
      className={cx('rounded-xl border border-dashed border-ex-edge bg-ex-panel px-4 py-5 text-sm text-ex-ink2', className)}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-ex-ink3">
        Placeholder{owner ? ` for ${owner}` : ''}
      </p>
      {children && <div className="mt-1.5 max-w-prose">{children}</div>}
    </div>
  )
}
