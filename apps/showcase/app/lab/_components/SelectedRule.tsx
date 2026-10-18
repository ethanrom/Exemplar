import { Badge } from '@/components/Badge.tsx'
import { Card } from '@/components/Card.tsx'
import { DslBlock } from '@/components/CodeBlock.tsx'
import { SELECTION_TEXT, type CandidateView } from '@/components/lab/CandidateList.tsx'
import { fmtPlain, ordinal } from '@/components/lab/core/format.ts'
import { DV } from '@/components/lab/DataValue.tsx'
import { Z3Badge } from '@/components/z3/Z3Badge.tsx'

/** The selected rule, printed from the rule by code: its English, its text, the filled blanks and the margin. */
export function SelectedRule({
  rule, experimental, titleOf,
}: { rule: CandidateView | null; experimental: boolean; titleOf: (alias: string) => string }) {
  if (!rule) return <p className="text-sm text-ex-ink2">Select a candidate to see it here.</p>
  const holes = Object.entries(rule.holes)
  return (
    <Card padding="md" data-src="lib/synth (computed here) or data/rules/*.json (recorded)">
      <div className="flex flex-wrap items-center gap-1.5">
        {rule.recorded && <Badge tone="neutral" icon="flag">recorded rank: {ordinal(rule.recorded.position)} of {rule.recorded.of}</Badge>}
        {rule.selection && <Badge tone="pos" icon="check">{SELECTION_TEXT[rule.selection]}</Badge>}
        {experimental && <Badge tone="warn" icon="warning">Experimental rule: no recorded guarantee</Badge>}
        <Z3Badge itemKey={rule.key} />
      </div>
      <p className="mt-3 text-md font-medium text-ex-ink">{rule.english}</p>
      <div className="mt-3"><DslBlock text={rule.dsl_text} size="sm" label="The selected rule in the Exemplar rule language" /></div>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        {holes.map(([k, v]) => (
          <div key={k}><dt className="text-xs text-ex-ink3">Blank <span className="font-mono text-ex-syn-hole">?{k}</span> filled with</dt><dd className="font-mono tabular-nums text-ex-ink"><DV src="solver output">{fmtPlain(v)} s</DV></dd></div>
        ))}
        {holes.length === 0 && <div><dt className="text-xs text-ex-ink3">Blanks</dt><dd className="text-ex-ink">none</dd></div>}
        <div><dt className="text-xs text-ex-ink3">Margin</dt><dd className="font-mono tabular-nums text-ex-ink"><DV src="solver output">{fmtPlain(rule.margin)}</DV></dd></div>
        <div><dt className="text-xs text-ex-ink3">Description length</dt><dd className="font-mono tabular-nums text-ex-ink"><DV src="lib/synth mdl">{fmtPlain(rule.mdl)}</DV></dd></div>
        <div><dt className="text-xs text-ex-ink3">Examples it misses</dt><dd className="text-ex-ink"><DV src="solver output">{rule.violated.length}</DV>{rule.violated.length > 0 && <span className="block text-xs text-ex-warn">{rule.violated.map(titleOf).join('; ')}</span>}</dd></div>
      </dl>
    </Card>
  )
}
