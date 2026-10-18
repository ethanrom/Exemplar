// The wording of the engine-check badge (SPEC 6.4, 7.1, 7.2), kept apart from the component so it can be tested.
import type { FreeCheck, PresetCheck } from './compare.ts'

export type CheckKind = 'idle' | 'pending' | 'match' | 'partial' | 'mismatch' | 'unchecked'

export type CheckView = {
  kind: CheckKind
  /** The badge's one-line statement. */
  headline: string
  /** Further sentences (what was not checked, the exact mismatches, ...). */
  details: string[]
}

const plural = (n: number, one: string, many = one + (/(?:s|x|z|ch|sh)$/.test(one) ? 'es' : 's')) => `${n} ${n === 1 ? one : many}`

export function describePreset(check: PresetCheck | null, running: boolean): CheckView {
  if (running) return { kind: 'pending', headline: 'Recomputing in your browser…', details: [] }
  if (check === null) return { kind: 'idle', headline: 'Not recomputed yet', details: ['Press “Recompute in your browser” to re-solve every recorded sketch here and compare with the recorded engine run.'] }
  const { identical, tie_verified, engine_supplied, mismatch } = check.counts
  const n = check.solves
  const details: string[] = []
  if (check.problems.length > 0) details.push(...check.problems.map((p) => `Differs from the engine: ${p}`))
  if (engine_supplied > 0) details.push(`${plural(engine_supplied, 'result is', 'results are')} shown from the engine run (beyond the in-browser budget or an operational status); they are not counted as re-solved here.`)
  if (tie_verified > 0) details.push(`${plural(tie_verified, 'solve')} equally optimal: the engine chose another of the tied alternatives (verified).`)
  if (mismatch > 0 || !check.candidates.same) {
    return { kind: 'mismatch', headline: `Differs from the recorded engine run: ${identical} of ${n} re-solved identically`, details }
  }
  const cands = `same ${check.candidates.recorded.length} candidates, same order`
  if (engine_supplied > 0 || tie_verified > 0) {
    return { kind: 'partial', headline: `Matches the recorded engine run: ${identical} of ${n} re-solved identically${tie_verified ? `, ${tie_verified} equally optimal (verified)` : ''}${engine_supplied ? `, ${engine_supplied} engine result${engine_supplied > 1 ? 's' : ''}` : ''}; ${cands}`, details }
  }
  return { kind: 'match', headline: `Matches the recorded engine run: ${identical} of ${n} re-solved identically, ${cands}`, details }
}

export function describeFree(check: FreeCheck | null, state: { running: boolean; invalid: boolean; gridStatus: 'loading' | 'ready' | 'unavailable' }): CheckView {
  if (state.invalid) return { kind: 'idle', headline: 'Pick at least one yes and one no', details: [] }
  if (state.running) return { kind: 'pending', headline: 'Re-solving in your browser…', details: [] }
  if (state.gridStatus === 'unavailable') {
    return { kind: 'unchecked', headline: 'Not checked against the engine', details: ['The precomputed engine results could not be loaded, so this solve was not compared. The result below is still computed here.'] }
  }
  if (check === null) {
    return { kind: 'pending', headline: state.gridStatus === 'loading' ? 'Loading the engine results to compare…' : 'Comparing with the engine…', details: [] }
  }
  const c = check.counts
  const matched = c.identical + c.rejected
  const details: string[] = []
  if (c.tie_verified > 0) details.push(`${plural(c.tie_verified, 'sketch')} equally optimal: the engine chose another of the tied alternatives with the same score and margin, verified here by placing that set.`)
  if (c.engine_supplied > 0) details.push(`${plural(c.engine_supplied, 'sketch')} shown from the engine (the engine’s placement depends on its solver’s model point, or the sketch is too large to re-solve here).`)
  if (c.missing > 0) details.push(`${plural(c.missing, 'sketch')} missing from the precomputed grid.`)
  if (check.mdlMismatch > 0) details.push(`${plural(check.mdlMismatch, 'description length')} differ from the engine.`)
  for (const p of check.problems) details.push(`Differs from the engine: ${p}`)
  if (c.mismatch > 0 || check.mdlMismatch > 0 || check.top6 === 'mismatch') {
    return { kind: 'mismatch', headline: `Differs from the engine on ${plural(c.mismatch + check.mdlMismatch + (check.top6 === 'mismatch' ? 1 : 0), 'item')}: ${matched} identical`, details }
  }
  const parts = [`${matched} identical`]
  if (c.tie_verified > 0) parts.push(`${c.tie_verified} equally optimal (verified)`)
  const headline = `Matches the engine: ${parts.join(', ')}${c.engine_supplied > 0 ? `; ${c.engine_supplied} shown from the engine` : ''}`
  if (check.top6 === 'explained') details.push('The candidate list differs because of tied alternatives; the engine’s own list is available below.')
  if (c.engine_supplied > 0 || check.top6 === 'explained') return { kind: 'partial', headline, details }
  return { kind: 'match', headline, details }
}
