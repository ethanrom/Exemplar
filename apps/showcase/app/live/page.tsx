import {
  Badge, ButtonLink, Card, Chip, Collapsible, Disclosure, PageHeader, Section, pageMetadata, requirePage,
} from '@/components/index.ts'
import type { TabItem } from '@/components/Tabs.tsx'
import { FactsStrip } from '@/components/story/FactsStrip.tsx'
import { FrameSheet, Still, hasFrames } from '@/components/story/Frame.tsx'
import { ReplayTabs } from '@/components/story/ReplayTabs.tsx'
import { FiredChip, RuleVerdict } from '@/components/story/Rule.tsx'
import { Src } from '@/components/story/Src.tsx'
import { WhyItFired } from '@/components/story/Witness.tsx'
import { fmtPlain, fmtScore } from '@/components/story/format.ts'
import { videoUrl, videoUrlAt } from '@/components/story/links.ts'
import { OutcomeSentence } from '@/components/story/OutcomeSentence.tsx'
import {
  CLASS_TITLE, PACKAGE_RULE, RULE_NAME, VEHICLE_RULE, classOutcomes, decisionOf,
} from '@/components/story/outcomes.ts'
import { loadClaims, loadLibrary, loadLive, loadRule, loadTrace } from '@/lib/data/index.ts'

export const metadata = pageMetadata('live')

const RULES = [PACKAGE_RULE, VEHICLE_RULE] as const

export default function LivePage() {
  const page = requirePage('live')
  const live = loadLive()
  const library = loadLibrary()
  const claims = loadClaims()
  const rules = Object.fromEntries(RULES.map((slug) => [slug, loadRule(slug)]))
  const cost = claims.claims.find((c) => c.id === 'cost.per_event_live')
  const video = videoUrl()
  const liveMoment = videoUrlAt(video, 81)
  const outcomes = classOutcomes(live)
  const events = [...live.events].sort((a, b) => a.order - b.order)

  const tabs: TabItem[] = events.map((ev) => {
    const card = library.find((c) => c.alias === ev.alias)
    if (!card) throw new Error(`live event ${ev.order} has no library clip`)
    const trace = loadTrace(ev.alias)
    const base = `event-${ev.order}`
    return {
      id: base,
      label: <>{ev.order} <span className="font-normal text-ex-ink2">{CLASS_TITLE[ev.class]}</span></>,
      panel: (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="min-w-0 space-y-4">
            <h3 id={`${base}-title`} className="card-title">{card.title}</h3>
            <Still card={card} priority={ev.order === 1} sizes="(min-width: 1024px) 40vw, 100vw" />
            <figure className="m-0 border-l-2 border-ex-line2 pl-3">
              <figcaption className="text-xs font-medium text-ex-ink3">Claude’s one-line summary of the clip</figcaption>
              <blockquote className="m-0 mt-1 text-md text-ex-ink">{trace.summary}</blockquote>
            </figure>
            {hasFrames(card) && (
              <Collapsible summary={<span>All 16 frames Claude read</span>}>
                <FrameSheet card={card} caption="Sixteen frames sampled across the clip, in time order, left to right and top to bottom. Each column of the facts below is one of them." />
              </Collapsible>
            )}
          </div>

          <div className="min-w-0 space-y-6">
            <section aria-labelledby={`${base}-facts`}>
              <h3 id={`${base}-facts`} className="card-title">The facts Claude read</h3>
              {trace.entities.length > 0 && (
                <ul className="m-0 mt-2 flex list-none flex-wrap gap-1.5 p-0">
                  {trace.entities.map((e) => (
                    <li key={e.id}>
                      <Chip>
                        <code className="font-mono">{e.id}</code> {e.type}{e.attrs.length > 0 ? `: ${e.attrs.map((a) => a.replace(/_/g, ' ')).join(', ')}` : ''}
                      </Chip>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3">
                <FactsStrip trace={trace} label={`Facts Claude read from ${card.title}`} />
              </div>
            </section>

            <section aria-labelledby={`${base}-rules`}>
              <h3 id={`${base}-rules`} className="card-title">What the two deployed rules decided</h3>
              <div className="mt-3 grid gap-3">
                {RULES.map((slug) => {
                  const d = decisionOf(ev.decisions, slug)
                  const rule = rules[slug]
                  if (!d || !rule) return null
                  const idx = ev.decisions.indexOf(d)
                  return (
                    <RuleVerdict
                      key={slug}
                      name={RULE_NAME[slug] ?? slug}
                      english={rule.english}
                      decision={d}
                      srcBase={`live.json#events[${ev.order - 1}].decisions[${idx}]`}
                    >
                      {d.fired && d.witness ? (
                        <WhyItFired witness={d.witness} durationMs={trace.duration_ms} />
                      ) : (
                        <p className="text-sm text-ex-ink2">
                          Nothing to explain: the score is not above the threshold, so no alert was raised and no witness was kept.
                        </p>
                      )}
                    </RuleVerdict>
                  )
                })}
              </div>
            </section>
          </div>
        </div>
      ),
    }
  })

  const tau = events[0]?.decisions[0]?.tau
  // Open on the first event where the package rule fired: that is where "Why it fired" has something to show.
  const firstPackageFire = events.find((ev) => decisionOf(ev.decisions, PACKAGE_RULE)?.fired)

  return (
    <>
      <PageHeader
        title={page.title}
        subtitle={page.purpose}
        actions={<Badge tone="pos" icon="check">Observed on the Ring Developer Playground</Badge>}
      />

      <Section
        id="events"
        title="Recorded events"
        description="Five events were simulated in the Ring Developer Playground. Two rules were deployed: the package rule and the vehicle rule."
      >
        <div className="space-y-5">
          <OutcomeSentence outcomes={outcomes} />

          <Card padding="none" className="overflow-hidden">
            <div role="region" aria-label="Outcome of each event for each deployed rule" tabIndex={0} className="overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <caption className="sr-only">For each recorded event, whether each deployed rule fired, with its score.</caption>
                <thead>
                  <tr className="border-b border-ex-line text-xs text-ex-ink3">
                    <th scope="col" className="px-3 py-2.5 sm:px-4 font-medium">Event</th>
                    <th scope="col" className="px-3 py-2.5 sm:px-4 font-medium">Package rule</th>
                    <th scope="col" className="px-3 py-2.5 sm:px-4 font-medium">Vehicle rule</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev) => (
                    <tr key={ev.order} className="border-b border-ex-line last:border-b-0">
                      <th scope="row" className="px-3 py-2.5 sm:px-4 font-medium text-ex-ink">
                        <span className="tabular-nums">{ev.order}</span> {CLASS_TITLE[ev.class]}
                      </th>
                      {RULES.map((slug) => {
                        const d = decisionOf(ev.decisions, slug)
                        if (!d) return <td key={slug} className="px-3 py-2.5 sm:px-4">—</td>
                        const idx = ev.decisions.indexOf(d)
                        return (
                          <td key={slug} className="px-3 py-2.5 sm:px-4">
                            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                              <FiredChip fired={d.fired} />
                              <span className="text-xs tabular-nums text-ex-ink2" data-src={`live.json#events[${ev.order - 1}].decisions[${idx}].score`}>
                                score {fmtScore(d.score)}
                              </span>
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <p className="text-sm text-ex-ink2">
            A rule fires when its score is above the threshold τ
            {tau !== undefined && <> (<Src src="live.json#events[0].decisions[0].tau">{fmtPlain(tau)}</Src> for both rules here)</>}.
            The score is the rule’s robustness on the facts Claude read: above the threshold the rule held, and the size reflects how
            confident the facts were. Stage 1 means the decision was made on the fast model’s facts. In a witness, ρ is the same measure
            for one part of the rule.
          </p>

          <ReplayTabs tabs={tabs} label="Recorded events" defaultId={firstPackageFire ? `event-${firstPackageFire.order}` : undefined} />
        </div>
      </Section>

      <Section id="cost" title="Cost, and the live moment" description="How the events were produced, and what reading one costs.">
        <div className="space-y-4">
          <Disclosure title="How these events were produced" as="h3">
            <p>Simulated in the Ring Developer Playground; events were read by polling event history.</p>
          </Disclosure>
          {cost && (
            <p className="text-md text-ex-ink">
              Reading an event with Claude on Amazon Bedrock costs{' '}
              <Src src="claims.json#cost.per_event_live" className="font-medium">{cost.display}</Src>. Every rule after that runs on the stored facts.
            </p>
          )}
          {liveMoment && (
            <ButtonLink href={liveMoment} variant="secondary" icon="play">Watch the live moment in the video</ButtonLink>
          )}
        </div>
      </Section>
    </>
  )
}
