// Tests for the story pages' pure logic, and for the facts their prose states about the recorded data.
// Run with: node --test components/story/story.test.ts   (from apps/showcase)
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadClaims, loadLibrary, loadLive, loadRule, loadTrace, loadCredits, runSlugs } from '../../lib/data/index.ts'
import { factRows } from './facts.ts'
import { capitalise, fmtDuration, fmtPlain, fmtScore, fmtSeconds, fmtSpan, ordinal, pluralise, words } from './format.ts'
import { parseVideoUrl, videoUrlAt } from './links.ts'
import { PACKAGE_RULE, VEHICLE_RULE, classOutcomes, decisionOf, playgroundBacktest, playgroundClass } from './outcomes.ts'

test('scores print with a sign and two decimals, like the engine rounds its margins', () => {
  assert.equal(fmtScore(0.44999999999999996), '+0.45')
  assert.equal(fmtScore(-0.5), '−0.50')
  assert.equal(fmtScore(-0.45), '−0.45')
  assert.equal(fmtScore(0), '0.00')
  assert.equal(fmtPlain(0), '0.00')
})

test('times, ranks and counts in prose', () => {
  assert.equal(fmtSeconds(991, 2), '0.99 s')
  assert.equal(fmtSeconds(15991, 2), '15.99 s')
  assert.equal(fmtSpan(991, 15991), '15 s')
  assert.equal(fmtDuration(32000), '32 s')
  assert.equal(fmtDuration(19930), '19.9 s')
  assert.deepEqual([1, 2, 3, 4, 5, 11, 12, 13, 21, 22].map(ordinal), ['1st', '2nd', '3rd', '4th', '5th', '11th', '12th', '13th', '21st', '22nd'])
  assert.equal(words(2), 'two')
  assert.equal(words(14), '14')
  assert.equal(capitalise('two'), 'Two')
  assert.equal(pluralise(1, 'event'), 'event')
  assert.equal(pluralise(2, 'event'), 'events')
})

test('the video link is shown only for an https YouTube URL, and can open at a moment', () => {
  assert.equal(parseVideoUrl(undefined), null)
  assert.equal(parseVideoUrl(''), null)
  assert.equal(parseVideoUrl('not a url'), null)
  assert.equal(parseVideoUrl('http://www.youtube.com/watch?v=abc'), null)
  assert.equal(parseVideoUrl('https://example.com/watch?v=abc'), null)
  const ok = parseVideoUrl('https://www.youtube.com/watch?v=abc')
  assert.equal(ok, 'https://www.youtube.com/watch?v=abc')
  assert.equal(videoUrlAt(ok, 81), 'https://www.youtube.com/watch?v=abc&t=81')
  assert.equal(videoUrlAt(null, 81), null)
})

test('facts group into one row per distinct fact, strongest confidence per frame', () => {
  const trace = {
    schema_version: 1, clip_id: 'x', source: 'ring', duration_ms: 3000, status: 'ok', error: null, entities: [], context: {}, summary: '',
    frames: [
      { t_ms: 0, facts: [{ pred: 'in_zone', args: ['k1', 'steps'], conf: 'low' }, { pred: 'in_zone', args: ['k1', 'steps'], conf: 'high' }] },
      { t_ms: 1000, facts: [{ pred: 'in_zone', args: ['k1', 'steps'], conf: 'med' }, { pred: 'present', args: ['p1'], conf: 'high' }] },
      { t_ms: 2000, facts: [] },
    ],
  } as const
  const rows = factRows(trace as never)
  assert.deepEqual(rows.map((r) => r.text), ['in_zone(k1, steps)', 'present(p1)'])
  assert.deepEqual(rows[0]?.cells, ['high', 'med', null])
  assert.equal(rows[0]?.seen, 2)
  assert.equal(rows[1]?.seen, 1)
})

test('class outcomes count how often each deployed rule fired', () => {
  const dec = (rule: string, fired: boolean) => ({ rule, stage: 1 as const, score: fired ? 0.45 : -0.5, tau: 0, fired, witness: null })
  const live = {
    events: [
      { alias: 'pg-bird-07', order: 1 as const, class: 'pg_bird' as const, decisions: [dec(PACKAGE_RULE, false), dec(VEHICLE_RULE, false)] },
      { alias: 'pg-pkg-19', order: 3 as const, class: 'pg_package' as const, decisions: [dec(PACKAGE_RULE, true), dec(VEHICLE_RULE, false)] },
    ],
  }
  const out = classOutcomes(live)
  assert.deepEqual(out.map((o) => [o.cls, o.events, o.packageFired, o.vehicleFired]), [['pg_package', 1, 1, 0], ['pg_bird', 1, 0, 0]])
  assert.equal(playgroundClass('pg-pkg-07'), 'pg_package')
  assert.equal(playgroundClass('cc-frollard-00s'), null)
  const counts = playgroundBacktest([{ alias: 'pg-pkg-01', matched: true }, { alias: 'pg-veh-01', matched: false }, { alias: 'cc-frollard-00s', matched: true }])
  assert.deepEqual(counts.map((c) => [c.cls, c.fired, c.total]), [['pg_package', 1, 1], ['pg_vehicle', 0, 1], ['pg_bird', 0, 0]])
})

// ---- what the pages say, checked against the recorded data ------------------------------------------------------

test('Home: the rule card is the deployed package rule, ranked 3rd of 6 and chosen by the user', () => {
  const rule = loadRule(PACKAGE_RULE)
  assert.equal(rule.english, 'There is a package k such that (k is on the steps or k is on the porch) continuously for at least 15 s.')
  assert.deepEqual(rule.recorded_rank, { run: 'p1-playground', position: 3, of: 6 })
  assert.equal(rule.selection, 'chosen_by_user_and_deployed')
  assert.deepEqual(rule.holes, { d: 15 })
})

test('Home and Live: the package event fired only the package rule, the vehicle events only the vehicle rule, the birds neither', () => {
  const live = loadLive()
  assert.equal(live.events.length, 5)
  const out = classOutcomes(live)
  const by = Object.fromEntries(out.map((o) => [o.cls, o]))
  assert.deepEqual([by.pg_package?.events, by.pg_package?.packageFired, by.pg_package?.vehicleFired], [2, 2, 0])
  assert.deepEqual([by.pg_vehicle?.events, by.pg_vehicle?.packageFired, by.pg_vehicle?.vehicleFired], [2, 0, 2])
  assert.deepEqual([by.pg_bird?.events, by.pg_bird?.packageFired, by.pg_bird?.vehicleFired], [1, 0, 0])
  for (const ev of live.events) {
    for (const d of ev.decisions) assert.equal(d.witness !== null, d.fired, `witness present exactly when fired (event ${ev.order}, ${d.rule})`)
    assert.ok(decisionOf(ev.decisions, PACKAGE_RULE) && decisionOf(ev.decisions, VEHICLE_RULE))
  }
})

test('Live: every event has a library clip with a trace, and a witness fits inside its clip', () => {
  const library = loadLibrary('frames')
  for (const ev of loadLive().events) {
    const card = library.find((c) => c.alias === ev.alias)
    assert.ok(card, `library has ${ev.alias}`)
    const trace = loadTrace(ev.alias)
    for (const d of ev.decisions) {
      if (!d.witness) continue
      for (const s of d.witness.spans) {
        assert.ok(s.t_start_ms >= 0 && s.t_end_ms <= trace.duration_ms, `${ev.alias} span ${s.path} inside the clip`)
        assert.ok(s.t_start_ms <= s.t_end_ms)
      }
    }
  }
})

test('Home: the proof tiles use claims that exist, verbatim', () => {
  const claims = loadClaims().claims
  for (const id of ['cost.per_event_live', 'cost.rule_eval', 'verify.encoding_cases', 'verify.planted_bugs']) {
    assert.ok(claims.find((c) => c.id === id), `claims.json has ${id}`)
  }
})

test('the published library has no AI-generated clip, no generated credit and no run taught from one', () => {
  const library = loadLibrary('frames')
  assert.ok(library.every((c) => c.source !== ('generated' as string) && c.class !== ('generated' as string) && !c.alias.startsWith('gen-')))
  assert.ok(loadCredits().every((c) => c.group !== ('generated' as string)))
  assert.deepEqual(runSlugs(), ['p1-playground', 'vehicle', 'theft-a', 'theft-b'])
})

test('Credits: every media source has a licence, evidence and a modification notice', () => {
  const credits = loadCredits()
  const media = credits.filter((c) => c.group !== 'software')
  for (const id of ['frollard', 'playground-frollard', 'playground-sandbox', 'ringtv-fox', 'meva']) {
    const e = media.find((c) => c.id === id)
    assert.ok(e, `credits.json has ${id}`)
    assert.ok(e.licence.length > 0 && e.permission.evidence.length > 0, `${id} has licence and evidence`)
    assert.ok((e.modification ?? '').length > 0, `${id} states what was changed`)
  }
  const frollard = media.find((c) => c.id === 'frollard')!
  assert.equal(frollard.title, 'Thief stealing our package')
  assert.equal(frollard.author, 'frollard')
  assert.match(frollard.licence, /CC BY 4\.0/)
})
