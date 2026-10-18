import { Card, CodeBlock, PageHeader, ScrollRegion, Section, TextLink, pageMetadata, requirePage } from '@/components/index.ts'
import { ClaimSource, ClaimValue } from '@/components/evidence/ClaimValue.tsx'
import { CostChart } from '@/components/evidence/CostChart.tsx'
import { FeedbackLinks } from '@/components/evidence/FeedbackLinks.tsx'
import { ParitySlot } from '@/components/evidence/ParitySlot.tsx'
import { VerificationRow } from '@/components/evidence/VerificationRow.tsx'
import { COST_DOC, COST_SCRIPT, COST_SVG, loadCostTable } from '@/components/evidence/cost-table.ts'
import { REPO_URL, blob } from '@/components/evidence/repo.ts'
import { README_TESTS_ANCHOR, ROWS } from './rows.ts'

export const metadata = pageMetadata('evidence')

const COST_CLAIMS = ['cost.per_event_live', 'cost.per_event_mean', 'cost.rule_eval', 'cost.zero_shot_per_rule'] as const

export default function EvidencePage() {
  const page = requirePage('evidence')
  const costRows = loadCostTable()
  const accessibility = ROWS.filter((r) => r.id === 'accessibility')
  const verification = ROWS.filter((r) => r.id !== 'accessibility')

  return (
    <>
      <PageHeader title={page.title} subtitle={page.purpose} />

      <p className="-mt-4 mb-10 max-w-prose text-sm text-ex-ink2">
        Each row gives the claim, the number as published in the repository, how it was measured, the command that reproduces it and the
        source files. Commands run from the root of the <TextLink href={REPO_URL}>Exemplar repository</TextLink>; they are the ones in the
        README’s <TextLink href={blob('README.md', README_TESTS_ANCHOR)}>tests and verification</TextLink> section, with Python run through uv.
      </p>

      <Section id="verification" title="Verification table" description="Each row: the claim, the number, how it was measured, the command and the file.">
        <ul className="space-y-4">
          {verification.map((row) => <VerificationRow key={row.id} row={row} />)}
        </ul>
      </Section>

      <Section
        id="own-check"
        title="This site’s own check"
        description="The browser code on this site is a TypeScript port of the Python engine. This report compares the two on golden files the engine generated."
      >
        <ParitySlot />
      </Section>

      <Section id="cost" title="Cost" description="What one watched event costs, and how that changes as rules are added.">
        <div className="space-y-6">
          <Card padding="lg">
            <h3 className="text-base font-semibold text-ex-ink">Published figures</h3>
            <ul className="mt-3 grid gap-x-8 gap-y-3 md:grid-cols-2" aria-label="Published cost figures">
              {COST_CLAIMS.map((id) => (
                <li key={id} className="min-w-0">
                  <p className="text-md font-semibold tracking-tight text-ex-ink"><ClaimValue id={id} /></p>
                  <p className="mt-0.5 text-xs text-ex-ink3">Published in <ClaimSource id={id} /></p>
                </li>
              ))}
            </ul>
          </Card>

          <Card padding="lg">
            <h3 className="text-md font-semibold tracking-tight text-ex-ink">Model cost per event as rules are added</h3>
            <p className="mb-4 mt-1 max-w-prose text-sm text-ex-ink2">
              Exemplar has Claude read an event once and scores every rule on the cached facts, so the cost stays at <ClaimValue id="cost.exemplar_flat" /> per
              event. The comparison line asks a strong vision model one question per rule, at <ClaimValue id="cost.zero_shot_per_rule" /> per
              rule per event. One-time teaching cost is not included.
            </p>
            <CostChart rows={costRows} />
          </Card>

          <div>
            <h3 className="text-base font-semibold text-ex-ink">The same numbers as a table</h3>
            <p className="mt-0.5 text-sm text-ex-ink2">
              Copied from <TextLink href={blob(COST_DOC)} className="font-mono text-xs">{COST_DOC}</TextLink> in the repository, exactly as published.
            </p>
            <div className="mt-3 rounded-xl border border-ex-line bg-ex-panel">
              <ScrollRegion label="Cost per event by number of rules" className="max-h-[30rem]">
                <table className="w-full min-w-[22rem] border-collapse text-left text-sm text-ex-ink2">
                  <caption className="sr-only">Model cost in US dollars per event for 1 to 10 deployed rules</caption>
                  <thead>
                    <tr className="border-b border-ex-line2">
                      <th scope="col" className="px-3 py-2 font-medium text-ex-ink">Rules deployed</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium text-ex-ink">Exemplar</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium text-ex-ink">Zero-shot prompting</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium text-ex-ink">Ratio</th>
                    </tr>
                  </thead>
                  <tbody>
                    {costRows.map((r) => (
                      <tr key={r.rules} className="border-t border-ex-line" data-src={`cost-table:row:${r.rules}`}>
                        <th scope="row" className="px-3 py-2 font-normal tabular-nums text-ex-ink">{r.rules}</th>
                        <td className="px-3 py-2 text-right tabular-nums">{r.exemplar}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{r.zeroShot}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{r.ratio}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollRegion>
            </div>
          </div>

          <Card padding="lg">
            <h3 className="text-base font-semibold text-ex-ink">How the numbers are obtained</h3>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-ex-ink2">
              <li>
                <span className="font-medium text-ex-ink">Exemplar.</span> The mean cost of the fast model perceiving one clip, over 1,005 clips of 16
                frames each. The trace is cached, so adding a rule adds no model call; scoring a rule on a cached trace takes about 0.05 to 0.1 ms in the
                NumPy evaluator.
              </li>
              <li>
                <span className="font-medium text-ex-ink">Prompting per rule.</span> The median cost of one strong-model call on the same 16 frames (527
                calls). That baseline asks one concept per call, so n rules cost n calls per event.
              </li>
              <li>
                Both prices come from the token counts the model returned and the per-token prices in{' '}
                <TextLink href={blob('eval/harness/budget.py')} className="font-mono text-xs">eval/harness/budget.py</TextLink>. A strong-model re-check of
                events near a rule’s decision boundary is billed on top; the live Playground run did not need it.
              </li>
            </ul>
            <p className="mt-4 text-sm text-ex-ink2">
              Method, ledgers and the original chart: <TextLink href={blob(COST_DOC)}>{COST_DOC}</TextLink> and{' '}
              <TextLink href={blob(COST_SVG)}>{COST_SVG}</TextLink>. Regenerate with:
            </p>
            <CodeBlock className="mt-2" label="Command to regenerate the cost chart">{`uv run --project engine python ${COST_SCRIPT}`}</CodeBlock>
          </Card>
        </div>
      </Section>

      <Section id="accessibility" title="Accessibility" description="Worded as an automated-check result.">
        <ul className="space-y-4">
          {accessibility.map((row) => <VerificationRow key={row.id} row={row} />)}
        </ul>
      </Section>

      <Section id="feedback" title="Developer feedback" description="Entries logged while building on Ring and AWS, with links.">
        <FeedbackLinks showHighlights={false} />
      </Section>
    </>
  )
}
