import { NextResponse } from 'next/server'
import { describeRingAuth } from '@/lib/ring/auth'

export const dynamic = 'force-dynamic'

/**
 * Auth mode for the dashboard. A Playground token pasted at runtime (PUT /api/ring/token) counts as
 * 'access_token' mode, same as RING_ACCESS_TOKEN. Never returns a credential.
 */
export async function GET() {
  const d = describeRingAuth()

  if (d.conflict) {
    return NextResponse.json(
      { error: 'Both RING_ACCESS_TOKEN and RING_REFRESH_TOKEN are set. Please use only one.' },
      { status: 400 }
    )
  }

  if (d.mode === null) {
    return NextResponse.json(
      {
        error: d.expired
          ? 'The pasted Ring Playground token has expired. Paste a fresh one.'
          : 'Authentication not configured. Paste a Playground token, or set RING_ACCESS_TOKEN or RING_REFRESH_TOKEN in .env.local',
      },
      { status: 400 }
    )
  }

  return NextResponse.json({ mode: d.mode })
}
