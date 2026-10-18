// The Lab's comparator against the real grid: the worker's pipeline (freePlay) for some label combinations, compared with
// the engine's entries through compareFree, exactly as the page does it.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { gunzipSync } from 'node:zlib'
import { test } from 'node:test'
import { loadCurated, loadSketches, loadTrace } from '../../../lib/data/load.ts'
import { Grid } from '../../../lib/synth/compare/grid.ts'
import { freePlay, isValid, slotOf, statesOf } from '../../../lib/synth/session.ts'
import type { LabData, States } from '../../../lib/synth/session.ts'
import { asTrace } from '../../../components/lab/core/rules.ts'
import { compareFree } from './compare.ts'

const grid = new Grid(JSON.parse(gunzipSync(readFileSync(new URL('../../../data/grid/grid.json.gz', import.meta.url))).toString('utf-8')))
const cur = loadCurated()
const data: LabData = {
  curated: cur.clips.map((a) => ({ alias: a, trace: asTrace(loadTrace(a)) })),
  sketches: loadSketches().map((s) => ({ id: s.id, text: s.text })),
}
const toStates = (tri: (string | null)[]): States => tri.map((t) => (t === 'pos' ? 1 : t === 'neg' ? 2 : 0))

test('the default combination (recorded labels only) matches the grid', async () => {
  const states = toStates(cur.default)
  assert.ok(isValid(states))
  if (grid.top6(slotOf(states)) === null) return // not generated yet in a partial grid
  const r = freePlay(data, states)
  const check = await compareFree(grid, data, states, r.outcomes, r.items, () => true)
  assert.ok(check)
  assert.equal(check.counts.mismatch, 0, check.problems.join('\n'))
  assert.equal(check.counts.missing, 0)
  assert.equal(check.mdlMismatch, 0)
  assert.notEqual(check.top6, 'mismatch')
})

test('a spread of label combinations: 0 mismatches against the grid', async () => {
  let checked = 0
  const total = { identical: 0, tie_verified: 0, engine_supplied: 0, mismatch: 0 }
  // The Lab offers seven clips; the grid's eighth digit stays 0, so these slots are the grid's slots with it pinned to "not used".
  const n = data.curated.length
  for (let slot = 7; slot < 3 ** n && checked < 16; slot += 97) {
    const states = statesOf(slot, n)
    if (!isValid(states) || grid.top6(slot) === null) continue
    const r = freePlay(data, states)
    const check = await compareFree(grid, data, states, r.outcomes, r.items, () => true)
    assert.ok(check)
    assert.equal(check.counts.mismatch, 0, `slot ${slot}: ${check.problems.join('; ')}`)
    assert.notEqual(check.top6, 'mismatch', `slot ${slot}`)
    for (const k of Object.keys(total) as (keyof typeof total)[]) total[k] += check.counts[k]
    checked++
  }
  assert.ok(checked >= 12, `only ${checked} combinations were available in the grid`)
  console.log('checked', checked, JSON.stringify(total))
})
