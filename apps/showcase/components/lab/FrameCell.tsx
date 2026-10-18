import type { CSSProperties } from 'react'
import { cx } from '../cx.ts'
import { Icon } from '../Icon.tsx'

/**
 * One frame of a clip's 4x4 frame sheet (SPEC 9.1: 16 frames of 320x180, row-major, in time order), shown whole. The
 * frame keeps Ring's watermark: nothing is ever drawn on it. Badges and labels belong below it, never over it.
 * Without a sheet (the SANDBOX_MEDIA=trace variant) a neutral tile stands in.
 */
export function FrameCell({
  sheet, index, label, className, style, decorative = false,
}: { sheet?: string; index: number; label: string; className?: string; style?: CSSProperties; decorative?: boolean }) {
  if (!sheet) return <TraceOnlyTile className={className} />
  const col = index % 4
  const row = Math.floor(index / 4)
  return (
    <div
      {...(decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': label })}
      className={cx('aspect-video w-full overflow-hidden rounded-md border border-ex-line bg-ex-raised bg-no-repeat', className)}
      style={{
        backgroundImage: `url(${sheet})`,
        backgroundSize: '400% 400%',
        backgroundPosition: `${(col / 3) * 100}% ${(row / 3) * 100}%`,
        ...style,
      }}
    />
  )
}

/** A poster image of a clip (640 px wide), shown whole. */
export function Poster({ src, label, className, compact = false }: { src?: string; label: string; className?: string; compact?: boolean }) {
  if (!src) return <TraceOnlyTile className={className} compact={compact} />
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={label} loading="lazy" decoding="async" width={640} height={360} className={cx('aspect-video w-full rounded-md border border-ex-line bg-ex-raised object-cover', className)} />
  )
}

/** The stand-in for a recording whose frames are not shown in this build (SPEC 9.3). */
export function TraceOnlyTile({ className, compact = false }: { className?: string; compact?: boolean }) {
  if (compact) {
    return (
      <div className={cx('grid aspect-video w-full place-items-center rounded-md border border-ex-line bg-ex-raised text-ex-ink3', className)} title="Ring Developer Playground recording: frames not shown">
        <Icon name="film" className="h-4 w-4" />
        <span className="sr-only">Ring Developer Playground recording: frames not shown</span>
      </div>
    )
  }
  return (
    <div className={cx('grid aspect-video w-full place-items-center rounded-md border border-ex-line bg-ex-raised p-2 text-center text-xs text-ex-ink3', className)}>
      <span className="inline-flex flex-col items-center gap-1">
        <Icon name="film" className="h-4 w-4" />
        Ring Developer Playground recording: frames not shown
      </span>
    </div>
  )
}
