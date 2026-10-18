// Proof that TypeScript with explicit .ts imports runs under `node --test` (Node strips the types itself) and,
// through components/site/config.ts, that the same file is what the Next build imports. Skeleton-owned.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  PAGES, RELEASES, disclosureParagraphs, isActivePath, pagesFor, parseRelease, parseSandboxMedia,
} from '../components/site/config.ts'

test('the seven pages, in navigation order', () => {
  assert.deepEqual(
    PAGES.map((p) => p.href),
    ['/', '/lab/', '/how/', '/live/', '/evidence/', '/platform/', '/credits/'],
  )
})

test('releases add pages (SPEC section 3)', () => {
  const ids = (r: (typeof RELEASES)[number]) => pagesFor(r).map((p) => p.id)
  assert.deepEqual(ids('R1'), ['home', 'live', 'platform', 'credits'])
  assert.deepEqual(ids('R2'), ['home', 'how', 'live', 'evidence', 'platform', 'credits'])
  assert.equal(ids('R3').length, 7)
  assert.equal(ids('R4').length, 7)
})

test('flags: defaults and rejection of unknown values', () => {
  assert.equal(parseRelease(undefined), 'R4')
  assert.equal(parseRelease('R1'), 'R1')
  assert.throws(() => parseRelease('R9'))
  assert.equal(parseSandboxMedia(undefined), 'frames')
  assert.equal(parseSandboxMedia('trace'), 'trace')
  assert.throws(() => parseSandboxMedia('all'))
})

test('active link matching tolerates the trailing slash; Home matches only itself', () => {
  assert.equal(isActivePath('/lab/', '/lab/'), true)
  assert.equal(isActivePath('/lab', '/lab/'), true)
  assert.equal(isActivePath('/lab/', '/'), false)
  assert.equal(isActivePath('/', '/'), true)
})

test('the replay disclosure grows with the release and is spec text', () => {
  const r1 = disclosureParagraphs('R1')
  assert.equal(r1.length, 1)
  assert.match(r1[0] ?? '', /^This site shows recorded results from Exemplar on the Ring Developer Playground/)
  assert.deepEqual(disclosureParagraphs('R2'), r1)
  assert.equal(disclosureParagraphs('R3').length, 2)
  assert.match(disclosureParagraphs('R3')[1] ?? '', /not re-solved here\.$/)
  assert.match(disclosureParagraphs('R4')[1] ?? '', /If you turn it on, Z3 also runs in your browser\.$/)
})
