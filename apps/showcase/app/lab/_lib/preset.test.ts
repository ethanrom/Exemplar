// P1: recompute in the browser's pipeline and compare with the recorded run, as the page does.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadRule, loadRun, loadTrace } from '../../../lib/data/load.ts'
import { runPreset } from '../../../lib/synth/session.ts'
import { asTrace } from '../../../components/lab/core/rules.ts'
import { comparePreset } from './compare.ts'
import { backtest, crossCheck, tally } from './backtest.ts'
import { loadLibrary } from '../../../lib/data/load.ts'
import type { TraceJson } from '../../../lib/data/types.ts'

for (const slug of ['p1-playground'] as const) {
  test(`${slug}: every recorded solve is re-solved identically and the candidates come out in the recorded order`, async () => {
    const run = loadRun(slug)
    const traces: Record<string, ReturnType<typeof asTrace>> = {}
    for (const e of run.examples) traces[e.alias] = asTrace(loadTrace(e.alias))
    const examples = run.examples.map((e) => ({ alias: e.alias, positive: e.label === 'pos', weight: e.weight }))
    const r = runPreset({ curated: [], sketches: [], traces }, { examples, rounds: run.proposals_by_round })
    const recordedTexts = run.candidates.map((s) => loadRule(s).dsl_text)
    const check = await comparePreset(run, r.events as never, r.items.map((i) => i.dsl_text), recordedTexts, traces, examples, () => true)
    assert.ok(check)
    assert.deepEqual(check.problems, [])
    assert.equal(check.counts.identical, check.solves)
    assert.ok(check.candidates.same)
  })
}

test('the backtest of every P1 candidate equals the engine scores recorded with the rule', () => {
  const lib = loadLibrary()
  const traces: Record<string, TraceJson> = {}
  for (const c of lib) traces[c.alias] = loadTrace(c.alias)
  for (const slug of ['p1-playground']) {
    for (const rs of loadRun(slug).candidates) {
      const rule = loadRule(rs)
      const rows = backtest(rule.dsl_text, lib, traces, rule.tau ?? 0)
      const cc = crossCheck(rows, new Map(rule.backtest.map((b) => [b.alias, b.score])))
      assert.equal(cc.checked, lib.length, rs)
      assert.deepEqual(cc.differences, [], rs)
    }
  }
  const t = tally(backtest(loadRule('package-deployed').dsl_text, lib, traces, 0))
  assert.deepEqual(t.find((x) => x.cls === 'pg_package'), { cls: 'pg_package', label: 'Playground recordings: package', matched: 20, total: 20 })
})
