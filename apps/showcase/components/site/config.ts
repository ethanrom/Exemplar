// Site-wide configuration: the seven pages, the release flag and the replay disclosure.
// Plain TypeScript with no framework imports at runtime, so Node's test runner can import it too
// (relative imports carry explicit .ts extensions; see lib/smoke.test.ts).

export const RELEASES = ['R1', 'R2', 'R3', 'R4'] as const
export type Release = (typeof RELEASES)[number]

export const SANDBOX_MEDIA_MODES = ['frames', 'trace'] as const
export type SandboxMedia = (typeof SANDBOX_MEDIA_MODES)[number]

export type PageId = 'home' | 'lab' | 'how' | 'live' | 'evidence' | 'platform' | 'credits'

export type PageInfo = {
  id: PageId
  /** Route with the trailing slash the static export uses. */
  href: string
  /** Navigation label. */
  label: string
  /** Page title (h1). */
  title: string
  /** One-line purpose, shown under the title. */
  purpose: string
  /** First release that includes the page (SPEC section 3). */
  since: Release
}

/** The seven pages in navigation order (SPEC section 3). */
export const PAGES: readonly PageInfo[] = [
  {
    id: 'home', href: '/', label: 'Home', since: 'R1',
    title: 'Teach your Ring camera by example',
    purpose: 'The idea in 60 seconds: what Exemplar does, that it ran on Ring, what it costs and where to look next.',
  },
  {
    id: 'lab', href: '/lab/', label: 'Lab', since: 'R3',
    title: 'Teach it yourself',
    purpose: 'Exemplar’s offline half running in your browser on recorded facts, checked against the engine.',
  },
  {
    id: 'how', href: '/how/', label: 'How it works', since: 'R2',
    title: 'How it works',
    purpose: 'Five chapters, each on one real recorded artifact, from reading a clip to a bound on false alarms.',
  },
  {
    id: 'live', href: '/live/', label: 'Live', since: 'R1',
    title: 'Playground replay',
    purpose: 'The recorded run on the Ring Developer Playground, with the evidence behind every alert.',
  },
  {
    id: 'evidence', href: '/evidence/', label: 'Evidence', since: 'R2',
    title: 'Evidence',
    purpose: 'Rigor that can be reproduced: every claim comes with its source and the command that checks it.',
  },
  {
    id: 'platform', href: '/platform/', label: 'Platform', since: 'R1',
    title: 'Built on Ring',
    purpose: 'How Exemplar uses Ring’s platform, with one honest status label on every capability.',
  },
  {
    id: 'credits', href: '/credits/', label: 'Credits', since: 'R1',
    title: 'Credits, permissions and disclosures',
    purpose: 'Every media source, its licence or authorisation, and the evidence for it.',
  },
]

const parseFlag = <T extends string>(name: string, raw: string | undefined, allowed: readonly T[], fallback: T): T => {
  if (raw === undefined || raw === '') return fallback
  if ((allowed as readonly string[]).includes(raw)) return raw as T
  throw new Error(`${name}=${JSON.stringify(raw)} is not valid; use one of ${allowed.join(', ')}`)
}

export const parseRelease = (raw: string | undefined): Release => parseFlag('SHOWCASE_RELEASE', raw, RELEASES, 'R4')
export const parseSandboxMedia = (raw: string | undefined): SandboxMedia =>
  parseFlag('SANDBOX_MEDIA', raw, SANDBOX_MEDIA_MODES, 'frames')

// next.config.js validates both flags and inlines them through `env`, so these resolve at build time in
// server and client code alike. (Node tests read the real environment, with the same defaults.)
export const RELEASE: Release = parseRelease(process.env.SHOWCASE_RELEASE)
export const SANDBOX_MEDIA: SandboxMedia = parseSandboxMedia(process.env.SANDBOX_MEDIA)

export const releaseAtLeast = (release: Release, since: Release): boolean =>
  RELEASES.indexOf(release) >= RELEASES.indexOf(since)

/** Pages included in a release, in navigation order. */
export const pagesFor = (release: Release): PageInfo[] => PAGES.filter((p) => releaseAtLeast(release, p.since))

export const getPage = (id: PageId): PageInfo => {
  const page = PAGES.find((p) => p.id === id)
  if (!page) throw new Error(`unknown page ${id}`)
  return page
}

/** Normalise a pathname so "/lab" and "/lab/" compare equal. */
export const normalizePath = (path: string): string => (path.length > 1 ? path.replace(/\/+$/, '') : path)

/** Does `pathname` belong to the nav entry `href`? Home matches only itself. */
export const isActivePath = (pathname: string, href: string): boolean => {
  const here = normalizePath(pathname)
  const target = normalizePath(href)
  return target === '/' ? here === '/' : here === target || here.startsWith(`${target}/`)
}

// ---------------------------------------------------------------------------------------------------------
// Replay disclosure (SPEC section 10.3). The text is exactly the spec's; it is chosen by release.

const BASE =
  'This site shows recorded results from Exemplar on the Ring Developer Playground and on recorded example clips. ' +
  'It runs in your browser and makes no Ring or AWS calls. ' +
  'Facts were produced by Claude on Amazon Bedrock when each clip was recorded.'

const LAB =
  'In the Lab, solving, checking, ranking and calibration re-run in your browser on those recorded facts. ' +
  'Rule sketches come from recorded sessions with the Strands agent. ' +
  "Results marked 'engine result' were computed by the engine, not re-solved here."

const Z3 = 'If you turn it on, Z3 also runs in your browser.'

/** The "What runs here" paragraphs for a release. R1 and R2 share one text; R3 and R4 build on it. */
export const disclosureParagraphs = (release: Release): string[] => {
  if (release === 'R1' || release === 'R2') return [BASE]
  if (release === 'R3') return [BASE, LAB]
  return [BASE, `${LAB} ${Z3}`]
}
