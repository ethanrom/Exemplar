import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { Badge, Card, Placeholder, ScrollRegion } from '@/components/index.ts'
import { dataRoot } from '../../lib/data/load.ts'

// "This site's own check" (SPEC 3.6): the parity report of the TypeScript port against the Python engine goldens
// (lib/dsl and lib/synth). Rendered only from parity.json (data/parity.json, or public/data/parity.json), written by
// `node scripts/parity/make-parity.mjs` from the test runs and the golden files; never typed by hand.
// Until that file exists the slot shows a placeholder; once the file exists the report appears with no code change.

type Family = {
  cases: number
  identical: number
  tie_verified: number
  engine_supplied: number
  excluded_operational: number
  mismatches: number
}
type Preset = { solves: number; identical: number; engine_supplied: number }
export type ParityReport = {
  generated_on: string
  engine_commit: string
  families: Record<string, Family>
  presets?: Record<string, Preset>
}

const FAMILY_KEYS = ['cases', 'identical', 'tie_verified', 'engine_supplied', 'excluded_operational', 'mismatches'] as const

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)
const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/** Throws on a malformed report, so a bad file fails the build instead of rendering partial numbers. */
export function parseParity(raw: unknown): ParityReport {
  if (!isObj(raw)) throw new Error('parity.json: not an object')
  const { generated_on, engine_commit, families, presets } = raw
  if (typeof generated_on !== 'string' || typeof engine_commit !== 'string') throw new Error('parity.json: generated_on / engine_commit')
  if (!isObj(families)) throw new Error('parity.json: families')
  const outFamilies: Record<string, Family> = {}
  for (const [name, f] of Object.entries(families)) {
    if (!isObj(f)) throw new Error(`parity.json: family ${name}`)
    const row = {} as Family
    for (const k of FAMILY_KEYS) {
      const v = f[k]
      if (!isNum(v)) throw new Error(`parity.json: family ${name} lacks numeric ${k}`)
      row[k] = v
    }
    outFamilies[name] = row
  }
  let outPresets: Record<string, Preset> | undefined
  if (presets !== undefined) {
    if (!isObj(presets)) throw new Error('parity.json: presets')
    outPresets = {}
    for (const [name, p] of Object.entries(presets)) {
      if (!isObj(p) || !isNum(p.solves) || !isNum(p.identical) || !isNum(p.engine_supplied)) throw new Error(`parity.json: preset ${name}`)
      outPresets[name] = { solves: p.solves, identical: p.identical, engine_supplied: p.engine_supplied }
    }
  }
  return { generated_on, engine_commit, families: outFamilies, presets: outPresets }
}

/** Reads parity.json (data/ first, then public/data/) at build time; this is a server component. Null when absent. */
export function loadParity(): ParityReport | null {
  const candidates = [join(dataRoot(), 'parity.json'), join(process.cwd(), 'public', 'data', 'parity.json')]
  const file = candidates.find((f) => existsSync(f))
  if (!file) return null
  return parseParity(JSON.parse(readFileSync(file, 'utf-8')))
}

const fmt = (n: number) => n.toLocaleString('en-US')
const TH = 'px-3 py-2 text-right font-medium text-ex-ink first:text-left'
const TD = 'px-3 py-2 text-right tabular-nums first:text-left'

export function ParitySlot() {
  const report = loadParity()
  if (!report) {
    return (
      <Placeholder owner="the parity report">
        Parity of the TypeScript port (<code className="font-mono text-xs">lib/dsl</code> and <code className="font-mono text-xs">lib/synth</code>) against
        the Python engine goldens appears here once <code className="font-mono text-xs">data/parity.json</code> exists. It is rendered from that
        file only.
      </Placeholder>
    )
  }
  const families = Object.entries(report.families)
  const presets = Object.entries(report.presets ?? {})
  const mismatches = families.reduce((sum, [, f]) => sum + f.mismatches, 0)
  return (
    <Card padding="lg">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Badge tone={mismatches === 0 ? 'pos' : 'neg'}>{mismatches === 0 ? 'No mismatches' : `${fmt(mismatches)} mismatches`}</Badge>
        <p className="text-sm text-ex-ink2">
          Engine commit <span className="font-mono text-xs" data-src="parity:engine_commit">{report.engine_commit.slice(0, 10)}</span>, generated{' '}
          <span data-src="parity:generated_on">{report.generated_on}</span>.
        </p>
      </div>
      <div className="mt-4">
        <ScrollRegion label="Parity by test family" className="max-h-[34rem]">
          <table className="w-max min-w-full border-collapse text-sm text-ex-ink2">
            <caption className="sr-only">Cases per golden family, and how the TypeScript port compares with the Python engine</caption>
            <thead>
              <tr className="border-b border-ex-line2">
                <th scope="col" className={TH}>Family</th>
                <th scope="col" className={TH}>Cases</th>
                <th scope="col" className={TH}>Identical</th>
                <th scope="col" className={TH}>Tie-verified</th>
                <th scope="col" className={TH}>Engine-supplied</th>
                <th scope="col" className={TH}>Excluded (operational)</th>
                <th scope="col" className={TH}>Mismatches</th>
              </tr>
            </thead>
            <tbody>
              {families.map(([name, f]) => (
                <tr key={name} className="border-t border-ex-line" data-src={`parity:family:${name}`}>
                  <th scope="row" className={`${TD} font-mono text-xs font-normal text-ex-ink`}>{name}</th>
                  <td className={TD}>{fmt(f.cases)}</td>
                  <td className={TD}>{fmt(f.identical)}</td>
                  <td className={TD}>{fmt(f.tie_verified)}</td>
                  <td className={TD}>{fmt(f.engine_supplied)}</td>
                  <td className={TD}>{fmt(f.excluded_operational)}</td>
                  <td className={`${TD} font-medium ${f.mismatches === 0 ? 'text-ex-pos' : 'text-ex-neg'}`}>{fmt(f.mismatches)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      </div>
      <p className="mt-4 max-w-3xl text-xs text-ex-ink3">
        Identical: the browser computed the same result as the engine, without reading it. Tie-verified: equally optimal, the engine chose another of
        the tied alternatives, verified here. Engine-supplied: shown from the engine, not re-solved here.
      </p>
      {presets.length > 0 && (
        <div className="mt-4">
          <ScrollRegion label="Parity on the recorded presets" className="max-h-60">
            <table className="w-max min-w-full border-collapse text-sm text-ex-ink2">
              <caption className="sr-only">Re-solving the recorded presets in the browser</caption>
              <thead>
                <tr className="border-b border-ex-line2">
                  <th scope="col" className={TH}>Preset</th>
                  <th scope="col" className={TH}>Solves</th>
                  <th scope="col" className={TH}>Identical</th>
                  <th scope="col" className={TH}>Engine-supplied</th>
                </tr>
              </thead>
              <tbody>
                {presets.map(([name, p]) => (
                  <tr key={name} className="border-t border-ex-line" data-src={`parity:preset:${name}`}>
                    <th scope="row" className={`${TD} font-mono text-xs font-normal text-ex-ink`}>{name}</th>
                    <td className={TD}>{fmt(p.solves)}</td>
                    <td className={TD}>{fmt(p.identical)}</td>
                    <td className={TD}>{fmt(p.engine_supplied)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        </div>
      )}
    </Card>
  )
}
