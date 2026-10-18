// Chapter 5's computation: scores of the recorded random sample, recomputed from the recorded facts, and the
// calibration made from them. Pure; a node test pins it to calibration/package.json.
import { robustness } from '../../../lib/dsl/index.ts'
import { calibrateScores } from '../../../lib/synth/conformal.ts'
import type { Calibration } from '../../../lib/synth/conformal.ts'
import type { CalDoc, CalibrationJson, TraceJson } from '../../../lib/data/types.ts'
import { asTrace, parseCached } from './rules.ts'

export type RandomScore = { alias: string; label: 'pos' | 'neg'; score: number; recorded: number }

export type Recomputed = {
  scores: RandomScore[]
  calibration: Calibration
  /** Names of the calibration fields that differ from the recorded ones (empty = identical). */
  differences: string[]
  /** The number of recomputed scores equal to the recorded ones. */
  scoresIdentical: number
}

const close = (a: number | null, b: number | null, tol: number) => (a === null || b === null ? a === b : Math.abs(a - b) <= tol)

/** Fields of a recomputed calibration that differ from the recorded one (CI within 1e-9, everything else exact). */
export function calibrationDifferences(mine: Calibration, rec: CalibrationJson): string[] {
  const out: string[] = []
  if (mine.alpha !== rec.alpha) out.push('alpha')
  if (mine.n_random_neg !== rec.n_random_neg) out.push('n_random_neg')
  if (mine.n_random_pos !== rec.n_random_pos) out.push('n_random_pos')
  if (mine.k !== rec.k) out.push('k')
  if (mine.tau !== rec.tau) out.push('tau')
  if (mine.guarantee !== rec.guarantee) out.push('guarantee')
  if (mine.message !== rec.message) out.push('message')
  if (mine.delta !== rec.delta) out.push('delta')
  if (!close(mine.recall, rec.recall, 1e-12)) out.push('recall')
  const a = mine.recall_ci95
  const b = rec.recall_ci95
  if ((a === null) !== (b === null) || (a && b && (!close(a[0], b[0], 1e-9) || !close(a[1], b[1], 1e-9)))) out.push('recall_ci95')
  return out
}

/** Score the deployed rule on every clip of the recorded random sample and calibrate; compare with the recorded calibration. */
export function recomputeCalibration(ruleDsl: string, cal: CalDoc, traces: Record<string, TraceJson>): Recomputed {
  const rule = parseCached(ruleDsl)
  const scores: RandomScore[] = cal.random.map((r) => ({
    alias: r.alias, label: r.label, recorded: r.score,
    score: robustness(rule, asTrace(traces[r.alias] as TraceJson)),
  }))
  const pos = scores.filter((s) => s.label === 'pos').map((s) => s.score)
  const neg = scores.filter((s) => s.label === 'neg').map((s) => s.score)
  const calibration = calibrateScores(pos, neg, cal.alpha)
  return {
    scores, calibration,
    differences: calibrationDifferences(calibration, cal.calibration),
    scoresIdentical: scores.filter((s) => s.score === s.recorded).length,
  }
}

/** Negatives sorted ascending (rank 1 = smallest), the way the rank k counts them. */
export function rankedNegatives(scores: readonly RandomScore[]): (RandomScore & { rank: number })[] {
  return scores.filter((s) => s.label === 'neg').sort((x, y) => x.score - y.score || (x.alias < y.alias ? -1 : 1)).map((s, i) => ({ ...s, rank: i + 1 }))
}
