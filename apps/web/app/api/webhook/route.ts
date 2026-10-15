import { NextRequest } from 'next/server'
import { addClient, eventStore, removeClient } from '@/lib/sse-broadcast'
import { handleRingWebhook } from '@/lib/ring/webhook-handler'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

/**
 * Legacy path of the sample app. The sample authenticated POSTs with a static bearer token compared
 * with `!==`; that is gone. POST now runs the same verified handler as /api/ring/webhook
 * (X-Signature HMAC over the raw body, constant-time compare, dedupe on meta.request_id).
 * GET stays: the sample dashboard (useEventStream) reads its live event feed from this SSE stream.
 */
export async function POST(request: NextRequest) {
  return handleRingWebhook(request)
}

export async function GET() {
  const encoder = new TextEncoder()

  const stream = new ReadableStream({
    start(controller) {
      addClient(controller)
      controller.enqueue(encoder.encode(': connected\n\n'))

      for (const event of eventStore) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }

      const keepAlive = setInterval(() => {
        try { controller.enqueue(encoder.encode(': ping\n\n')) }
        catch { clearInterval(keepAlive) }
      }, 30000)

      ;(controller as any)._keepAlive = keepAlive
    },
    cancel(controller) {
      removeClient(controller)
      const keepAlive = (controller as any)._keepAlive
      if (keepAlive) clearInterval(keepAlive)
    },
  })

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}
