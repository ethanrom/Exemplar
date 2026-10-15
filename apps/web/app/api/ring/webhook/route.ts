import { NextRequest, NextResponse } from 'next/server'
import { handleRingWebhook } from '@/lib/ring/webhook-handler'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/**
 * Ring notifications endpoint: configure `https://<host>/api/ring/webhook` as the app's webhook URL.
 * Verifies `X-Signature` (HMAC-SHA256 over the raw body), dedupes on meta.request_id, answers 200 fast and
 * forwards the original body to the engine. See lib/ring/webhook-handler.ts.
 */
export async function POST(request: NextRequest) {
  return handleRingWebhook(request)
}

/** Liveness probe for setup/debugging. Reveals nothing but whether a signing key is configured. */
export async function GET() {
  return NextResponse.json({
    ok: true,
    method: 'POST',
    signing_key_configured: !!process.env.RING_WEBHOOK_SIGNING_KEY,
  })
}
