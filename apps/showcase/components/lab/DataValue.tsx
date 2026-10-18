import type { ReactNode } from 'react'

/**
 * Marks a value as coming from the exported data or from a computation on it. `src` names the file or function it
 * came from; the number audit (SPEC 10.4) reads `data-src`. Renders no styling of its own.
 */
export function DV({ src, children, className }: { src: string; children: ReactNode; className?: string }) {
  return <span data-src={src} className={className}>{children}</span>
}
