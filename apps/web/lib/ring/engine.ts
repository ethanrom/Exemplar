/** Server-side access to the Python engine (FastAPI). The browser never calls it directly for Ring things. */

export function engineUrl(): string {
  return (process.env.ENGINE_URL || 'http://127.0.0.1:8787').replace(/\/+$/, '')
}

export interface EngineResult<T = unknown> {
  ok: boolean
  status: number
  body: T | null
}

/** JSON request to the engine with a hard timeout. Never throws: failures come back as `{ok:false}`. */
export async function engineJson<T = unknown>(
  path: string,
  init: { method?: string; json?: unknown; timeoutMs?: number } = {},
): Promise<EngineResult<T>> {
  try {
    const res = await fetch(`${engineUrl()}${path}`, {
      method: init.method ?? 'GET',
      headers: init.json !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: init.json !== undefined ? JSON.stringify(init.json) : undefined,
      signal: AbortSignal.timeout(init.timeoutMs ?? 4000),
      cache: 'no-store',
    })
    let body: T | null = null
    try {
      body = (await res.json()) as T
    } catch {
      /* empty or non-JSON body */
    }
    return { ok: res.ok, status: res.status, body }
  } catch {
    return { ok: false, status: 0, body: null }
  }
}

/**
 * Forward a verified Ring webhook body, byte for byte, to `POST /ring/webhook-events`.
 * Retries briefly (the engine may be restarting). 202 and 409 (already processed) both count as delivered.
 * Resolves to true when the engine accepted it.
 */
export async function forwardWebhookToEngine(rawBody: string): Promise<boolean> {
  const delays = [0, 500, 1500]
  for (const delay of delays) {
    if (delay) await new Promise((r) => setTimeout(r, delay))
    try {
      const res = await fetch(`${engineUrl()}/ring/webhook-events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: rawBody,
        signal: AbortSignal.timeout(4000),
        cache: 'no-store',
      })
      if (res.ok || res.status === 409) return true
      if (res.status >= 400 && res.status < 500) return false // the engine rejected the payload: retrying won't help
    } catch {
      /* engine down or timed out: retry */
    }
  }
  return false
}
