/**
 * Which Ring credential the Next.js server uses (WHEP proxy, device discovery).
 *
 * Precedence: a Playground token pasted at runtime (still valid) > RING_ACCESS_TOKEN > RING_REFRESH_TOKEN
 * (the sample's `lib/auth.ts`, left untouched). Nothing here ever returns a token to a browser.
 */
import { getAccessToken } from '@/lib/auth'
import { getRuntimeToken, getRuntimeTokenStatus } from './runtime-token'

export type RingAuthMode = 'access_token' | 'refresh_token'
export type RingAuthSource = 'pasted' | 'env'

export interface RingAuthDescription {
  mode: RingAuthMode | null
  source: RingAuthSource | null
  conflict: boolean
  /** A pasted token exists but has expired and nothing else is configured. */
  expired: boolean
}

export class RingAuthUnavailableError extends Error {
  constructor(message: string, readonly code: 'NOT_CONFIGURED' | 'TOKEN_EXPIRED' | 'CONFLICT') {
    super(message)
    this.name = 'RingAuthUnavailableError'
  }
}

export function describeRingAuth(): RingAuthDescription {
  const envAccess = !!process.env.RING_ACCESS_TOKEN
  const envRefresh = !!process.env.RING_REFRESH_TOKEN
  const pasted = getRuntimeTokenStatus()
  if (pasted.connected) return { mode: 'access_token', source: 'pasted', conflict: false, expired: false }
  if (envAccess && envRefresh) return { mode: null, source: null, conflict: true, expired: false }
  if (envAccess) return { mode: 'access_token', source: 'env', conflict: false, expired: false }
  if (envRefresh) return { mode: 'refresh_token', source: 'env', conflict: false, expired: false }
  return { mode: null, source: null, conflict: false, expired: pasted.expired }
}

export async function getRingAccessToken(): Promise<string> {
  const pasted = getRuntimeToken()
  if (pasted && !pasted.expired) return pasted.token
  const d = describeRingAuth()
  if (d.conflict) {
    throw new RingAuthUnavailableError('Both RING_ACCESS_TOKEN and RING_REFRESH_TOKEN are set. Please use only one.', 'CONFLICT')
  }
  if (d.mode) return getAccessToken()
  if (pasted) {
    throw new RingAuthUnavailableError('The pasted Ring Playground token has expired (they last 30 minutes). Paste a fresh one.', 'TOKEN_EXPIRED')
  }
  throw new RingAuthUnavailableError(
    'Ring is not connected. Paste a Developer Playground token, or set RING_ACCESS_TOKEN / RING_REFRESH_TOKEN in .env.local.',
    'NOT_CONFIGURED',
  )
}

/** HTTP status for an auth failure raised by getRingAccessToken(). */
export function authErrorStatus(err: unknown): number {
  return err instanceof RingAuthUnavailableError ? 401 : 500
}
