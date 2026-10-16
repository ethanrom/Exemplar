// Run:  cd apps/web && node --test lib/ring/ring.test.mjs    (Node >= 18, no extra dependencies)
//
// Drives the webhook verifier with the SAME signed fixtures the Python tests use
// (engine/tests/fixtures/webhooks/*.json: `expect`, `headers`, raw `body`; key `exemplar-test-signing-key`),
// plus the WHEP session-URL allow-list used by DELETE /api/ring/stream.
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { LruSet, evaluateDelivery } from './webhook-delivery.mjs'
import { signBody, verifySignature } from './webhook-verify.mjs'
import { isValidDeviceId, validateWhepSessionUrl } from './whep-url.mjs'

const KEY = 'exemplar-test-signing-key'
const DIR = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..', 'engine', 'tests', 'fixtures', 'webhooks')
const fixtures = Object.fromEntries(
  readdirSync(DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => [f.replace(/\.json$/, ''), JSON.parse(readFileSync(join(DIR, f), 'utf8'))]),
)
const raw = (name) => Buffer.from(fixtures[name].body, 'utf8')
const sig = (name) => fixtures[name].headers['X-Signature']

test('fixtures are present', () => {
  for (const n of ['motion_human', 'motion_vehicle', 'button_press', 'app_integration_added', 'app_integration_removed', 'duplicate', 'tampered', 'reserialised', 'missing_signature']) {
    assert.ok(fixtures[n], `missing fixture ${n}`)
  }
  assert.deepEqual(new Set(Object.values(fixtures).map((f) => f.expect)), new Set(['accept', 'reject', 'duplicate']))
})

for (const [name, f] of Object.entries(fixtures)) {
  test(`fixture ${name}: expect ${f.expect}`, () => {
    const dedupe = new LruSet()
    if (f.expect === 'duplicate') {
      const first = evaluateDelivery(raw('motion_human'), sig('motion_human'), KEY, dedupe)
      assert.equal(first.status, 'accepted')
    }
    const d = evaluateDelivery(raw(name), f.headers['X-Signature'], KEY, dedupe)
    const want = { accept: 'accepted', reject: 'rejected', duplicate: 'duplicate' }[f.expect]
    assert.equal(d.status, want, d.detail)
    if (f.expect === 'reject') assert.equal(d.reason, 'bad_signature')
    if (f.expect !== 'reject') assert.equal(typeof d.requestId, 'string')
  })
}

test('replaying a delivery is a duplicate the second time only', () => {
  const dedupe = new LruSet()
  assert.equal(evaluateDelivery(raw('motion_human'), sig('motion_human'), KEY, dedupe).status, 'accepted')
  assert.equal(evaluateDelivery(raw('motion_human'), sig('motion_human'), KEY, dedupe).status, 'duplicate')
  assert.equal(evaluateDelivery(raw('motion_vehicle'), sig('motion_vehicle'), KEY, dedupe).status, 'accepted')
})

test('rejected deliveries do not consume the request_id', () => {
  const dedupe = new LruSet()
  for (const bad of ['tampered', 'reserialised', 'missing_signature']) {
    assert.equal(evaluateDelivery(raw(bad), fixtures[bad].headers['X-Signature'], KEY, dedupe).status, 'rejected')
  }
  assert.equal(dedupe.size, 0)
  assert.equal(evaluateDelivery(raw('motion_human'), sig('motion_human'), KEY, dedupe).status, 'accepted')
})

test('signature covers the raw bytes, not the parsed JSON', () => {
  const body = raw('motion_human')
  const reserialised = Buffer.from(JSON.stringify(JSON.parse(body.toString('utf8')), null, 1))
  assert.equal(verifySignature(body, sig('motion_human'), KEY), true)
  assert.equal(verifySignature(reserialised, sig('motion_human'), KEY), false)
  assert.equal(verifySignature(Buffer.concat([body, Buffer.from(' ')]), sig('motion_human'), KEY), false)
})

test('signBody reproduces the fixture signatures', () => {
  for (const n of ['motion_human', 'motion_vehicle', 'button_press', 'app_integration_added', 'app_integration_removed']) {
    assert.equal(signBody(raw(n), KEY), sig(n))
  }
})

test('garbage headers / keys never verify and never throw', () => {
  const body = raw('motion_human')
  for (const h of [undefined, null, '', 'sha256=', 'sha256', 'sha1=' + '0'.repeat(40), 'sha256=zz' + '0'.repeat(62), 'sha256=' + '0'.repeat(63), 'sha256=' + '0'.repeat(64), '=', 'md5=abc']) {
    assert.equal(verifySignature(body, h, KEY), false, String(h))
  }
  assert.equal(verifySignature(body, sig('motion_human'), ''), false)
  assert.equal(verifySignature(body, sig('motion_human'), undefined), false)
  assert.equal(verifySignature(body, sig('motion_human'), 'another-key'), false)
})

test('uppercase hex and surrounding whitespace are tolerated', () => {
  const h = '  ' + sig('motion_human').replace('sha256=', 'sha256=').toUpperCase().replace('SHA256=', 'sha256=') + ' '
  assert.equal(verifySignature(raw('motion_human'), h, KEY), true)
})

test('unconfigured key rejects everything; signed garbage is malformed, not a crash', () => {
  assert.equal(evaluateDelivery(raw('motion_human'), sig('motion_human'), undefined, new LruSet()).reason, 'no_key')
  const junk = Buffer.from('not json')
  const d = evaluateDelivery(junk, signBody(junk, KEY), KEY, new LruSet())
  assert.deepEqual([d.status, d.reason], ['rejected', 'malformed'])
  const noMeta = Buffer.from('{"hello":"world"}')
  assert.equal(evaluateDelivery(noMeta, signBody(noMeta, KEY), KEY, new LruSet()).reason, 'malformed')
})

test('LruSet is bounded and refreshes recency', () => {
  const s = new LruSet(3)
  assert.deepEqual(['a', 'b', 'c'].map((x) => s.claim(x)), [true, true, true])
  assert.equal(s.claim('a'), false) // refresh a: order b, c, a
  assert.equal(s.claim('d'), true) // evicts b
  assert.equal(s.size, 3)
  assert.equal(s.claim('b'), true) // forgotten (evicts c)
  assert.equal(s.claim('a'), false)
  s.release('a')
  assert.equal(s.claim('a'), true)
})

// ---- WHEP session URL allow-list --------------------------------------------------------------
const DEV = 'ava1.ring.device.FIXTUREDEVICE0001'
const SESSION = `https://api.amazonvision.com/v1/devices/${DEV}/media/streaming/whep/sessions/abc123`
const LONG = `${SESSION}?location=ava1.ring.whep.location.${'X'.repeat(300)}&x=1%2F2`

test('WHEP: valid session URLs are forwarded verbatim, long query intact', () => {
  for (const u of [SESSION, LONG]) {
    const r = validateWhepSessionUrl(u, DEV)
    assert.deepEqual(r, { ok: true, url: u })
    assert.equal(validateWhepSessionUrl(u).ok, true)
  }
})

test('WHEP: anything else is refused (token must not leak)', () => {
  const bad = [
    'https://evil.example/v1/devices/x/media/streaming/whep/sessions/abc',
    'http://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/abc',
    'https://api.amazonvision.com.evil.example/v1/devices/x/media/streaming/whep/sessions/abc',
    'https://api.amazonvision.com@evil.example/v1/devices/x/media/streaming/whep/sessions/abc',
    'https://user:pw@api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/abc',
    'https://api.amazonvision.com:8443/v1/devices/x/media/streaming/whep/sessions/abc',
    'https://api.amazonvision.com:443/v1/devices/x/media/streaming/whep/sessions/abc',
    'https://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/',
    'https://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/a/b',
    'https://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/..',
    'https://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/../../../users/me',
    'https://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/%2e%2e/foo',
    'https://api.amazonvision.com/v1/devices/x/../y/media/streaming/whep/sessions/abc',
    'https://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/abc#frag',
    'https://api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/abc\\..\\..',
    'https://api.amazonvision.com/v1/users/me',
    'https://api.amazonvision.com/v1/devices/x/media/video/download',
    '//api.amazonvision.com/v1/devices/x/media/streaming/whep/sessions/abc',
    '/v1/devices/x/media/streaming/whep/sessions/abc',
    'javascript:alert(1)',
    '',
    ' ' + SESSION,
  ]
  for (const u of bad) assert.equal(validateWhepSessionUrl(u).ok, false, u)
  for (const v of [undefined, null, 42, {}, []]) assert.equal(validateWhepSessionUrl(v).ok, false)
})

test('WHEP: a session of another device is refused when the device is given', () => {
  assert.equal(validateWhepSessionUrl(SESSION, 'ava1.ring.device.OTHER').ok, false)
  assert.equal(validateWhepSessionUrl(SESSION, DEV).ok, true)
})

test('device ids are restricted to a safe alphabet', () => {
  assert.equal(isValidDeviceId(DEV), true)
  for (const id of ['', '..', '.', 'a/b', 'a b', 'a?b', 'a#b', '../x', 'x'.repeat(300), undefined, 5]) {
    assert.equal(isValidDeviceId(id), false, String(id))
  }
})
