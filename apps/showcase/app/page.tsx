import {
  ButtonLink, Card, RELEASE, Section, SmartLink, StatTile, TextLink, getPage, pageMetadata, pagesFor, releaseAtLeast, requirePage,
} from '@/components/index.ts'
import { FrameStrip, Still } from '@/components/story/Frame.tsx'
import { OutcomeSentence } from '@/components/story/OutcomeSentence.tsx'
import { FiredChip, RuleCard } from '@/components/story/Rule.tsx'
import { Src } from '@/components/story/Src.tsx'
import { fmtScore, words } from '@/components/story/format.ts'
import { REPO_URL, videoUrl } from '@/components/story/links.ts'
import { CLASS_NOUN, PACKAGE_RULE, VEHICLE_RULE, classOutcomes } from '@/components/story/outcomes.ts'
import { Icon } from '@/components/Icon.tsx'
import {
  loadClaims, loadLibrary, loadLive, loadRule, loadRun,
} from '@/lib/data/index.ts'

export const metadata = pageMetadata('home')

// The two doorstep windows of the problem pair, and which frames of each sheet to show (whole frames, in time order).
const LEFT = { alias: 'cc-frollard-00s', cells: [0, 12, 15], label: 'A box left on the steps' }
const RIGHT = { alias: 'cc-frollard-35s', cells: [11, 12, 13], label: 'A box carried past' }

const STEPS = [
  { title: 'Perceive once', text: 'Claude on Amazon Bedrock reads each clip once into facts.' },
  { title: 'Sketch with blanks', text: 'A Strands agent drafts rule sketches.' },
  { title: 'Fill the blanks', text: 'Z3 fills in the numbers.' },
  { title: 'Bound false alarms', text: 'Calibration bounds false alarms.' },
] as const

export default function HomePage() {
  requirePage('home')
  const library = loadLibrary()
  const live = loadLive()
  const claims = loadClaims()
  const deployed = loadRule(PACKAGE_RULE)
  const p1 = loadRun('p1-playground')
  const claim = (id: string) => {
    const c = claims.claims.find((x) => x.id === id)
    if (!c) throw new Error(`home: claims.json has no ${id}`)
    return c
  }
  const cardOf = (alias: string) => {
    const c = library.find((x) => x.alias === alias)
    if (!c) throw new Error(`home: ${alias} is not in the library`)
    return c
  }

  const outcomes = classOutcomes(live)
  const video = videoUrl()
  const hasLab = releaseAtLeast(RELEASE, 'R3')
  const cta = hasLab
    ? { href: getPage('lab').href, label: 'Teach it yourself' }
    : { href: getPage('live').href, label: 'See it run on the Ring Developer Playground' }

  const verdict = (alias: string) => {
    const b = deployed.backtest.find((x) => x.alias === alias)
    if (!b) throw new Error(`home: the package rule has no backtest row for ${alias}`)
    return b
  }
  const pair = [LEFT, RIGHT].map((p) => ({ ...p, card: cardOf(p.alias), verdict: verdict(p.alias), taught: p1.examples.find((e) => e.alias === p.alias) }))
  const taughtIndex = pair.findIndex((p) => p.taught && p.taught.label === 'neg')

  const entryIds = new Set(['lab', 'how', 'live'])
  const entryPages = pagesFor(RELEASE).filter((p) => entryIds.has(p.id))

  return (
    <>
      <section id="hero" aria-labelledby="hero-title" className="mb-12 grid items-start gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-10">
        <div className="min-w-0">
          <h1 id="hero-title" className="text-xl font-semibold tracking-tight text-ex-ink sm:text-2xl lg:text-[1.75rem] lg:leading-9">
            A box carried past your door, and a box left on your steps, look the same to a motion alert.
          </h1>
          <p className="mt-3 text-md text-ex-ink2 sm:text-lg">
            Exemplar lets you teach your Ring camera the difference, by example.
          </p>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <ButtonLink href={cta.href} variant="primary" size="lg" trailingIcon="arrow-right">{cta.label}</ButtonLink>
          </div>
        </div>

        <figure className="m-0 min-w-0" aria-labelledby="problem-caption">
          <div className="grid gap-4">
            {pair.map((p) => (
              <div key={p.alias} className="min-w-0 rounded-xl border border-ex-line bg-ex-panel p-3">
                <p className="mb-2 text-base font-medium text-ex-ink">{p.label}</p>
                <FrameStrip card={p.card} cells={p.cells} />
                <p className="sr-only">{p.card.summary}</p>
                <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ex-ink2">
                  <FiredChip fired={p.verdict.matched} label="Package rule" />
                  <span className="tabular-nums" data-src={`rules/${PACKAGE_RULE}.json#backtest.${p.alias}`}>score {fmtScore(p.verdict.score)}</span>
                </p>
              </div>
            ))}
          </div>
          <figcaption id="problem-caption" className="mt-2 text-xs text-ex-ink3">
            Two windows of a CC BY doorstep video, three whole frames of each, in time order. The verdicts are the deployed package rule’s recorded scores.
            {taughtIndex >= 0 ? <> The {taughtIndex === 0 ? 'first' : 'second'} window is one of the examples the rule was taught from.</> : null}
          </figcaption>
        </figure>
      </section>

      <Section id="about" title="What this site is">
        <Card padding="lg">
          <ul className="m-0 list-none space-y-4 p-0 text-md text-ex-ink2">
            <li>
              <strong className="font-semibold text-ex-ink">Runs in your browser:</strong> the rule checker, the solver and the calibration.
              It’s the same logic as Exemplar’s engine, and the rule checker matches the engine on{' '}
              <Src src="lib/dsl/test/golden/ (7,886 + 30,806 + 5,351 + 72 + 2,110 = 46,225 golden cases)">over 46,000 test cases</Src>.
            </li>
            <li>
              <strong className="font-semibold text-ex-ink">Replayed from real recordings:</strong> what Claude saw in each clip, the agent’s
              drafts, and the live events on the Ring Developer Playground.
            </li>
            <li>
              <strong className="font-semibold text-ex-ink">Why it isn’t live:</strong> the full app signs in to your Ring account and calls
              Claude on Amazon Bedrock. A public page shouldn’t hold your Ring credentials or spend AI credits on every visit, so here you
              explore a real recorded session. The full live loop is in {video ? <TextLink href={video}>the video</TextLink> : 'the video'} and{' '}
              <TextLink href={REPO_URL}>the repository</TextLink>.
            </li>
          </ul>
        </Card>
      </Section>

      <Section id="rule" title="The rule it learned" description="Taught by example from real video (Ring Playground recordings and a real doorstep video) and printed in plain English.">
        <RuleCard
          rule={deployed}
          size="lg"
          showSketch
          showRank={false}
          footer={<p>Printed from the rule by code; never paraphrased by a model.</p>}
        />
      </Section>

      <Section
        id="result"
        title="It ran on the Ring Developer Playground"
        description="Five events were simulated. Two rules were deployed: the package rule and the vehicle rule."
        actions={<ButtonLink href="/live/" variant="secondary" size="sm" trailingIcon="arrow-right">See every event</ButtonLink>}
      >
        <OutcomeSentence outcomes={outcomes} className="mb-4 max-w-3xl text-md text-ex-ink" />
        <ul className="m-0 grid list-none gap-4 p-0 md:grid-cols-3">
          {outcomes.map((o) => {
            const card = cardOf(o.first.alias)
            return (
              <Card as="li" key={o.cls} padding="sm" className="flex min-w-0 flex-col gap-3">
                <Still card={card} sizes="(min-width: 768px) 30vw, 100vw" />
                <div className="min-w-0">
                  <h3 className="text-base font-medium text-ex-ink">
                    <span className="capitalize">{CLASS_NOUN[o.cls]}</span> {o.events === 1 ? 'event' : 'events'}
                    <span className="font-normal text-ex-ink3"> · {o.events === 1 ? 'one recorded' : `${words(o.events)} recorded`}</span>
                  </h3>
                  <p className="mt-0.5 text-xs text-ex-ink3">{card.title}</p>
                </div>
                <p className="mt-auto flex flex-wrap gap-1.5">
                  <FiredChip fired={o.packageFired > 0} label="Package rule" />
                  <FiredChip fired={o.vehicleFired > 0} label="Vehicle rule" />
                </p>
              </Card>
            )
          })}
        </ul>
        <p className="mt-3 text-xs text-ex-ink3">
          Each frame is shown as Ring exported it, watermark and all. A rule that fired on an event is shown as fired; “dropped” means it did not.
        </p>
      </Section>

      <Section id="proof" title="What backs it up" description="Each figure is a recorded result or a published number, and links to where it comes from.">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatTile
            label="Reading one event"
            valueSize="md"
            value={<Src src="claims.json#cost.per_event_live">{claim('cost.per_event_live').display}</Src>}
            caption="Claude on Amazon Bedrock reads each event once."
            href="/live/"
            linkLabel="See it on the Live page"
          />
          <StatTile
            label="Running a rule"
            valueSize="md"
            value={<Src src="claims.json#cost.rule_eval">{claim('cost.rule_eval').display}</Src>}
            caption="Once the facts are read, every rule runs on them with no model call."
            href="/live/"
            linkLabel="See it on the Live page"
          />
          <StatTile
            label="Checked against a second method"
            valueSize="md"
            value={<Src src="claims.json#verify.encoding_cases">{claim('verify.encoding_cases').display}</Src>}
            caption={
              <>
                The solver’s encoding had to agree with a separate evaluator and a brute-force search, with zero mismatches.{' '}
                <Src src="claims.json#verify.planted_bugs">{claim('verify.planted_bugs').display}.</Src>
              </>
            }
            href={getPage('live').href}
            linkLabel="See a rule explain itself"
          />
        </div>
      </Section>

      {video && (
        <Section id="video" title="Watch it" description="The demo video, on YouTube.">
          <ButtonLink href={video} variant="secondary" icon="play">Watch the 2.5-minute video</ButtonLink>
        </Section>
      )}

      <Section id="steps" title="How it works, in four steps" description="From a few examples to a rule that explains every alert.">
        <ol className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <Card as="li" key={s.title} padding="sm">
              <p className="flex items-center gap-2 text-base font-medium text-ex-ink">
                <span aria-hidden="true" className="grid h-5 w-5 shrink-0 place-items-center rounded-full border border-ex-line2 text-xs tabular-nums text-ex-ink2">{i + 1}</span>
                {s.title}
              </p>
              <p className="mt-1.5 text-sm text-ex-ink2">{s.text}</p>
            </Card>
          ))}
        </ol>
        <ul className="m-0 mt-5 grid list-none gap-3 p-0 sm:grid-cols-2 lg:grid-cols-3">
          {entryPages.map((p) => (
            <li key={p.id} className="m-0 min-w-0">
              <SmartLink
                href={p.href}
                className="group flex h-full flex-col rounded-xl border border-ex-line bg-ex-panel p-4 transition-colors hover:bg-ex-raised"
              >
                <span className="flex items-center justify-between gap-2 text-md font-semibold text-ex-ink">
                  {p.label}
                  <Icon name="arrow-right" className="h-4 w-4 text-ex-ink3 transition-transform group-hover:translate-x-0.5" />
                </span>
                <span className="mt-1 text-sm text-ex-ink2">{p.purpose}</span>
              </SmartLink>
            </li>
          ))}
        </ul>
      </Section>
    </>
  )
}
