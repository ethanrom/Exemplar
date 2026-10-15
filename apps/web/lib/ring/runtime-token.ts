/**
 * Server-side holder for the Developer Playground token pasted in the UI (valid ~30 min, read-only).
 *
 * Lives on `globalThis` so it survives Next dev hot reloads. It is NEVER sent to the browser:
 * `GET /api/ring/token` returns only expiry metadata. The same token is forwarded to the engine
 * (`PUT /ring/auth`) so history/media calls and the WHEP proxy use one credential.
 */

interface Stored {
  token: string
  issuedAtMs: number | null
  expiresAtMs: number | null
  setAtMs: number
}

const g = globalThis as unknown as { __exemplarRingRuntimeToken?: Stored | null }

export interface RuntimeTokenStatus {
  connected: boolean
  expired: boolean
  issuedAtMs: number | null
  expiresAtMs: number | null
}

/** Decode `iat`/`exp` (seconds -> ms) from a JWT WITHOUT verifying it. Throws if it isn't a JWT. */
export function decodeJwtTimes(token: string): { issuedAtMs: number | null; expiresAtMs: number | null } {
  const parts = token.split('.')
  if (parts.length !== 3 || !parts[0] || !parts[1]) throw new Error('Not a JWT (expected three dot-separated segments)')
  let claims: Record<string, unknown>
  try {
    claims = JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'))
  } catch {
    throw new Error('JWT payload is not valid base64url JSON')
  }
  if (!claims || typeof claims !== 'object') throw new Error('JWT payload is not an object')
  const ms = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v * 1000) : null)
  return { issuedAtMs: ms(claims.iat), expiresAtMs: ms(claims.exp) }
}

/** Accepts a raw token or a pasted `Bearer <token>`; throws on anything that isn't a JWT. */
export function normalizePastedToken(input: string): string {
  const token = input.trim().replace(/^Bearer\s+/i, '').trim()
  if (token.length > 8192) throw new Error('Token is too long')
  decodeJwtTimes(token)
  return token
}

export function setRuntimeToken(input: string): RuntimeTokenStatus {
  const token = normalizePastedToken(input)
  const { issuedAtMs, expiresAtMs } = decodeJwtTimes(token)
  g.__exemplarRingRuntimeToken = { token, issuedAtMs, expiresAtMs, setAtMs: Date.now() }
  return getRuntimeTokenStatus()
}

export function clearRuntimeToken(): void {
  g.__exemplarRingRuntimeToken = null
}

/** The raw token, for server-side use only. */
export function getRuntimeToken(): { token: string; expired: boolean } | null {
  const s = g.__exemplarRingRuntimeToken
  if (!s) return null
  return { token: s.token, expired: s.expiresAtMs !== null && Date.now() >= s.expiresAtMs }
}

export function getRuntimeTokenStatus(): RuntimeTokenStatus {
  const s = g.__exemplarRingRuntimeToken
  if (!s) return { connected: false, expired: false, issuedAtMs: null, expiresAtMs: null }
  const expired = s.expiresAtMs !== null && Date.now() >= s.expiresAtMs
  return { connected: !expired, expired, issuedAtMs: s.issuedAtMs, expiresAtMs: s.expiresAtMs }
}
