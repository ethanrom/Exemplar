import { NextRequest, NextResponse } from 'next/server'
import { engineJson } from '@/lib/ring/engine'
import { sameOriginOrNoOrigin } from '@/lib/ring/guard'
import { clearRuntimeToken, decodeJwtTimes, getRuntimeTokenStatus, setRuntimeToken } from '@/lib/ring/runtime-token'
import { describeRingAuth } from '@/lib/ring/auth'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/**
 * The Ring access token is a server-side secret: this route NEVER returns it (the sample's
 * GET /api/ring/token handed the token to any caller). GET reports only whether we are connected and
 * when the token expires; PUT is the UI's "paste token" flow.
 */
const noStore = { 'Cache-Control': 'no-store' }

function statusBody() {
  const d = describeRingAuth()
  let issued: number | null = null
  let expires: number | null = null
  if (d.source === 'pasted' || d.expired) {
    const rt = getRuntimeTokenStatus()
    issued = rt.issuedAtMs
    expires = rt.expiresAtMs
  } else if (d.source === 'env' && d.mode === 'access_token') {
    try {
      const t = decodeJwtTimes(process.env.RING_ACCESS_TOKEN ?? '')
      issued = t.issuedAtMs
      expires = t.expiresAtMs
    } catch {
      /* an opaque (non-JWT) token has no readable expiry */
    }
  }
  return {
    // a bare access token is what the Developer Playground hands out; a refresh token means app (OAuth) mode
    mode: d.mode === null ? null : d.mode === 'refresh_token' ? 'oauth' : 'playground',
    connected: d.mode !== null,
    source: d.source,
    expired: d.expired,
    issued_at_ms: issued,
    expires_at_ms: expires,
  }
}

export async function GET() {
  return NextResponse.json(statusBody(), { headers: noStore })
}

/**
 * PUT { access_token } - store a Developer Playground token for this server (WHEP proxy, device
 * discovery) and forward it to the engine's PUT /ring/auth so history/media calls use it too.
 */
export async function PUT(request: NextRequest) {
  if (!sameOriginOrNoOrigin(request)) {
    return NextResponse.json({ error: 'Cross-origin request refused' }, { status: 403, headers: noStore })
  }
  let body: any
  try {
    body = await request.json()
  } catch {
    return NextResponse.json({ error: 'Body must be JSON: {"access_token": "<token>"}' }, { status: 400, headers: noStore })
  }
  const pasted = typeof body?.access_token === 'string' ? body.access_token : typeof body?.token === 'string' ? body.token : ''
  if (!pasted) {
    return NextResponse.json({ error: 'Missing access_token' }, { status: 400, headers: noStore })
  }
  try {
    setRuntimeToken(pasted)
  } catch (err) {
    return NextResponse.json(
      { error: `That does not look like a Ring access token (${err instanceof Error ? err.message : 'invalid'})` },
      { status: 400, headers: noStore },
    )
  }

  // Best effort: the engine may not be up yet; the token is already usable by this server.
  const engine = await engineJson<{ user_name?: string | null; error?: string }>('/ring/auth', {
    method: 'PUT',
    json: { access_token: pasted.trim().replace(/^Bearer\s+/i, '') },
  })
  return NextResponse.json(
    {
      ...statusBody(),
      user_name: engine.body?.user_name ?? null,
      engine: engine.ok ? 'synced' : engine.status === 0 ? 'unreachable' : `rejected (${engine.status})`,
      ...(engine.ok || !engine.body?.error ? {} : { engine_error: engine.body.error }),
    },
    { headers: noStore },
  )
}

export const POST = PUT

/** Forget the pasted token (disconnect). */
export async function DELETE(request: NextRequest) {
  if (!sameOriginOrNoOrigin(request)) {
    return NextResponse.json({ error: 'Cross-origin request refused' }, { status: 403, headers: noStore })
  }
  clearRuntimeToken()
  return NextResponse.json(statusBody(), { headers: noStore })
}
