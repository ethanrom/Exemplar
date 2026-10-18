// The wording of the engine-check badge: the statements SPEC 7.1 and 7.2 give as examples, and the failure paths.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { FreeCheck, PresetCheck } from './compare.ts'
import { describeFree, describePreset } from './describe.ts'

const free = (counts: Partial<FreeCheck['counts']>, extra: Partial<FreeCheck> = {}): FreeCheck => ({
  slot: 1, total: 37, counts: { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0, rejected: 0, missing: 0, ...counts },
  notes: [], top6: 'same', engineList: null, mdlChecked: 0, mdlMismatch: 0, problems: [], ...extra,
})
const ready = { running: false, invalid: false, gridStatus: 'ready' as const }

test('free play: all identical', () => {
  const v = describeFree(free({ identical: 37 }), ready)
  assert.equal(v.kind, 'match')
  assert.equal(v.headline, 'Matches the engine: 37 identical')
})

test('free play: equally optimal entries are named, and counted apart from identical ones', () => {
  const v = describeFree(free({ identical: 35, tie_verified: 2 }), ready)
  assert.equal(v.headline, 'Matches the engine: 35 identical, 2 equally optimal (verified)')
})

test('free play: engine results are labelled and the badge says so', () => {
  const v = describeFree(free({ identical: 35, engine_supplied: 2 }), ready)
  assert.equal(v.kind, 'partial')
  assert.equal(v.headline, 'Matches the engine: 35 identical; 2 shown from the engine')
})

test('free play: a mismatch is stated with its exact reason, never as a match', () => {
  const v = describeFree(free({ identical: 30, mismatch: 1 }, { problems: ['sketch 5: margin 0.3 vs 0.45'], top6: 'same' }), ready)
  assert.equal(v.kind, 'mismatch')
  assert.ok(v.details.some((d) => d.includes('sketch 5: margin 0.3 vs 0.45')))
  assert.ok(!v.headline.startsWith('Matches'))
})

test('free play: not checked when the grid did not load; invalid when fewer than one yes and one no', () => {
  assert.equal(describeFree(null, { ...ready, gridStatus: 'unavailable' }).kind, 'unchecked')
  assert.equal(describeFree(null, { ...ready, invalid: true }).headline, 'Pick at least one yes and one no')
  assert.equal(describeFree(null, { ...ready, running: true }).kind, 'pending')
})

test('free play: tied alternatives in the candidate list are explained', () => {
  const v = describeFree(free({ identical: 28, tie_verified: 6 }, { top6: 'explained' }), ready)
  assert.equal(v.kind, 'partial')
  assert.ok(v.details.some((d) => d.includes('differs because of tied alternatives')))
})

const preset = (counts: Partial<PresetCheck['counts']>, same = true): PresetCheck => ({
  solves: 12, counts: { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0, ...counts }, notes: [], extra: 0,
  candidates: { same, mine: Array(6).fill('x'), recorded: Array(6).fill('x') }, problems: same ? [] : ['the candidate order differs from the recorded run'],
})

test('presets: the statement of SPEC 7.1', () => {
  const v = describePreset(preset({ identical: 12 }), false)
  assert.equal(v.kind, 'match')
  assert.equal(v.headline, 'Matches the recorded engine run: 12 of 12 re-solved identically, same 6 candidates, same order')
})

test('presets: a different candidate order is a difference', () => {
  assert.equal(describePreset(preset({ identical: 12 }, false), false).kind, 'mismatch')
})
