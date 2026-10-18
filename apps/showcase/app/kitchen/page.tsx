import { notFound } from 'next/navigation'
import {
  Alert, Badge, Button, ButtonLink, Card, CardTitle, Chip, CodeBlock, Collapsible, Disclosure, Dsl, DslBlock, InfoTip,
  PageHeader, ScrollRegion, Section, Stat, StatStrip, StatTile, Tabs, TextLink, Tooltip,
  type Tone,
} from '@/components/index.ts'

export const metadata = { title: 'Component kitchen' }

const TONES: Tone[] = ['neutral', 'pos', 'neg', 'warn', 'info', 'accent']

// A preview-only gallery of the shared components, to check them (axe, keyboard, 375 px) in one place.
// Rendered only when the build sets NEXT_PUBLIC_KITCHEN=1; otherwise the route is a 404 and ships nothing.
export default function KitchenPage() {
  if (process.env.NEXT_PUBLIC_KITCHEN !== '1') notFound()
  return (
    <>
      <PageHeader title="Component kitchen" subtitle="Every shared component in one place. Preview builds only." />

      <Section id="buttons" title="Buttons and links">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary">Primary</Button>
          <Button>Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="primary" size="lg" trailingIcon="arrow-right">Large</Button>
          <Button size="sm" icon="play">Small</Button>
          <Button disabled>Disabled</Button>
          <ButtonLink href="/lab/" variant="primary" trailingIcon="arrow-right">Internal link</ButtonLink>
          <ButtonLink href="https://github.com/ethanrom/Exemplar">External link</ButtonLink>
        </div>
        <p className="mt-3 text-base text-ex-ink2">
          Inline <TextLink href="/how/">internal link</TextLink> and <TextLink href="https://github.com/ethanrom/Exemplar">external link</TextLink>.
        </p>
      </Section>

      <Section id="badges" title="Badges and chips">
        <div className="flex flex-wrap items-center gap-2">
          {TONES.map((t) => <Badge key={t} tone={t}>{t}</Badge>)}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {TONES.map((t) => <Chip key={t} tone={t}>{t}</Chip>)}
          <Chip icon="shield" tone="pos">Cleared</Chip>
        </div>
      </Section>

      <Section id="cards" title="Cards, stat tiles and stats">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Card><CardTitle>Neutral card</CardTitle><p className="mt-1 text-base text-ex-ink2">The standard surface.</p></Card>
          <Card tone="warn"><CardTitle>Warn card</CardTitle><p className="mt-1 text-base text-ex-ink2">Tinted, always with words.</p></Card>
          <StatTile label="Stat tile" value="Observed" caption="One headline value and a caption." href="/live/" linkLabel="See the replay" />
        </div>
        <div className="mt-4">
          <StatStrip label="Example figures">
            <Stat label="First" value="One" hint="a hint" />
            <Stat label="Second" value="Two" tone="pos" icon="check" />
            <Stat label="Third" value="Three" tone="warn" />
            <Stat label="Fourth" value="Four" tone="accent" />
          </StatStrip>
        </div>
      </Section>

      <Section id="code" title="Rule and code blocks">
        <DslBlock text="exists k: Package: holds_for >= 15 (in_zone(k, porch) or in_zone(k, steps))" />
        <div className="mt-3">
          <DslBlock size="sm" text="exists k: Package: holds_for >= ?d in_zone(k, steps)" />
        </div>
        <p className="mt-3 text-base text-ex-ink2">Inline: <Dsl text="holds_for >= ?d in_zone(k, steps)" className="font-mono text-sm" /></p>
        <div className="mt-3">
          <CodeBlock label="Example command">npm run typecheck</CodeBlock>
        </div>
      </Section>

      <Section id="tabs" title="Tabs">
        <Tabs
          label="Example tabs"
          tabs={[
            { id: 'one', label: 'Preset P1', panel: <p className="text-base text-ex-ink2">First panel.</p> },
            { id: 'two', label: 'Second tab', badge: '7', panel: <p className="text-base text-ex-ink2">Second panel.</p> },
            { id: 'three', label: 'Free play', panel: <p className="text-base text-ex-ink2">Third panel.</p> },
          ]}
        />
      </Section>

      <Section id="tooltips" title="Tooltips">
        <div className="flex flex-wrap items-center gap-3 text-base text-ex-ink2">
          <Tooltip content="A short explanation that also appears on keyboard focus.">
            <button type="button" className="btn btn-sm">Hover or focus me</button>
          </Tooltip>
          <span className="inline-flex items-center gap-1">
            Margin <InfoTip label="About the margin">How far the best example sits from the decision boundary.</InfoTip>
          </span>
        </div>
      </Section>

      <Section id="disclosures" title="Disclosure, alerts and expanders">
        <div className="grid gap-3">
          <Disclosure title="How this candidate was selected" as="h3">
            <p>A disclosure sits next to the result it qualifies.</p>
          </Disclosure>
          <Alert tone="info" title="Info">A neutral notice.</Alert>
          <Alert tone="warn" title="Warning">Something to be aware of.</Alert>
          <Collapsible summary="Transcript">The transcript text, collapsed by default.</Collapsible>
        </div>
      </Section>

      <Section id="scroll" title="Scroll region">
        <ScrollRegion label="Wide table" className="max-h-40">
          <table className="w-max min-w-full border-collapse text-left text-sm text-ex-ink2">
            <thead>
              <tr><th scope="col" className="px-3 py-2 text-ex-ink">Claim</th><th scope="col" className="px-3 py-2 text-ex-ink">Source</th><th scope="col" className="px-3 py-2 text-ex-ink">Command</th></tr>
            </thead>
            <tbody>
              {['alpha', 'beta', 'gamma', 'delta', 'epsilon'].map((r) => (
                <tr key={r} className="border-t border-ex-line"><td className="px-3 py-2">{r}</td><td className="px-3 py-2">data file</td><td className="whitespace-nowrap px-3 py-2 font-mono">npm run typecheck -- --pretty false</td></tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      </Section>
    </>
  )
}
