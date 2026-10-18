import type { ReactNode } from 'react'
import type { ClipCard, CreditEntry } from '@/lib/data/types.ts'
import { Badge } from '../Badge.tsx'
import { Card } from '../Card.tsx'
import { Collapsible } from '../Disclosure.tsx'
import { TextLink } from '../Link.tsx'
import type { SandboxMedia } from '../site/config.ts'
import { pluralise } from './format.ts'

const BASIS: Record<CreditEntry['permission']['basis'], string> = {
  cc_by: 'Creative Commons attribution',
  own_work: 'Own work',
  ring_sandbox: 'Ring Developer Playground sandbox',
  open_source: 'Open-source licence',
}

function Row({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-0.5 py-2 first:pt-0 last:pb-0 sm:grid-cols-[9rem_minmax(0,1fr)]">
      <dt className="text-xs font-medium text-ex-ink3 sm:pt-0.5">{term}</dt>
      <dd className="m-0 min-w-0 break-words text-sm text-ex-ink2">{children}</dd>
    </div>
  )
}

/** One media source or software component: who made it, under what licence, the evidence, and what was changed. */
export function CreditCard({
  entry, items, sandboxMedia,
}: { entry: CreditEntry; items: ClipCard[]; sandboxMedia: SandboxMedia }) {
  const pending = entry.permission.status === 'pending_user_decision'
  const framesHidden = pending && sandboxMedia === 'trace'
  return (
    <Card as="article" id={`credit-${entry.id}`} className="scroll-mt-20">
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
        <h3 className="card-title min-w-0 flex-1">{entry.title}</h3>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={pending ? 'warn' : 'pos'} icon={pending ? 'clock' : 'check'}>
            {pending ? 'Owner’s decision pending' : 'Permission cleared'}
          </Badge>
          <Badge tone="neutral" icon={null}>{BASIS[entry.permission.basis]}</Badge>
        </div>
      </div>
      <dl className="mt-3 divide-y divide-ex-line">
        {entry.author && <Row term="By">{entry.author}</Row>}
        {entry.url && <Row term="Source"><TextLink href={entry.url}>{entry.url.replace(/^https?:\/\//, '')}</TextLink></Row>}
        <Row term="Licence">
          {entry.licence_url ? <TextLink href={entry.licence_url}>{entry.licence}</TextLink> : entry.licence}
        </Row>
        {entry.modification && <Row term="Changes made">{entry.modification}</Row>}
        <Row term={`Evidence, checked ${entry.permission.checked_on}`}>{entry.permission.evidence}</Row>
        {entry.note && <Row term="Note">{entry.note}</Row>}
        {framesHidden && <Row term="In this build">The frames of these recordings are not shown; only Claude’s reading of each clip is.</Row>}
      </dl>
      {items.length > 0 && (
        <div className="mt-3">
          <Collapsible summary={<span>{items.length} {pluralise(items.length, 'item')} from this source</span>}>
            <ul className="m-0 grid list-none gap-x-6 gap-y-1 p-0 sm:grid-cols-2">
              {items.map((c) => <li key={c.alias} className="min-w-0 break-words">{c.title}</li>)}
            </ul>
          </Collapsible>
        </div>
      )}
    </Card>
  )
}
