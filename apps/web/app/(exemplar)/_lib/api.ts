// Browser -> /api/engine/* (Next route, server side) -> engine. The browser never calls the engine or Ring directly.
import type { ApiErrorBody } from './types'

export const ENGINE_BASE = '/api/engine'
export const engineUrl = (path: string) => `${ENGINE_BASE}${path}`

export class ApiError extends Error {
  status: number
  code: string | null
  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null
  try {
    body = await res.json()
  } catch {
    /* not JSON */
  }
  const fallback = res.status === 502 ? 'The engine is not reachable.' : `Request failed (${res.status})`
  // The proxy reports "Engine unreachable at <url> (<socket error>)": say it in plain words instead.
  const unreachable = body?.code === 'ENGINE_UNREACHABLE'
  return new ApiError(res.status, unreachable ? 'The Exemplar engine is not running or not reachable. Start it, then try again.' : body?.error || fallback, body?.code ?? null)
}

export async function api<T = unknown>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
  init: { signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['content-type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(engineUrl(path), { method, headers, body: payload, cache: 'no-store', signal: init.signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'Could not reach the Exemplar web server.', 'NETWORK')
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204 || res.status === 202 && res.headers.get('content-length') === '0') return null as T
  const text = await res.text()
  return (text ? JSON.parse(text) : null) as T
}

export const get = <T>(path: string, signal?: AbortSignal) => api<T>('GET', path, undefined, { signal })
export const post = <T>(path: string, body?: unknown) => api<T>('POST', path, body)
export const put = <T>(path: string, body?: unknown) => api<T>('PUT', path, body)
export const patch = <T>(path: string, body?: unknown) => api<T>('PATCH', path, body)

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return String(err)
}
