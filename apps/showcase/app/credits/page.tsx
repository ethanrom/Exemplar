import {
  Card, PageHeader, SANDBOX_MEDIA, Section, TextLink, pageMetadata, requirePage,
} from '@/components/index.ts'
import { CreditCard } from '@/components/story/CreditCard.tsx'
import { REPO_URL } from '@/components/story/links.ts'
import { loadCredits, loadLibrary } from '@/lib/data/index.ts'
import type { CreditEntry } from '@/lib/data/types.ts'

export const metadata = pageMetadata('credits')

// Media sources in the order a reader meets them. Entries the data adds later follow, in the data's order.
const ORDER = ['frollard', 'playground-frollard', 'playground-sandbox', 'ringtv-fox', 'meva']
const rank = (e: CreditEntry) => {
  const i = ORDER.indexOf(e.id)
  return i === -1 ? ORDER.length : i
}

export default function CreditsPage() {
  const page = requirePage('credits')
  const credits = loadCredits()
  const library = loadLibrary()
  const media = credits.filter((c) => c.group !== 'software').sort((a, b) => rank(a) - rank(b))
  const software = credits.filter((c) => c.group === 'software')
  const itemsOf = (entry: CreditEntry) => library.filter((c) => c.credit === entry.id)

  const frollard = credits.find((c) => c.id === 'frollard')
  const playgroundFrollard = credits.find((c) => c.id === 'playground-frollard')

  return (
    <>
      <PageHeader title={page.title} subtitle={page.purpose} />

      <Section
        id="media"
        title="Media sources"
        description="Every picture on this site comes from one of these. Each entry gives the author, the licence, the evidence for it and what was changed."
      >
        <div className="grid gap-4">
          {media.map((entry) => (
            <CreditCard key={entry.id} entry={entry} items={itemsOf(entry)} sandboxMedia={SANDBOX_MEDIA} />
          ))}
        </div>
      </Section>

      {frollard && (
        <Section
          id="frollard"
          title="The CC BY video credit"
          description="The doorstep video behind the Playground’s package recordings, credited as its licence asks."
        >
          <Card>
            <p className="text-md text-ex-ink" data-src="credits.json#frollard">
              “{frollard.title}” by {frollard.author}, {frollard.licence}, {frollard.url ? <TextLink href={frollard.url}>{frollard.url}</TextLink> : null}
            </p>
            {frollard.modification && <p className="mt-2 text-sm text-ex-ink2">Changes: {frollard.modification}</p>}
            {playgroundFrollard?.note && <p className="mt-2 text-sm text-ex-ink2">{playgroundFrollard.note} The Playground’s package clip is derived from this video.</p>}
            {frollard.licence_url && (
              <p className="mt-2 text-sm text-ex-ink2">
                Licence: <TextLink href={frollard.licence_url}>{frollard.licence_url.replace(/^https?:\/\//, '')}</TextLink>
              </p>
            )}
          </Card>
        </Section>
      )}

      <Section id="recorded" title="What is recorded" description="The footer of every page carries the full “What runs here” statement for this build.">
        <Card>
          <ul className="m-0 list-disc space-y-1 pl-5 text-sm text-ex-ink2">
            <li>The Playground events, and what each deployed rule decided on them.</li>
            <li>Claude’s reading of every clip: the facts, with a confidence for each.</li>
            <li>The rule sketches the agent wrote, the values the solver chose and the candidate ranks.</li>
            <li>The calibration of the deployed package rule.</li>
            <li>The backtests of the deployed rules over the whole library.</li>
          </ul>
        </Card>
      </Section>

      <Section id="disclosures" title="Disclosures" description="Plain statements about the recordings and the site.">
        <Card>
          <ul className="m-0 list-disc space-y-2 pl-5 text-sm text-ex-ink2">
            <li>This is a supplementary showcase of recorded data. The working project is in the <TextLink href={REPO_URL}>repository</TextLink>.</li>
            <li>Rule text and the English printed beside it come from the rules by code; a model never paraphrases them.</li>
            <li>The Playground events were simulated in the Ring Developer Playground. Ring’s watermark and its Device-ID line are part of the exported frames and are shown whole; this site prints no device, event or account identifiers.</li>
          </ul>
        </Card>
      </Section>

      <Section id="software" title="Software licences" description="The repository, the font and the solver.">
        <ul className="m-0 grid list-none gap-3 p-0 md:grid-cols-3">
          {software.map((s) => (
            <Card as="li" key={s.id}>
              <h3 className="card-title">{s.title}</h3>
              <p className="mt-1 text-sm text-ex-ink2">
                {s.licence_url ? <TextLink href={s.licence_url}>{s.licence}</TextLink> : s.licence}
                {s.author && <> · {s.author}</>}
              </p>
              {s.url && <p className="mt-1 text-sm"><TextLink href={s.url}>{s.url.replace(/^https?:\/\//, '')}</TextLink></p>}
            </Card>
          ))}
        </ul>
      </Section>
    </>
  )
}
