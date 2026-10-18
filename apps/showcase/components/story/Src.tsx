import type { ReactNode } from 'react'

/**
 * Marks a figure with where it came from (SPEC section 10.4): `data-src` holds the data file and path, so the
 * number audit can tell a bound figure from a typed one. Renders no extra visual.
 */
export function Src({ src, children, className }: { src: string; children: ReactNode; className?: string }) {
  return <span data-src={src} className={className}>{children}</span>
}
