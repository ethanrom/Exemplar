// Outbound links the story pages may show. Both are plain links (never an embed: the site's COEP headers block
// third-party iframes). The video link is hidden unless an https YouTube URL is configured at build time.

export const REPO_URL = 'https://github.com/ethanrom/Exemplar'

const YOUTUBE_HOSTS = new Set(['www.youtube.com', 'youtube.com', 'youtu.be', 'm.youtube.com'])

/** The configured demo-video URL, or null when it is unset or is not an https YouTube link. */
export function parseVideoUrl(raw: string | undefined): string | null {
  if (!raw) return null
  try {
    const url = new URL(raw)
    if (url.protocol !== 'https:' || !YOUTUBE_HOSTS.has(url.hostname)) return null
    return url.toString()
  } catch {
    return null
  }
}

/** Build-time setting: NEXT_PUBLIC_VIDEO_URL. Next inlines it into server and client code. */
export const videoUrl = (): string | null => parseVideoUrl(process.env.NEXT_PUBLIC_VIDEO_URL)

/** The same link opened at a moment (seconds), for the live segment. */
export function videoUrlAt(raw: string | null, seconds: number): string | null {
  if (!raw) return null
  const url = new URL(raw)
  url.searchParams.set('t', String(seconds))
  return url.toString()
}
