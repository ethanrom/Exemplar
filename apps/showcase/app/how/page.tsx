import { PageHeader, pageMetadata, requirePage } from '@/components/index.ts'
import { loadCalibration, loadLibrary, loadLive, loadRule, loadRun, loadTrace } from '@/lib/data/index.ts'
import type { ClipCard, RuleDoc, TraceJson } from '@/lib/data/types.ts'
import { HowChapters } from './_components/HowChapters.tsx'
import type { HowData, HowRun, SlimRule } from './_lib/types.ts'

export const metadata = pageMetadata('how')

const slim = (r: RuleDoc): SlimRule => {
  const { backtest: _backtest, ast: _ast, ...rest } = r
  return rest
}

// SPEC 3.4. Five chapters, each on one recorded artifact; the interactions re-run Exemplar's offline logic in the browser.
// Everything is read from the export at build time (server side) and handed to one client component.
function loadHowData(): HowData {
  const library = loadLibrary()
  const cardOf = (alias: string): ClipCard => library.find((c) => c.alias === alias) as ClipCard
  const live = loadLive()
  const cal = loadCalibration()

  const p1 = loadRun('p1-playground')
  const runs: HowRun[] = [
    { slug: 'p1-playground' as const, rule: 'package-deployed' },
  ].map(({ slug, rule }) => {
    const run = loadRun(slug)
    return { slug, title: run.title, rule: slim(loadRule(rule)), examples: run.examples }
  })

  const aliases = new Set<string>()
  for (const e of live.events) aliases.add(e.alias)
  for (const r of runs) for (const e of r.examples) aliases.add(e.alias)
  for (const r of cal.random) aliases.add(r.alias)
  const traces: Record<string, TraceJson> = {}
  const cards: Record<string, ClipCard> = {}
  for (const a of [...aliases].sort()) {
    traces[a] = loadTrace(a)
    cards[a] = cardOf(a)
  }

  return {
    traces,
    cards,
    live,
    deployed: { 'package-deployed': slim(loadRule('package-deployed')), 'vehicle-deployed': slim(loadRule('vehicle-deployed')) },
    p1: { slug: p1.slug, title: p1.title, events: p1.events, proposer_note: p1.proposer_note, candidates: p1.candidates, proposals_by_round: p1.proposals_by_round },
    runs,
    cal,
    packageRule: slim(loadRule('package-deployed')),
  }
}

export default function HowPage() {
  const page = requirePage('how')
  const data = loadHowData()
  return (
    <>
      <PageHeader title={page.title} subtitle={page.purpose} />
      <p className="-mt-6 mb-10 max-w-3xl text-sm text-ex-ink2">
        Every chapter uses one recorded artifact, and every control re-runs Exemplar’s offline logic in your browser on that artifact: the same rule evaluator, the same witness extraction and the same rank arithmetic as the engine, checked against its outputs. Nothing on this page calls a model.
      </p>
      <HowChapters data={data} />
    </>
  )
}
