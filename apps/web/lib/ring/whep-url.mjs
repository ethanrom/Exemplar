// WHEP session URL allow-list for `DELETE /api/ring/stream`. The route attaches our bearer token to
// the URL, so it may only ever point at the Ring API's own WHEP sessions (the sample forwarded the
// token to any client-supplied URL).
export const RING_API_ORIGIN = 'https://api.amazonvision.com'
const PATH_RE = /^\/v1\/devices\/([A-Za-z0-9._-]{1,256})\/media\/streaming\/whep\/sessions\/([^/?#]+)$/

/** @param {unknown} id */
export function isValidDeviceId(id) {
  return typeof id === 'string' && /^[A-Za-z0-9._-]{1,256}$/.test(id) && id !== '.' && id !== '..'
}

/** Expected prefix for a device's sessions, e.g. https://api.amazonvision.com/v1/devices/<id>/media/streaming/whep/sessions/ */
export function whepSessionsPrefix(deviceId) {
  return `${RING_API_ORIGIN}/v1/devices/${deviceId}/media/streaming/whep/sessions/`
}

/**
 * @param {unknown} sessionUrl value from the client (the `Location` of the WHEP POST)
 * @param {string} [deviceId] when given, the URL must belong to this device
 * @returns {{ ok: true, url: string } | { ok: false, reason: string }}
 */
export function validateWhepSessionUrl(sessionUrl, deviceId) {
  if (typeof sessionUrl !== 'string' || sessionUrl.length === 0 || sessionUrl.length > 4096) {
    return { ok: false, reason: 'sessionUrl must be a non-empty string' }
  }
  if (/[\s\x00-\x1f\\]/.test(sessionUrl) || sessionUrl.includes('#')) {
    return { ok: false, reason: 'sessionUrl contains forbidden characters' }
  }
  let u
  try {
    u = new URL(sessionUrl)
  } catch {
    return { ok: false, reason: 'sessionUrl is not a valid URL' }
  }
  if (u.protocol !== 'https:' || u.origin !== RING_API_ORIGIN || u.username || u.password) {
    return { ok: false, reason: 'sessionUrl must be on ' + RING_API_ORIGIN }
  }
  // The raw string (minus its query) must be byte-identical to the normalised one: no `..`, `%2e`,
  // `:443`, or other tricks that would make the URL we forward differ from the URL we validated.
  const rawPath = sessionUrl.split('?')[0]
  if (rawPath !== u.origin + u.pathname) {
    return { ok: false, reason: 'sessionUrl is not in canonical form' }
  }
  const m = PATH_RE.exec(u.pathname)
  if (!m || m[2] === '.' || m[2] === '..') {
    return { ok: false, reason: 'sessionUrl is not a WHEP session of a device' }
  }
  if (deviceId !== undefined && m[1] !== deviceId) {
    return { ok: false, reason: 'sessionUrl belongs to a different device' }
  }
  if (deviceId !== undefined && !sessionUrl.startsWith(whepSessionsPrefix(deviceId))) {
    return { ok: false, reason: 'sessionUrl prefix mismatch' }
  }
  return { ok: true, url: sessionUrl } // forwarded verbatim: the long `?location=...` query stays intact
}
