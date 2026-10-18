import { Card, TextLink } from '@/components/index.ts'
import { ClaimSource, ClaimValue } from './ClaimValue.tsx'
import { FEEDBACK, HIGHLIGHTS, LOG } from './feedback-data.ts'
import { blob } from './repo.ts'

// Developer feedback: the entry count (published claim), links to the log and the product feedback, and a few
// highlights written as "what we learned and what Exemplar does about it". Anchors follow GitHub's heading slugs.

export function FeedbackLinks({ heading = 'h3', showHighlights = true }: { heading?: 'h3' | 'h4'; showHighlights?: boolean }) {
  const H = heading
  return (
    <div className="space-y-5">
      <Card padding="lg">
        <p className="text-lg font-semibold tracking-tight text-ex-ink"><ClaimValue id="friction.entries" /></p>
        <p className="mt-0.5 text-xs text-ex-ink3">Published in <ClaimSource id="friction.entries" /></p>
        <p className="mt-3 max-w-prose text-sm text-ex-ink2">
          Each entry gives the task, the steps, what we expected and what happened, a severity, the workaround we used and a concrete suggestion.
          Entries marked live were reproduced against the Ring Developer Playground. The product feedback covers every tool we used: what worked,
          onboarding, and whether we would build with it again.
        </p>
        <ul className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <li><TextLink href={blob(LOG)}>Friction log</TextLink></li>
          <li><TextLink href={blob(FEEDBACK)}>Product feedback</TextLink></li>
          <li><TextLink href={blob(FEEDBACK, '10-feature-requests')}>Feature requests</TextLink></li>
        </ul>
      </Card>

      {showHighlights && (
        <div>
          <H className="text-base font-semibold text-ex-ink">A few entries, and what Exemplar does about each</H>
          <ul className="mt-3 grid gap-3 md:grid-cols-2">
            {HIGHLIGHTS.map((h) => (
              <Card as="li" key={h.id} padding="sm" className="flex flex-col">
                <p className="text-xs text-ex-ink3"><span className="font-mono">{h.id}</span> &middot; {h.area}</p>
                <p className="mt-1.5 text-sm text-ex-ink2"><span className="font-medium text-ex-ink">What we learned.</span> {h.learned}</p>
                <p className="mt-1.5 text-sm text-ex-ink2"><span className="font-medium text-ex-ink">What Exemplar does.</span> {h.did}</p>
                <p className="mt-auto pt-2 text-sm"><TextLink href={blob(LOG, h.anchor)}>Read {h.id}</TextLink></p>
              </Card>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
