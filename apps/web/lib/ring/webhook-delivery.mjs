// Verify -> parse -> dedupe for one Ring webhook delivery. Pure (no Next imports) so it is unit-tested
// against the same signed fixtures as the Python side (engine/tests/fixtures/webhooks/*.json).
// Verify FIRST, claim second: a forged request must never be able to burn a legitimate request_id.
import { verifySignature } from './webhook-verify.mjs'

export const LIFECYCLE_EVENTS = ['app_integration_added', 'app_integration_removed']

/** Bounded LRU set of delivered `meta.request_id`s (in-memory; the engine keeps its own table). */
export class LruSet {
  /** @param {number} [max] */
  constructor(max = 2000) {
    this.max = max
    /** @type {Map<string, true>} */
    this.map = new Map()
  }
  /** @param {string} id */
  has(id) {
    return this.map.has(id)
  }
  /** @param {string} id @returns {boolean} true if `id` is new */
  claim(id) {
    if (this.map.has(id)) {
      this.map.delete(id)
      this.map.set(id, true) // refresh recency
      return false
    }
    this.map.set(id, true)
    while (this.map.size > this.max) {
      const oldest = this.map.keys().next().value
      if (oldest === undefined) break
      this.map.delete(oldest)
    }
    return true
  }
  /** @param {string} id */
  release(id) {
    this.map.delete(id)
  }
  get size() {
    return this.map.size
  }
}

/**
 * @typedef {{ status: 'accepted' | 'duplicate', requestId: string, eventType: string, body: any }
 *   | { status: 'rejected', reason: 'no_key' | 'bad_signature' | 'malformed', detail: string }} Delivery
 */

/**
 * @param {Uint8Array} rawBody
 * @param {string | null | undefined} signatureHeader
 * @param {string | null | undefined} key
 * @param {{ claim(id: string): boolean }} dedupe
 * @returns {Delivery}
 */
export function evaluateDelivery(rawBody, signatureHeader, key, dedupe) {
  if (!key) return { status: 'rejected', reason: 'no_key', detail: 'signing key not configured' }
  if (!verifySignature(rawBody, signatureHeader, key)) {
    return { status: 'rejected', reason: 'bad_signature', detail: 'bad or missing signature' }
  }
  let body
  try {
    body = JSON.parse(Buffer.from(rawBody).toString('utf8'))
  } catch {
    return { status: 'rejected', reason: 'malformed', detail: 'body is not JSON' }
  }
  const requestId = body?.meta?.request_id
  const eventType = body?.data?.type
  if (typeof requestId !== 'string' || !requestId || typeof eventType !== 'string' || !eventType) {
    return { status: 'rejected', reason: 'malformed', detail: 'missing meta.request_id or data.type' }
  }
  if (!dedupe.claim(requestId)) return { status: 'duplicate', requestId, eventType, body }
  return { status: 'accepted', requestId, eventType, body }
}
