import { Badge } from '@/components/Badge.tsx'
import { Card } from '@/components/Card.tsx'
import { Poster } from '@/components/lab/FrameCell.tsx'
import { DV } from '@/components/lab/DataValue.tsx'
import type { ClipCard, RunDoc } from '@/lib/data/types.ts'
import type { CreditBrief } from '../_lib/types.ts'

const SOURCE_TEXT: Record<ClipCard['source'], string> = {
  playground: 'Playground recording',
  cc_by: 'CC BY video window',
  meva: 'Parking-lot clip',
}
const BASIS_TEXT: Record<CreditBrief['basis'], string> = {
  cc_by: 'licence: CC BY',
  own_work: 'own work',
  ring_sandbox: 'Ring sandbox output',
  open_source: 'open source',
}

/** The preset's real examples, each with its label, how it entered the run, where it came from and under what permission. */
export function ExamplesPreset({
  run, cards, credits,
}: { run: RunDoc; cards: ReadonlyMap<string, ClipCard>; credits: Record<string, CreditBrief> }) {
  const pos = run.examples.filter((e) => e.label === 'pos').length
  return (
    <div data-src={`data/runs/${run.slug}.json`} className="space-y-3">
      <p className="text-sm text-ex-ink2">
        <strong className="font-medium text-ex-ink">{run.title}.</strong> The run started from <DV src={`runs/${run.slug}.json#examples`}>{run.examples.length}</DV> labelled examples ({pos} yes, {run.examples.length - pos} no), each weighing <DV src={`runs/${run.slug}.json#examples.weight`}>{run.examples[0]?.weight ?? 3}</DV>. Recorded in <DV src={`runs/${run.slug}.json#duration_ms`}>{(run.duration_ms / 1000).toFixed(1)} s</DV>. Proposer: {run.proposer_note}.
      </p>
      <ul className="space-y-2" aria-label="Examples this run was taught from">
        {run.examples.map((ex) => {
          const c = cards.get(ex.alias)
          const cr = c ? credits[c.credit] : undefined
          return (
            <li key={ex.alias}>
              <Card padding="sm" className="flex gap-3">
                <div className="w-24 shrink-0 sm:w-28"><Poster src={c?.poster} label={c ? `Poster: ${c.title}` : ex.alias} compact /></div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={ex.label === 'pos' ? 'pos' : 'neg'} icon={ex.label === 'pos' ? 'plus' : 'minus'}>{ex.label === 'pos' ? 'yes' : 'no'}</Badge>
                    <Badge tone="neutral" icon="flag" title="How the example entered the run">{ex.provenance === 'example' ? 'given as an example' : 'chosen by the active question'}</Badge>
                    {c && <Badge tone="neutral" icon="film">{SOURCE_TEXT[c.source]}</Badge>}
                    {cr && <Badge tone="neutral" icon="shield" title={cr.title}>{BASIS_TEXT[cr.basis]}</Badge>}
                  </div>
                  <p className="mt-1 text-sm font-medium text-ex-ink">{c?.title ?? ex.alias}</p>
                  {c && <p className="mt-0.5 line-clamp-2 text-xs text-ex-ink2">{c.summary}</p>}
                  {c && <p className="mt-0.5 font-mono text-xs tabular-nums text-ex-ink3">{(c.duration_ms / 1000).toFixed(1)} s</p>}
                </div>
              </Card>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
