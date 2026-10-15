import type { ReactNode } from 'react'

export type IconName =
  | 'check' | 'cross' | 'plus' | 'minus' | 'question' | 'warning' | 'info' | 'play' | 'stop' | 'clock'
  | 'chevron' | 'chevron-right' | 'spark' | 'link' | 'camera' | 'bolt' | 'shuffle' | 'upload' | 'refresh'
  | 'shield' | 'pause' | 'film' | 'eye' | 'flag' | 'external' | 'dot' | 'diamond'

const PATHS: Record<IconName, ReactNode> = {
  check: <path d="M3 8.5l3.2 3.2L13 4.8" />,
  cross: <path d="M4 4l8 8M12 4l-8 8" />,
  plus: <path d="M8 3v10M3 8h10" />,
  minus: <path d="M3 8h10" />,
  question: (
    <>
      <path d="M6 6.2a2 2 0 1 1 3 1.7c-.7.4-1 .8-1 1.6" />
      <path d="M8 12v.01" />
    </>
  ),
  warning: (
    <>
      <path d="M8 2.2l6.2 10.8H1.8z" />
      <path d="M8 6.5v3M8 11.3v.01" />
    </>
  ),
  info: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 7.2v4M8 5v.01" />
    </>
  ),
  play: <path d="M5 3.5l7.5 4.5L5 12.5z" />,
  stop: <rect x="4" y="4" width="8" height="8" rx="1" />,
  pause: <path d="M5.5 3.5v9M10.5 3.5v9" />,
  clock: (
    <>
      <circle cx="8" cy="8" r="6" />
      <path d="M8 4.6V8l2.4 1.4" />
    </>
  ),
  chevron: <path d="M4 6l4 4 4-4" />,
  'chevron-right': <path d="M6 4l4 4-4 4" />,
  spark: <path d="M8 1.5l1.6 4.9 4.9 1.6-4.9 1.6L8 14.5 6.4 9.6 1.5 8l4.9-1.6z" />,
  link: (
    <>
      <path d="M6.8 9.2a2.6 2.6 0 0 0 3.7 0l2-2a2.6 2.6 0 0 0-3.7-3.7l-.8.8" />
      <path d="M9.2 6.8a2.6 2.6 0 0 0-3.7 0l-2 2a2.6 2.6 0 0 0 3.7 3.7l.8-.8" />
    </>
  ),
  camera: (
    <>
      <rect x="1.8" y="4.5" width="12.4" height="8.5" rx="1.6" />
      <circle cx="8" cy="8.7" r="2.2" />
      <path d="M5.5 4.5l.8-1.6h3.4l.8 1.6" />
    </>
  ),
  bolt: <path d="M9 1.8L3.5 9H8l-1 5.2L12.5 7H8z" />,
  shuffle: (
    <>
      <path d="M2 4.5h2.2c2.8 0 3.6 6.5 6.4 6.5H14M2 11h2.2c1 0 1.7-.9 2.3-1.9M14 4.5h-3.4c-1 0-1.7.9-2.3 1.9" />
      <path d="M12 2.8l2 1.7-2 1.7M12 9.3l2 1.7-2 1.7" />
    </>
  ),
  upload: <path d="M8 11V3M4.8 6.2L8 3l3.2 3.2M2.5 11.5v1.8h11v-1.8" />,
  refresh: (
    <>
      <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
      <path d="M13.6 2.4v2.9h-2.9" />
    </>
  ),
  shield: (
    <>
      <path d="M8 1.8l5 1.9v4c0 3.1-2.1 5.2-5 6.5-2.9-1.3-5-3.4-5-6.5v-4z" />
      <path d="M5.8 8l1.6 1.6 3-3.2" />
    </>
  ),
  film: (
    <>
      <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
      <path d="M5 2.5v11M11 2.5v11M2 6h3M2 10h3M11 6h3M11 10h3" />
    </>
  ),
  eye: (
    <>
      <path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z" />
      <circle cx="8" cy="8" r="1.8" />
    </>
  ),
  flag: <path d="M3.5 14V2.5M3.5 3h8l-1.6 2.6L11.5 8h-8" />,
  external: <path d="M9 2.5h4.5V7M13.5 2.5L7.5 8.5M6.5 3.5H3a.5.5 0 0 0-.5.5v8.5a.5.5 0 0 0 .5.5h8.5a.5.5 0 0 0 .5-.5V9.5" />,
  dot: <circle cx="8" cy="8" r="3" fill="currentColor" />,
  diamond: <path d="M8 2.5l5 5.5-5 5.5L3 8z" fill="currentColor" />,
}

export function Icon({ name, className = 'h-4 w-4', title }: { name: IconName; className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      className={`${className} shrink-0`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? 'img' : undefined}
      aria-label={title}
    >
      {PATHS[name]}
    </svg>
  )
}
