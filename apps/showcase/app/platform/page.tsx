import { Card, Chip, Disclosure, PageHeader, Section, TextLink, pageMetadata, requirePage } from '@/components/index.ts'
import { ClaimSource, ClaimValue } from '@/components/evidence/ClaimValue.tsx'
import { FeedbackLinks } from '@/components/evidence/FeedbackLinks.tsx'
import { ApiCard } from '@/components/evidence/platform/ApiCard.tsx'
import { FlowSteps } from '@/components/evidence/platform/FlowSteps.tsx'
import { STATUS_LABEL, STATUS_MEANING, StatusBadge, type ApiStatus } from '@/components/evidence/platform/StatusBadge.tsx'
import { blob } from '@/components/evidence/repo.ts'
import { API_ITEMS } from './apis.ts'
import { RING_ARTICLE, RING_PRODUCT_PAGE } from './ring-words.ts'
import { ADDED, EXTENDED, KEPT, SAMPLE_COMMIT, SAMPLE_COMMIT_DATE, SAMPLE_URL, type Change } from './sample.ts'

export const metadata = pageMetadata('platform')

const READ_ONLY_SENTENCE = 'Monitoring needs only read access. The optional Chime action, off by default, is the one call that acts on a device.'

const itemsWith = (status: ApiStatus) => API_ITEMS.filter((i) => i.status === status)

function ChangeList({ title, intro, items }: { title: string; intro?: string; items: Change[] }) {
  return (
    <div>
      <h3 className="text-base font-semibold text-ex-ink">{title}</h3>
      {intro && <p className="mt-0.5 text-sm text-ex-ink2">{intro}</p>}
      <ul className="mt-3 space-y-3">
        {items.map((c) => (
          <li key={c.what} className="text-sm text-ex-ink2">
            <p>{c.what}</p>
            <ul className="mt-0.5 flex flex-wrap gap-x-4">
              {c.where.map((p) => <li key={p} className="min-w-0"><TextLink href={blob(p)} className="inline-block break-all py-1 font-mono text-xs">{p}</TextLink></li>)}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function PlatformPage() {
  const page = requirePage('platform')
  const observed = itemsWith('observed')
  const fixture = itemsWith('fixture')
  const flagged = itemsWith('flag')
  const product = RING_PRODUCT_PAGE
  const article = RING_ARTICLE

  return (
    <>
      <PageHeader title={page.title} subtitle={page.purpose} />

      <Section
        id="capabilities"
        title="The Ring API surface Exemplar uses"
        description="One status label on every item, and the code and tests behind it."
      >
        <div className="space-y-8">
          <Disclosure tone="info" as="p">
            <p><span className="font-medium text-ex-ink">Scope. </span>{READ_ONLY_SENTENCE}</p>
          </Disclosure>

          <dl className="grid gap-3 md:grid-cols-3" aria-label="What the status labels mean">
            {(['observed', 'fixture', 'flag'] as const).map((s) => (
              <Card key={s} padding="sm">
                <dt><StatusBadge status={s} /></dt>
                <dd className="mt-2 text-sm text-ex-ink2">{STATUS_MEANING[s]}</dd>
              </Card>
            ))}
          </dl>

          <div>
            <h3 className="text-md font-semibold tracking-tight text-ex-ink">{STATUS_LABEL.observed}</h3>
            <p className="mt-0.5 text-sm text-ex-ink2">Exercised against the Playground’s simulated device, with the read-only token.</p>
            <ul className="mt-3 space-y-4">{observed.map((item) => <ApiCard key={item.id} item={item} />)}</ul>
          </div>

          <div>
            <h3 className="text-md font-semibold tracking-tight text-ex-ink">{STATUS_LABEL.fixture}</h3>
            <p className="mt-0.5 text-sm text-ex-ink2">Paths the Playground cannot drive, covered by signed fixtures and mocked HTTP.</p>
            <ul className="mt-3 space-y-4">{fixture.map((item) => <ApiCard key={item.id} item={item} />)}</ul>
          </div>

          <p className="text-sm text-ex-ink2">
            While writing the client, we also used the Ring Appstore docs server from our coding assistant to look up endpoints and error codes. It is a
            development tool, not part of the app.
          </p>
        </div>
      </Section>

      <Section id="chime" title="Chime: an optional action" description="Presented separately from the read-only monitoring path.">
        <ul className="space-y-4">{flagged.map((item) => <ApiCard key={item.id} item={item} headingLevel="h3" />)}</ul>
      </Section>

      <Section id="flows" title="Event flows" description="The path each event takes, for the observed route and for the fixture-tested one.">
        <div className="space-y-8">
          <div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <h3 className="text-md font-semibold tracking-tight text-ex-ink">Polling</h3>
              <StatusBadge status="observed" />
            </div>
            <div className="mt-3">
              <FlowSteps
                label="Observed event flow: polling"
                steps={[
                  { title: 'Simulate in the Ring Developer Playground' },
                  { title: 'Poll event history', detail: 'Every 15 seconds, new events only.' },
                  { title: 'Download that event’s video', detail: 'Event-scoped, through the pre-signed redirect.' },
                  { title: 'One Claude perception on Amazon Bedrock', detail: '16 frames into typed facts.' },
                  { title: 'Facts cached as a trace' },
                  { title: 'Every deployed rule scored on the cached facts', detail: 'No further model call.' },
                  { title: 'Alert with its witness', detail: 'The moments and the margin that made the rule true.' },
                ]}
              />
            </div>
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <h3 className="text-md font-semibold tracking-tight text-ex-ink">Webhooks</h3>
              <StatusBadge status="fixture" />
            </div>
            <div className="mt-3">
              <FlowSteps
                label="Fixture-tested event flow: webhooks"
                steps={[
                  { title: 'Signed webhook arrives' },
                  { title: 'Verify the signature', detail: 'HMAC-SHA256 over the raw body, constant-time compare.' },
                  { title: 'Deduplicate', detail: 'On the delivery’s request id.' },
                  { title: 'Forward to the engine' },
                  { title: 'The same pipeline as above', detail: 'Download, perceive once, score every rule, alert with witness.' },
                ]}
              />
            </div>
          </div>
        </div>
      </Section>

      <Section
        id="sample"
        title="Built on Ring’s ring-api-helloworld sample"
        description="The web app started as a fork of Ring’s sample. This is what stayed, what grew and what is new."
      >
        <div className="space-y-6">
          <Card padding="lg">
            <p className="max-w-prose text-sm text-ex-ink2">
              <code className="font-mono text-xs">apps/web</code> is a fork of <TextLink href={SAMPLE_URL}>AmazonAppDev/ring-api-helloworld</TextLink> (MIT
              licence, copyright 2026 Amazon), taken at commit <code className="font-mono text-xs">{SAMPLE_COMMIT}</code> from {SAMPLE_COMMIT_DATE}. The sample
              went into this repository unmodified, in a commit of its own, and its licence file is kept as the licence requires. Everything after that
              commit is Exemplar’s work. The details are in <TextLink href={blob('apps/web/UPSTREAM.md')}>apps/web/UPSTREAM.md</TextLink>.
            </p>
            <p className="mt-3 max-w-prose text-sm text-ex-ink2">
              The sample was a good starting point: its live-view hook worked on the first try, and its processor registry is a clean extension point.
              Each change we made is written up as a suggestion in the friction log (entries <span className="font-mono">APP-1</span> to{' '}
              <span className="font-mono">APP-6</span>).
            </p>
          </Card>
          <div className="grid gap-8 lg:grid-cols-3">
            <ChangeList title="Kept as it is" items={KEPT} />
            <ChangeList title="Extended" intro="Sample files that grew." items={EXTENDED} />
            <ChangeList title="Added" intro="New in Exemplar." items={ADDED} />
          </div>
        </div>
      </Section>

      <Section
        id="fits"
        title="How Exemplar fits with Ring today"
        description="Ring’s own features, in Ring’s words, and what a developer-built app on Ring’s platform adds."
      >
        <div className="grid gap-6 lg:grid-cols-2">
          <Card padding="lg" className="min-w-0">
            <h3 className="text-md font-semibold tracking-tight text-ex-ink">In Ring’s words</h3>
            <div className="mt-4 space-y-5 text-sm text-ex-ink2">
              <div>
                <p>
                  Ring’s <TextLink href={product.url}>{product.title} support page</TextLink> lists these among its “{product.section}”:
                </p>
                <ul className="mt-2 flex flex-wrap gap-2" aria-label="Features Ring lists">
                  {product.features.map((f) => (
                    <li key={f.name}><Chip>{f.name}<span className="text-ex-ink3"> (footnote {f.note})</span></Chip></li>
                  ))}
                </ul>
                <figure className="m-0 mt-3 space-y-2">
                  <blockquote className="m-0 border-l-2 border-ex-line2 pl-3 text-xs leading-5">
                    <span className="font-medium text-ex-ink">Footnote 2.</span> “{product.footnote2}”
                  </blockquote>
                  <blockquote className="m-0 border-l-2 border-ex-line2 pl-3 text-xs leading-5">
                    <span className="font-medium text-ex-ink">Footnote 3.</span> “{product.footnote3}”
                  </blockquote>
                </figure>
              </div>

              <div>
                <p>
                  Ring’s article <TextLink href={article.url}>{article.title}</TextLink> describes three of them:
                </p>
                <dl className="mt-2 space-y-2">
                  {article.benefits.map((b) => (
                    <div key={b.feature}>
                      <dt className="font-medium text-ex-ink">{b.feature}</dt>
                      <dd className="m-0"><blockquote className="m-0 border-l-2 border-ex-line2 pl-3 text-xs leading-5">“{b.text}”</blockquote></dd>
                    </div>
                  ))}
                </dl>
              </div>

              <div>
                <p className="font-medium text-ex-ink">Requirements and availability, as the article states them</p>
                <ul className="mt-2 space-y-1.5">
                  {article.requirements.map((r) => (
                    <li key={r}><blockquote className="m-0 border-l-2 border-ex-line2 pl-3 text-xs leading-5">“{r}”</blockquote></li>
                  ))}
                </ul>
                <blockquote className="m-0 mt-2 border-l-2 border-ex-line2 pl-3 text-xs leading-5">“{article.beta}”</blockquote>
              </div>

              <p className="text-xs text-ex-ink3">Quoted from Ring’s support pages as retrieved on 2026-10-18. Please see those pages for their current wording.</p>
            </div>
          </Card>

          <Card padding="lg" className="min-w-0">
            <h3 className="text-md font-semibold tracking-tight text-ex-ink">What Exemplar adds, as a developer-built app on Ring’s platform</h3>
            <ul className="mt-4 space-y-4 text-sm text-ex-ink2">
              <li>
                <p className="font-medium text-ex-ink">Rules you teach by example, and can read.</p>
                <p className="mt-0.5">
                  A customer marks a few clips as “yes, like this” or “no”. Exemplar returns a rule printed in plain English by code, never paraphrased by a
                  model. One it learned from Playground clips:
                </p>
                <figure className="m-0 mt-2">
                  <blockquote className="m-0 border-l-2 border-ex-accent-line pl-3 text-ex-ink" data-src="claims:rule.example_published">
                    “<ClaimValue id="rule.example_published" />”
                  </blockquote>
                  <figcaption className="mt-1 text-xs text-ex-ink3">Published in <ClaimSource id="rule.example_published" /></figcaption>
                </figure>
              </li>
              <li>
                <p className="font-medium text-ex-ink">Rules that unfold over time.</p>
                <p className="mt-0.5">
                  The rule above holds only when the package has been there “for at least 15 s”. The same language expresses a person picking a package
                  up from the steps.
                </p>
              </li>
              <li>
                <p className="font-medium text-ex-ink">A false-alarm level set before deploying.</p>
                <p className="mt-0.5">
                  You choose the level (<ClaimValue id="calibration.alpha_default" />). The firing threshold is set from randomly sampled clips the rule never
                  trained on, so for events like those, the chance of a false alarm is at most the level you chose. <ClaimSource id="calibration.alpha_default" />.
                </p>
              </li>
              <li>
                <p className="font-medium text-ex-ink">Teaching per camera, for homes and small businesses.</p>
                <p className="mt-0.5">
                  A rule can be limited to one camera or to hours of the day, so each camera carries its own rules: a front door for a household, a
                  storefront or a loading dock for a small business.
                </p>
              </li>
              <li>
                <p className="font-medium text-ex-ink">Actions you choose.</p>
                <p className="mt-0.5">
                  When a rule fires, it can raise a notification in the app, call an outbound webhook into a business system, post to Slack, or, behind
                  a flag, play a chime.
                </p>
              </li>
            </ul>
            <p className="mt-5 border-t border-ex-line pt-4 text-sm text-ex-ink2">
              Exemplar is an app a customer chooses to connect, using the access Ring grants through its developer platform. It sits alongside Ring’s own
              alerts and adds rules of the customer’s own, taught by example. Both can run side by side: Ring’s alerts as they are, and Exemplar’s rules for the moments a household or a business has defined for itself.
            </p>
          </Card>
        </div>
      </Section>

      <Section
        id="appstore"
        title="Designed for the Ring Appstore’s requirements"
        description="Design choices we made with the Appstore in mind. They are not a review outcome: shipping through the Ring Appstore is the next step."
      >
        <ul className="grid gap-3 md:grid-cols-2">
          <Card as="li" padding="sm">
            <p className="font-medium text-ex-ink">Server-side calls only</p>
            <p className="mt-0.5 text-sm text-ex-ink2">
              Every Ring call is made by the engine or the web app’s server routes. The access token is never returned to the browser.{' '}
              <TextLink href={blob('apps/web/app/api/ring/token/route.ts')}>The token route</TextLink>.
            </p>
          </Card>
          <Card as="li" padding="sm">
            <p className="font-medium text-ex-ink">Read-only monitoring</p>
            <p className="mt-0.5 text-sm text-ex-ink2">{READ_ONLY_SENTENCE}</p>
          </Card>
          <Card as="li" padding="sm">
            <p className="font-medium text-ex-ink">The Ring watermark is never covered</p>
            <p className="mt-0.5 text-sm text-ex-ink2">
              Nothing is drawn over the live video, and overlays on clips sit on the bottom edge.{' '}
              <TextLink href={blob('apps/web/app/(exemplar)/_screens/LiveScreen.tsx')}>The live screen</TextLink>.
            </p>
          </Card>
          <Card as="li" padding="sm">
            <p className="font-medium text-ex-ink">Cameras shown by name, never by identifier</p>
            <p className="mt-0.5 text-sm text-ex-ink2">The interface names the camera; device and event identifiers are not displayed.</p>
          </Card>
          <Card as="li" padding="sm">
            <p className="font-medium text-ex-ink">No facial recognition, no cross-property tracking</p>
            <p className="mt-0.5 text-sm text-ex-ink2">Exemplar has no life-safety function. See “Responsible by design” in the <TextLink href={blob('README.md', 'responsible-by-design')}>README</TextLink>.</p>
          </Card>
          <Card as="li" padding="sm">
            <p className="font-medium text-ex-ink">Accessibility</p>
            <p className="mt-0.5 text-sm text-ex-ink2">
              Automated checks: <ClaimValue id="a11y.axe" />, on every screen of the web app. Details and the command are on the{' '}
              <TextLink href="/evidence/#accessibility">Evidence page</TextLink>.
            </p>
          </Card>
        </ul>
      </Section>

      <Section id="feedback" title="Developer feedback" description="What we logged while building on Ring and AWS, with links.">
        <div className="space-y-5">
          <Card padding="lg">
            <figure className="m-0">
              <blockquote className="m-0 max-w-prose border-l-2 border-ex-accent-line pl-3 text-sm text-ex-ink">
                “the Ring API’s combination of event history, event-scoped media download and WHEP live view is the right primitive for event-based AI apps,
                and the Playground got us to a real end-to-end loop in the first working session.”
              </blockquote>
              <figcaption className="mt-2 text-xs text-ex-ink3">
                From our <TextLink href={blob('docs/FEEDBACK.md')}>product feedback</TextLink>.
              </figcaption>
            </figure>
          </Card>
          <FeedbackLinks />
        </div>
      </Section>
    </>
  )
}
