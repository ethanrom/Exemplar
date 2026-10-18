import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { PageHeader, Section, pageMetadata, requirePage } from '@/components/index.ts'
import { DV } from '@/components/lab/DataValue.tsx'
import {
  dataRoot, loadCalibration, loadCredits, loadCurated, loadLibrary, loadRule, loadRun, loadSketches,
} from '@/lib/data/index.ts'
import type { LabProps, LabRule, PresetSlug } from './_lib/types.ts'
import { LabClient } from './_components/LabClient.tsx'
import type { ParityReport } from './_components/FreePane.tsx'

export const metadata = pageMetadata('lab')

// SPEC 3.2. The preset (the recorded teach run) and free play on the curated clips, in one workbench. The server reads the
// export at build time; the client re-runs the offline logic in a Web Worker and compares it with the engine's results.
function loadLabProps(): LabProps {
  const runs = { 'p1-playground': loadRun('p1-playground') } as Record<PresetSlug, ReturnType<typeof loadRun>>
  const rules: Record<string, LabRule> = {}
  for (const run of Object.values(runs)) {
    for (const slug of run.candidates) {
      const { ast: _ast, ...rest } = loadRule(slug)
      rules[slug] = rest
    }
  }
  const credits: LabProps['credits'] = {}
  for (const c of loadCredits()) credits[c.id] = { id: c.id, group: c.group, title: c.title, basis: c.permission.basis }
  return {
    library: loadLibrary(),
    credits,
    runs,
    rules,
    curated: loadCurated(),
    sketches: loadSketches(),
    cal: loadCalibration(),
  }
}

function loadParity(): ParityReport | null {
  const p = path.join(dataRoot(), 'grid', 'parity-report.json')
  return existsSync(p) ? (JSON.parse(readFileSync(p, 'utf-8')) as ParityReport) : null
}

export default function LabPage() {
  const page = requirePage('lab')
  const props = loadLabProps()
  return (
    <>
      <PageHeader title={page.title} subtitle={page.purpose} />

      <Section id="explainer" title="What the Lab does">
        <p data-src="data/lab/sketches.json" className="max-w-3xl text-sm text-ex-ink2">
          Replay a recorded teaching session, or change the examples and watch the rule search re-run in your browser over a recorded bank of{' '}
          <DV src="lab/sketches.json">{props.sketches.length}</DV> sketches.
        </p>
      </Section>

      <LabClient props={props} parity={loadParity()} />
    </>
  )
}
