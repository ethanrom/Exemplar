// Ring webhook signature verification (notifications.md): `X-Signature: sha256=<lowercase hex>`,
// HMAC-SHA256 over the RAW request body, key used as-is (UTF-8), constant-time comparison.
//
// Plain ESM (.mjs) so it runs unchanged under Next (route handlers) and `node --test` (no TS loader).
import { createHmac, timingSafeEqual } from 'node:crypto'

/**
 * @param {Uint8Array | string} rawBody exactly the bytes received (never a re-serialised object)
 * @param {string} key signing key
 * @returns {string} the header value, e.g. `sha256=ab12...`
 */
export function signBody(rawBody, key) {
  return 'sha256=' + createHmac('sha256', key).update(rawBody).digest('hex')
}

/**
 * Constant-time verification of an `X-Signature` header. Never throws on bad input.
 * @param {Uint8Array | string} rawBody
 * @param {string | null | undefined} header
 * @param {string | null | undefined} key
 * @returns {boolean}
 */
export function verifySignature(rawBody, header, key) {
  if (!key || typeof header !== 'string') return false
  const m = /^\s*sha256=([0-9a-fA-F]{64})\s*$/i.exec(header)
  if (!m) return false
  const given = Buffer.from(m[1], 'hex')
  const expected = createHmac('sha256', key).update(rawBody).digest()
  return given.length === expected.length && timingSafeEqual(given, expected)
}
