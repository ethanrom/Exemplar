// Chapter 4 recomputes the recorded decisions in the browser; at the recorded value it must reproduce them exactly.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadLive, loadRule, loadTrace } from '../../../lib/data/load.ts'
import { parseCached } from '../../../components/lab/core/rules.ts'
import { explore, matchesRecorded, singleHole } from './explore.ts'

test('all five live events x both deployed rules: the recomputation equals the recorded decision exactly', () => {
  const live = loadLive()
  let checked = 0
  let witnesses = 0
  for (const ev of live.events) {
    const trace = loadTrace(ev.alias)
    for (const dec of ev.decisions) {
      const rule = loadRule(dec.rule)
      const sketch = parseCached(rule.sketch_text)
      const hole = singleHole(sketch)
      const value = hole ? (rule.holes[hole] as number) : null
      const x = explore(sketch, trace, hole, value)
      assert.ok(matchesRecorded(x.witness, dec), `${ev.alias} ${dec.rule}`)
      assert.equal(x.witness.score > dec.tau, dec.fired, `${ev.alias} ${dec.rule} fired`)
      checked++
      if (dec.witness) witnesses++
    }
  }
  assert.equal(checked, 10)
  assert.equal(witnesses, 4)
})

test('the package rule on live event 3 matches at 15 s and stops matching past the longest hold', () => {
  const live = loadLive()
  const ev = live.events.find((e) => e.order === 3)!
  const rule = loadRule('package-deployed')
  const sketch = parseCached(rule.sketch_text)
  const trace = loadTrace(ev.alias)
  assert.ok(explore(sketch, trace, 'd', 15).witness.score > 0)
  assert.ok(explore(sketch, trace, 'd', 29).witness.score > 0)
  assert.ok(explore(sketch, trace, 'd', 30).witness.score < 0)
})
