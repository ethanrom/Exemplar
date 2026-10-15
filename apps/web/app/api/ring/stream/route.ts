import { NextRequest, NextResponse } from 'next/server'
import { authErrorStatus, getRingAccessToken } from '@/lib/ring/auth'
import { sameOriginOrNoOrigin } from '@/lib/ring/guard'
import { RING_API_ORIGIN, isValidDeviceId, validateWhepSessionUrl } from '@/lib/ring/whep-url.mjs'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const API_BASE = RING_API_ORIGIN

export async function POST(request: NextRequest) {
  try {
    if (!sameOriginOrNoOrigin(request)) {
      return NextResponse.json({ error: 'Cross-origin request refused' }, { status: 403 })
    }
    const { sdpOffer, deviceId } = await request.json()

    if (!sdpOffer || typeof sdpOffer !== 'string') {
      return NextResponse.json({ error: 'Missing sdpOffer' }, { status: 400 })
    }

    // Use deviceId from request body, fall back to env var
    const resolvedDeviceId = deviceId || process.env.NEXT_PUBLIC_RING_DEVICE_ID
    if (!resolvedDeviceId) {
      return NextResponse.json(
        { error: 'No device ID provided. Pass deviceId in request body or set NEXT_PUBLIC_RING_DEVICE_ID.' },
        { status: 400 }
      )
    }
    // The id is spliced into a URL path that carries our bearer token: restrict it to a safe alphabet.
    if (!isValidDeviceId(resolvedDeviceId)) {
      return NextResponse.json({ error: 'Invalid device ID' }, { status: 400 })
    }

    const token = await getRingAccessToken()
    const whepUrl = `${API_BASE}/v1/devices/${resolvedDeviceId}/media/streaming/whep/sessions`

    const response = await fetch(whepUrl, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/sdp',
      },
      body: sdpOffer,
      redirect: 'manual',
    })

    if (!response.ok) {
      const error = await response.text()
      return NextResponse.json(
        { error: `WHEP failed: ${response.status} - ${error}` },
        { status: response.status }
      )
    }

    const sdpAnswer = await response.text()
    const location = response.headers.get('Location')
    // Make the session URL absolute so DELETE can validate it against the Ring API prefix.
    let sessionUrl: string | null = null
    if (location) {
      try {
        sessionUrl = new URL(location, API_BASE).href
      } catch {
        sessionUrl = null
      }
    }

    return NextResponse.json({ sdpAnswer, sessionUrl })
  } catch (error) {
    console.error('Stream error:', error instanceof Error ? error.message : error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Stream failed' },
      { status: authErrorStatus(error) }
    )
  }
}

/**
 * Close a WHEP session. The session URL comes from the browser, and we attach our bearer token to it,
 * so it must be a WHEP session of a device on the Ring API itself
 * (https://api.amazonvision.com/v1/devices/<deviceId>/media/streaming/whep/sessions/...). The long
 * `?location=...` query that Ring appends is forwarded untouched.
 */
export async function DELETE(request: NextRequest) {
  try {
    if (!sameOriginOrNoOrigin(request)) {
      return NextResponse.json({ error: 'Cross-origin request refused' }, { status: 403 })
    }
    const { sessionUrl, deviceId } = await request.json()
    if (!sessionUrl) {
      return NextResponse.json({ error: 'Missing sessionUrl' }, { status: 400 })
    }
    if (deviceId !== undefined && deviceId !== null && !isValidDeviceId(deviceId)) {
      return NextResponse.json({ error: 'Invalid device ID' }, { status: 400 })
    }

    const checked = validateWhepSessionUrl(sessionUrl, deviceId ?? undefined)
    if (!checked.ok) {
      return NextResponse.json({ error: `Refusing to forward: ${checked.reason}` }, { status: 400 })
    }

    const token = await getRingAccessToken()
    await fetch(checked.url, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
      redirect: 'manual', // never follow a redirect with the bearer token attached
    })

    return NextResponse.json({ success: true })
  } catch (error) {
    return NextResponse.json({ error: 'Failed to close session' }, { status: 500 })
  }
}
