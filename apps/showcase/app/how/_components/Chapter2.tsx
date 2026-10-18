'use client'

import { useMemo } from 'react'
import { Badge } from '@/components/Badge.tsx'
import { Card } from '@/components/Card.tsx'
import { Dsl } from '@/components/CodeBlock.tsx'
import { Icon } from '@/components/Icon.tsx'
import { fmtPlain } from '@/components/lab/core/format.ts'
import { parseCached } from '@/components/lab/core/rules.ts'
import { holesOf, toEnglish, toText } from '@/lib/dsl/index.ts'
import type { RunDoc, RunEvent } from '@/lib/data/types.ts'

type Sketch = {
  text: string
  round: number
  backfill: boolean
  english: string
  holes: string[]
  result?: RunEvent
}

/** Chapter 2: the sketches the agent wrote in the recorded session, each with its blank, and one the type checker sent back. */
export function Chapter2({ p1 }: { p1: Pick<RunDoc, 'slug' | 'title' | 'events' | 'proposer_note' | 'proposals_by_round'> }) {
  const { sketches, rejected } = useMemo(() => {
    const fromModel = new Set(p1.proposals_by_round.filter((r) => !r.backfill).flatMap((r) => r.texts))
    const backfill = new Set(p1.proposals_by_round.filter((r) => r.backfill).flatMap((r) => r.texts))
    const seen = new Map<string, Sketch>()
    for (const e of p1.events) {
      if (e.type === 'sketch_proposed' && e.sketch && !seen.has(e.sketch)) {
        const rule = parseCached(e.sketch)
        seen.set(e.sketch, { text: e.sketch, round: e.round ?? 1, backfill: backfill.has(e.sketch) && !fromModel.has(e.sketch), english: toEnglish(rule), holes: holesOf(rule) })
      }
      if (e.type === 'solve_result' && e.sketch && seen.has(e.sketch)) (seen.get(e.sketch) as Sketch).result = e
    }
    const rej = p1.events.filter((e) => e.type === 'typecheck_failed')
    return { sketches: [...seen.values()], rejected: rej }
  }, [p1.events, p1.proposals_by_round])

  return (
    <div data-src="data/runs/p1-playground.json" className="space-y-6">
      <p className="max-w-3xl text-sm text-ex-ink2">
        {p1.proposer_note}. The model does not write the numbers. It writes the <em>shape</em> of a rule and leaves each number as a blank, written <Dsl text="?d" /> or <Dsl text="?b" />. A deterministic printer turns each sketch into plain English, blank included; no model paraphrases it. When the model’s rounds left fewer than six consistent rules, the run topped up from a fixed template library; those sketches are marked.
      </p>

      <ul className="grid gap-3 md:grid-cols-2" aria-label="Sketches the agent proposed in the recorded session">
        {sketches.map((s) => {
          const r = s.result
          return (
            <li key={s.text}>
              <Card padding="sm" className="h-full">
                <div className="flex flex-wrap items-center gap-1.5">
                  {s.backfill
                    ? <Badge tone="neutral" icon="layers" title="Added from the template library after the model’s rounds; the model did not write it">Template back-fill</Badge>
                    : <Badge tone="accent" icon="spark">Round {s.round}</Badge>}
                  <Badge tone="neutral" icon="sliders">{s.holes.length === 0 ? 'no blanks' : s.holes.length === 1 ? 'one blank' : `${s.holes.length} blanks`}: {s.holes.map((h) => `?${h}`).join(', ') || 'none'}</Badge>
                </div>
                <pre className="mt-2 whitespace-pre-wrap break-words rounded-md border border-ex-line bg-ex-bg px-3 py-2 font-mono text-xs leading-5"><code><Dsl text={toText(parseCached(s.text))} /></code></pre>
                <p className="mt-2 text-sm text-ex-ink2">{s.english}</p>
                {r && (
                  <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-ex-line pt-2 font-mono text-xs tabular-nums text-ex-ink2">
                    <span className="font-sans text-ex-ink3">recorded solve</span>
                    <span>{r.result}</span>
                    {r.holes && Object.entries(r.holes).map(([k, v]) => (
                      <span key={k}><span className="text-ex-syn-hole">?{k}</span> = {fmtPlain(v)}</span>
                    ))}
                    {r.margin != null && <span><span className="font-sans text-ex-ink3">margin</span> {fmtPlain(r.margin)}</span>}
                    {r.violated_clip_ids && r.violated_clip_ids.length > 0 && <span className="text-ex-warn">{r.violated_clip_ids.length} example{r.violated_clip_ids.length > 1 ? 's' : ''} missed</span>}
                  </p>
                )}
              </Card>
            </li>
          )
        })}
      </ul>

      {rejected.length > 0 && (
        <Card tone="warn" padding="sm">
          <div className="flex items-start gap-3">
            <Icon name="shield" className="mt-0.5 h-4 w-4 shrink-0 text-ex-warn" />
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-ex-ink">The type checker catches the agent’s mistakes</h3>
              <p className="mt-1 text-sm text-ex-ink2">
                In this recorded session the agent proposed a sketch the grammar does not allow. The checker sent it back with this message, word for word, and the agent revised it.
              </p>
              <p className="mt-2 text-xs font-medium text-ex-ink3">Sketch sent back</p>
              <pre className="mt-1 whitespace-pre-wrap break-words rounded-md border border-ex-line bg-ex-bg px-3 py-2 font-mono text-xs leading-5"><code><Dsl text={rejected[0]?.sketch ?? ''} /></code></pre>
              <p className="mt-2 text-xs font-medium text-ex-ink3">Recorded error text</p>
              <pre tabIndex={0} aria-label="Recorded error text (scrolls sideways; the caret marks the column)" className="mt-1 overflow-x-auto whitespace-pre rounded-md border border-ex-warn-line bg-ex-bg px-3 py-2 font-mono text-xs leading-5 text-ex-ink"><code>{rejected[0]?.error}</code></pre>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
