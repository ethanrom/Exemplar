import { NextRequest } from 'next/server'

/**
 * CSRF guard for state-changing routes that take a credential: a browser always sends `Origin` on
 * cross-site POST/PUT/DELETE, so if it is present it must match this host. Non-browser callers
 * (curl, server-to-server, the Playwright demo harness) send no Origin and pass.
 */
export function sameOriginOrNoOrigin(req: NextRequest): boolean {
  const origin = req.headers.get('origin')
  if (!origin) return true
  try {
    return new URL(origin).host === req.headers.get('host')
  } catch {
    return false
  }
}
