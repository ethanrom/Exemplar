/**
 * Server-side proxy: browser -> /api/engine/* -> ENGINE_URL (default http://127.0.0.1:8787).
 *
 * The browser never talks to the Python engine (or Ring) directly. This route forwards every
 * method, the query string, JSON and multipart bodies (streamed, never buffered), binary
 * responses (JPEG / MP4 including Range / 206) and Server-Sent Events (streamed without buffering).
 */
import type { NextRequest } from 'next/server'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const ENGINE_URL = (process.env.ENGINE_URL || 'http://127.0.0.1:8787').replace(/\/+$/, '')

/** Request headers that are safe and useful to forward (everything else, e.g. cookies, is dropped). */
const FORWARD_REQUEST_HEADERS = [
  'accept',
  'content-type',
  'content-length',
  'range',
  'if-range',
  'if-none-match',
  'if-modified-since',
  'last-event-id',
  'x-request-id',
]

/** Hop-by-hop response headers (RFC 9110 7.6.1) that must not be relayed. */
const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'trailers',
  'transfer-encoding',
  'upgrade',
])

type Ctx = { params: Promise<{ path: string[] }> }

function jsonError(status: number, error: string, code: string): Response {
  return new Response(JSON.stringify({ error, code }), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  })
}

async function proxy(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params
  const target = `${ENGINE_URL}/${path.map(encodeURIComponent).join('/')}${req.nextUrl.search}`

  const headers = new Headers()
  for (const name of FORWARD_REQUEST_HEADERS) {
    const v = req.headers.get(name)
    if (v) headers.set(name, v)
  }
  // Identity encoding: the body is relayed byte for byte, so Range / Content-Length stay exact
  // and SSE frames are never held back by a compressor.
  headers.set('accept-encoding', 'identity')

  const hasBody = req.method !== 'GET' && req.method !== 'HEAD' && req.body !== null
  const init: RequestInit & { duplex?: 'half' } = {
    method: req.method,
    headers,
    redirect: 'manual', // pass OAuth 302s through to the browser untouched
    cache: 'no-store',
    signal: req.signal, // client went away (closed tab, SSE unsubscribed) -> abort upstream
  }
  if (hasBody) {
    init.body = req.body
    init.duplex = 'half'
  }

  let upstream: Response
  try {
    upstream = await fetch(target, init)
  } catch (err) {
    if (req.signal.aborted) return new Response(null, { status: 499 })
    const reason = err instanceof Error ? (err.cause as Error | undefined)?.message || err.message : String(err)
    return jsonError(502, `Engine unreachable at ${ENGINE_URL} (${reason})`, 'ENGINE_UNREACHABLE')
  }

  const out = new Headers()
  const wasEncoded = upstream.headers.has('content-encoding')
  upstream.headers.forEach((value, name) => {
    const n = name.toLowerCase()
    if (HOP_BY_HOP.has(n)) return
    // fetch() already decoded the body, so the encoding / length headers would now lie.
    if (wasEncoded && (n === 'content-encoding' || n === 'content-length')) return
    if (n === 'location') {
      // Keep engine-relative redirects inside the proxy.
      out.set(name, value.startsWith(ENGINE_URL) ? `/api/engine${value.slice(ENGINE_URL.length)}` : value)
      return
    }
    out.set(name, value)
  })

  const contentType = upstream.headers.get('content-type') || ''
  if (contentType.startsWith('text/event-stream')) {
    out.set('cache-control', 'no-cache, no-transform')
    out.set('x-accel-buffering', 'no')
  } else if (!out.has('cache-control')) {
    out.set('cache-control', 'no-store')
  }

  const noBody = req.method === 'HEAD' || upstream.status === 204 || upstream.status === 304
  return new Response(noBody ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  })
}

export const GET = proxy
export const POST = proxy
export const PUT = proxy
export const PATCH = proxy
export const DELETE = proxy
export const HEAD = proxy
