import { Card, TextLink } from '@/components/index.ts'
import { blob } from '../repo.ts'
import { StatusBadge, type ApiStatus } from './StatusBadge.tsx'

export type ApiItem = {
  id: string
  name: string
  status: ApiStatus
  /** What Exemplar uses it for. */
  uses: string
  /** Endpoints, written without Ring identifiers. */
  calls: string[]
  /** Why this label: what was run, or what covers it. */
  basis: string
  /** Code that implements it. */
  code: string[]
  /** Tests that cover it. */
  tests: string[]
  /** Friction-log entries about it, as [id, anchor]. */
  log?: { id: string; anchor: string }[]
}

const LOG = 'docs/FRICTION_LOG.md'

export function ApiCard({ item, headingLevel = 'h4' }: { item: ApiItem; headingLevel?: 'h3' | 'h4' }) {
  const Heading = headingLevel
  return (
    <Card as="li" id={item.id} padding="lg" className="scroll-mt-20">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <Heading className="text-md font-semibold tracking-tight text-ex-ink">{item.name}</Heading>
        <StatusBadge status={item.status} />
      </div>
      <p className="mt-2 max-w-prose text-sm text-ex-ink2">{item.uses}</p>
      {item.calls.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Endpoints">
          {item.calls.map((c) => <li key={c} className="max-w-full break-words rounded border border-ex-line2 bg-ex-bg px-2 py-0.5 font-mono text-xs text-ex-ink2">{c}</li>)}
        </ul>
      )}
      <p className="mt-3 text-sm text-ex-ink2"><span className="font-medium text-ex-ink">Why this label.</span> {item.basis}</p>
      <dl className="mt-3 grid gap-x-8 gap-y-3 text-sm md:grid-cols-2">
        <div className="min-w-0">
          <dt className="label">Code</dt>
          <dd className="mt-1">
            <ul>
              {item.code.map((p) => <li key={p}><TextLink href={blob(p)} className="inline-block break-all py-1 font-mono text-xs">{p}</TextLink></li>)}
            </ul>
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="label">Tests{item.log ? ' and notes' : ''}</dt>
          <dd className="mt-1">
            <ul>
              {item.tests.map((p) => <li key={p}><TextLink href={blob(p)} className="inline-block break-all py-1 font-mono text-xs">{p}</TextLink></li>)}
              {item.log?.map((l) => (
                <li key={l.id}><TextLink href={blob(LOG, l.anchor)} className="inline-block py-1 text-xs">Friction log entry <span className="font-mono">{l.id}</span></TextLink></li>
              ))}
            </ul>
          </dd>
        </div>
      </dl>
    </Card>
  )
}
