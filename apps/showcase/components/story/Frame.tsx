import type { ReactNode } from 'react'
import { cx } from '../cx.ts'
import { Icon } from '../Icon.tsx'
import type { ClipCard } from '@/lib/data/types.ts'
import { fmtSeconds } from './format.ts'

// Frames are shown exactly as exported (SPEC 9.1): full frame, never cropped, nothing drawn over the top of the
// image (the Ring watermark and its Device-ID line live there). Captions, badges and links go below the image.

const FRAME_BOX = 'block h-auto w-full rounded-lg border border-ex-line bg-ex-raised'

/** True when this build shows the clip's pixels. */
export const hasFrames = (card: ClipCard): boolean => card.media === 'frames' && Boolean(card.poster)

/** The neutral stand-in used when a clip's frames are not shown (SANDBOX_MEDIA=trace): the explanation stays. */
export function TraceOnlyTile({ card, className }: { card: ClipCard; className?: string }) {
  return (
    <div
      className={cx('flex aspect-video w-full flex-col items-start justify-center gap-1.5 rounded-lg border border-dashed border-ex-line2 bg-ex-panel px-4 py-3', className)}
      role="group"
      aria-label={`${card.title}: frames not shown`}
    >
      <p className="flex items-center gap-1.5 text-sm font-medium text-ex-ink">
        <Icon name="image" className="h-4 w-4 text-ex-ink3" />
        Ring Developer Playground recording: frames not shown
      </p>
      <p className="text-sm text-ex-ink2">Claude’s reading of this clip is below.</p>
    </div>
  )
}

/** One still (the poster) at its native 16:9, full width of its container. */
export function Still({ card, priority = false, sizes, className }: { card: ClipCard; priority?: boolean; sizes?: string; className?: string }) {
  if (!hasFrames(card)) return <TraceOnlyTile card={card} className={className} />
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static export with unoptimized images
    <img
      src={card.poster}
      width={640}
      height={360}
      sizes={sizes}
      alt={`Still frame from ${card.title}`}
      loading={priority ? 'eager' : 'lazy'}
      decoding="async"
      className={cx(FRAME_BOX, className)}
    />
  )
}

/** All sixteen frames Claude read, as exported: a 4 by 4 sheet in time order, row by row. */
export function FrameSheet({ card, caption }: { card: ClipCard; caption?: ReactNode }) {
  if (!hasFrames(card) || !card.sheet) return <TraceOnlyTile card={card} />
  const times = card.sheet_times_ms
  const first = times[0]
  const last = times[times.length - 1]
  const range = first !== undefined && last !== undefined ? `, from ${fmtSeconds(first, 2)} to ${fmtSeconds(last, 2)}` : ''
  return (
    <figure className="m-0">
      {/* eslint-disable-next-line @next/next/no-img-element -- static export with unoptimized images */}
      <img
        src={card.sheet}
        width={1280}
        height={720}
        alt={`The ${times.length || 16} frames Claude read from ${card.title}, in time order, left to right and top to bottom${range}`}
        loading="lazy"
        decoding="async"
        className={FRAME_BOX}
      />
      {caption && <figcaption className="mt-2 text-sm text-ex-ink2">{caption}</figcaption>}
    </figure>
  )
}

/**
 * A few whole frames from a sheet, side by side, each labelled with its time. Used only for windows of the CC BY
 * doorstep video (no Ring watermark there). Every cell is a complete 16:9 frame of the sheet; none is cropped.
 */
export function FrameStrip({ card, cells, className }: { card: ClipCard; cells: number[]; className?: string }) {
  if (!card.sheet) return <TraceOnlyTile card={card} />
  const sheet = card.sheet
  return (
    <ol className={cx('grid list-none grid-cols-3 gap-1.5 p-0', className)}>
      {cells.map((cell) => {
        const col = cell % 4
        const row = Math.floor(cell / 4)
        const t = card.sheet_times_ms[cell]
        const when = t === undefined ? `frame ${cell + 1}` : fmtSeconds(t)
        return (
          <li key={cell} className="m-0 min-w-0">
            <div
              role="img"
              aria-label={`${card.title}, frame ${cell + 1} of 16, at ${when}`}
              className="aspect-video w-full rounded-md border border-ex-line bg-ex-raised bg-no-repeat"
              style={{ backgroundImage: `url(${sheet})`, backgroundSize: '400% 400%', backgroundPosition: `${(col * 100) / 3}% ${(row * 100) / 3}%` }}
            />
            <p className="mt-1 text-xs tabular-nums text-ex-ink3">{when}</p>
          </li>
        )
      })}
    </ol>
  )
}
