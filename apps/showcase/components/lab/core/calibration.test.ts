// The recorded part of chapter 5 equals calibration/package.json, and the browser recomputation reproduces it.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadCalibration, loadRule, loadTrace } from '../../../lib/data/load.ts'
import type { TraceJson } from '../../../lib/data/types.ts'
import { conformalRank, minNegatives } from '../../../lib/synth/conformal.ts'
import { rankedNegatives, recomputeCalibration } from './calibration.ts'

test('chapter 5: the file equals the deployed rule calibration, and the recomputation is identical', () => {
  const cal = loadCalibration()
  const rule = loadRule('package-deployed')
  assert.deepEqual(cal.calibration, rule.calibration)
  const traces: Record<string, TraceJson> = {}
  for (const r of cal.random) traces[r.alias] = loadTrace(r.alias)
  const re = recomputeCalibration(rule.dsl_text, cal, traces)
  assert.deepEqual(re.differences, [])
  assert.equal(re.scoresIdentical, cal.random.length)
  assert.equal(re.calibration.k, conformalRank(re.calibration.n_random_neg, cal.alpha))
  // the k-th smallest negative is tau_alpha; tau is floored at 0
  const neg = rankedNegatives(re.scores)
  assert.equal(neg.length, cal.calibration.n_random_neg)
  assert.equal(neg[(cal.calibration.k as number) - 1]?.score, re.calibration.tau_alpha)
  assert.equal(minNegatives(cal.alpha), 9)
})
