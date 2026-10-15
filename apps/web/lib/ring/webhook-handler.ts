/**
 * Shared Ring webhook handler (used by /api/ring/webhook and the sample's legacy /api/webhook POST).
 *
 * Flow (PLAN.md 2.7, notifications.md):
 *   raw body -> verify X-Signature (HMAC-SHA256, constant time) -> parse -> dedupe meta.request_id
 *   -> respond 200 immediately -> forward the ORIGINAL body fire-and-forget to the engine
 *   (and broadcast to the sample dashboard's SSE feed).
 * Ring requires a 2xx within 5 s, so nothing slow is awaited before the response.
 */
import { NextRequest, NextResponse } from 'next/server'
import { broadcastEvent } from '@/lib/sse-broadcast'
import { forwardWebhookToEngine } from './engine'
import { LIFECYCLE_EVENTS, LruSet, evaluateDelivery } from './webhook-delivery.mjs'

const MAX_BODY_BYTES = 1_000_000

const g = globalThis as unknown as { __exemplarRingDedupe?: LruSet }
// process-wide so a Next dev hot reload does not forget what Ring already delivered
const dedupe: LruSet = (g.__exemplarRingDedupe ??= new LruSet(2000))

/** The sample dashboard's NormalizedEvent shape, extended for Ring's lifecycle/account events. */
function normalizeRingEvent(body: any) {
  const { meta, data } = body
  const a = data.attributes ?? {}
  let timestamp: string = meta?.time ?? new Date().toISOString()
  if (typeof a.timestamp === 'number' && Number.isFinite(a.timestamp)) {
    const d = new Date(a.timestamp)
    if (!Number.isNaN(d.getTime())) timestamp = d.toISOString()
  } else if (typeof a.timestamp === 'string') {
    timestamp = a.timestamp
  }
  return {
    event_id: data.id ?? meta.request_id,
    event_type: data.type,
    timestamp,
    // app_integration_* events are about the account (source_type "users"), not a device
    device_id: a.source_type === 'devices' && typeof a.source === 'string' ? a.source : null,
    confidence: a.confidence ?? null,
    bounding_box: a.bounding_box ?? null,
    thumbnail_url: a.thumbnail_url ?? null,
    metadata: {
      ring_version: meta?.version,
      ring_time: meta?.time,
      request_id: meta.request_id,
      account_id: meta?.account_id,
      source_type: a.source_type,
      sub_type: data.subType,
      device_link: data.relationships?.devices?.links?.self,
    },
    raw: body,
  }
}

function json(body: Record<string, unknown>, status: number) {
  return NextResponse.json(body, { status, headers: { 'Cache-Control': 'no-store' } })
}

export async function handleRingWebhook(req: NextRequest): Promise<NextResponse> {
  const key = process.env.RING_WEBHOOK_SIGNING_KEY
  if (!key) {
    // Never accept unsigned traffic just because the key is missing.
    console.error('[ring-webhook] RING_WEBHOOK_SIGNING_KEY is not set; refusing deliveries')
    return json({ error: 'Webhook signing key is not configured' }, 503)
  }

  const declared = Number(req.headers.get('content-length') ?? 0)
  if (declared > MAX_BODY_BYTES) return json({ error: 'Payload too large' }, 413)
  // Raw bytes, not req.text(): text() strips a BOM and replaces invalid UTF-8, either of which would
  // change what was signed.
  const raw = Buffer.from(await req.arrayBuffer())
  if (raw.length > MAX_BODY_BYTES) return json({ error: 'Payload too large' }, 413)

  const verdict = evaluateDelivery(raw, req.headers.get('x-signature'), key, dedupe)

  if (verdict.status === 'rejected') {
    if (verdict.reason === 'malformed') return json({ error: 'Malformed Ring notification' }, 400)
    console.warn('[ring-webhook] rejected delivery: bad or missing signature')
    return json({ error: 'Invalid signature' }, 401)
  }

  if (verdict.status === 'duplicate') {
    // 2xx so Ring stops retrying; nothing is re-processed.
    return json({ status: 'duplicate', request_id: verdict.requestId }, 200)
  }

  const { requestId, eventType, body } = verdict
  const isLifecycle = (LIFECYCLE_EVENTS as string[]).includes(eventType)
  if (isLifecycle) console.info(`[ring-webhook] lifecycle event: ${eventType}`)

  try {
    broadcastEvent(normalizeRingEvent(body))
  } catch (err) {
    console.error('[ring-webhook] SSE broadcast failed', err)
  }

  // Fire and forget: the 200 below must not wait for the engine.
  void forwardWebhookToEngine(raw.toString('utf8')).then((delivered) => {
    if (!delivered) {
      // Let a redelivery of the same request_id through, and make the loss visible in the logs.
      dedupe.release(requestId)
      console.error(`[ring-webhook] engine did not accept ${eventType} (request ${requestId})`)
    }
  })

  return json({ status: 'accepted', request_id: requestId, event_type: eventType }, 200)
}
